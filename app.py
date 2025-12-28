"""
GlobalProxy Master - v2.0 智能内容识别版
1. 增加 HTTP 状态码自动切换功能 (403/429等)
2. 增加 响应关键字 自动切换功能 (验证码/拦截等)
3. 优化 TCP 转发逻辑，支持重连探测
"""
import asyncio
import re
import json
import os
import time
import threading
from datetime import datetime
from typing import List, Dict, Optional, Set
from flask import Flask, render_template_string, request, jsonify
from flask_cors import CORS
import httpx

# ==================== 核心配置 ====================
CONFIG = {
    "proxy_hub_port": 8888,
    "web_port": 5000,
    "data_file": "proxies_data.json",
    "source_config": "api_sources.json", 
    "timeout": 10,
    "max_concurrent": 100,
    "max_retries": 5,          # 最大切换重试次数
    "fail_threshold": 3,
    "fetch_proxy": "http://127.0.0.1:7897",
    "use_fetch_proxy": True,
    
    # --- 新增：智能切换触发条件 ---
    "switch_status_codes": [403, 429, 502, 503, 504],  # 遇到这些状态码自动换 IP
    "switch_keywords": ["验证码", "访问被拒绝", "Forbidden", "CAPTCHA", "IP限制", "安全验证"] # 遇到这些词自动换 IP
}

class ProxyDatabase:
    def __init__(self):
        self.apis: List[Dict] = []
        self.proxies: List[Dict] = []
        self.alive_proxies: List[Dict] = []
        self.blacklist: Set[str] = set()
        self.api_id_counter = 0
        self.load_from_disk()

    def add_api(self, url: str, tag: str = ""):
        if any(api['url'] == url for api in self.apis): return False
        self.api_id_counter += 1
        self.apis.append({"url": url, "tag": tag, "id": self.api_id_counter})
        self.save_to_disk()
        return True
        
    def remove_api(self, api_id: int):
        self.apis = [a for a in self.apis if a["id"] != api_id]
        self.save_to_disk()
        
    def add_proxies(self, proxies: List[Dict]):
        existing = {p["proxy"] for p in self.proxies}
        for proxy in proxies:
            if proxy["proxy"] not in existing:
                self.proxies.append(proxy)
                existing.add(proxy["proxy"])
        self.save_to_disk()

    def update_proxy_status(self, proxy: str, status: Dict):
        for p in self.proxies:
            if p["proxy"] == proxy:
                p.update(status)
                if status.get("alive") and proxy in self.blacklist:
                    self.blacklist.remove(proxy)
                break 

    def get_alive_proxies(self, region: str = "all") -> List[Dict]:
        pool = [p for p in self.alive_proxies if p["proxy"] not in self.blacklist]
        if region == "domestic": return [p for p in pool if p.get("region") == "国内"]
        elif region == "foreign": return [p for p in pool if p.get("region") == "国外"]
        return pool

    def save_to_disk(self):
        data = {"apis": self.apis, "api_counter": self.api_id_counter, "proxies": self.proxies}
        with open(CONFIG["data_file"], "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_from_disk(self):
        if os.path.exists(CONFIG["data_file"]):
            try:
                with open(CONFIG["data_file"], "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.apis = data.get("apis", [])
                    self.api_id_counter = data.get("api_counter", 0)
                    self.proxies = data.get("proxies", [])
                    self.alive_proxies = [p for p in self.proxies if p.get("alive")]
            except: pass

db = ProxyDatabase()

# ==================== 智能转发服务 (8888) ====================


class ProxyHubServer:
    def __init__(self):
        self.current_index = 0
        self.mode = "all"
        self.fail_counts: Dict[str, int] = {}

    def get_next_proxy(self) -> Optional[str]:
        proxies = db.get_alive_proxies(self.mode)
        if not proxies: return None
        proxy = proxies[self.current_index % len(proxies)]
        self.current_index += 1
        return proxy["proxy"]

    async def pipe(self, reader, writer):
        try:
            while not reader.at_eof():
                data = await reader.read(4096)
                if not data: break
                writer.write(data)
                await writer.drain()
        except: pass
        finally: writer.close()

    async def handle_client(self, reader, writer):
        # 1. 预读客户端的请求头（用于重连时重新发送）
        try:
            client_header = await asyncio.wait_for(reader.read(4096), timeout=3)
            if not client_header: return writer.close()
        except: return writer.close()

        success = False
        for _ in range(CONFIG["max_retries"]):
            target_proxy = self.get_next_proxy()
            if not target_proxy: break
            
            try:
                h, p = target_proxy.split("://")[-1].split(":")
                remote_reader, remote_writer = await asyncio.wait_for(
                    asyncio.open_connection(h, int(p)), timeout=3
                )
                
                # 发送请求头到代理
                remote_writer.write(client_header)
                await remote_writer.drain()
                
                # 2. 检查响应内容（仅对非 CONNECT 请求有效）
                if not client_header.startswith(b"CONNECT"):
                    response_start = await asyncio.wait_for(remote_reader.read(4096), timeout=5)
                    
                    # 检查状态码
                    status_match = re.search(b"HTTP/1\\.[01] (\\d{3})", response_start)
                    should_switch = False
                    if status_match:
                        code = int(status_match.group(1))
                        if code in CONFIG["switch_status_codes"]:
                            print(f"[*] 命中状态码 {code}，正在自动更换 IP...")
                            should_switch = True
                    
                    # 检查关键词
                    if not should_switch:
                        for kw in CONFIG["switch_keywords"]:
                            if kw.encode('utf-8') in response_start:
                                print(f"[*] 命中关键字 '{kw}'，正在自动更换 IP...")
                                should_switch = True
                                break
                    
                    if should_switch:
                        self.fail_counts[target_proxy] = self.fail_counts.get(target_proxy, 0) + 1
                        remote_writer.close()
                        continue # 触发重试逻辑，尝试下一个 IP

                    # 内容正常，将预读的数据包还给客户端
                    writer.write(response_start)
                    await writer.drain()

                # 3. 建立正常双向管道
                self.fail_counts[target_proxy] = 0
                await asyncio.gather(self.pipe(reader, remote_writer), self.pipe(remote_reader, writer))
                success = True
                break
            except:
                self.fail_counts[target_proxy] = self.fail_counts.get(target_proxy, 0) + 1
                if self.fail_counts[target_proxy] >= CONFIG["fail_threshold"]:
                    db.blacklist.add(target_proxy)
                continue
        
        if not success: writer.close()

    async def run(self):
        server = await asyncio.start_server(self.handle_client, '127.0.0.1', CONFIG["proxy_hub_port"])
        async with server: await server.serve_forever()

proxy_hub_server = ProxyHubServer()

# ==================== Flask API (保持原有逻辑) ====================
app = Flask(__name__)
CORS(app)

@app.route('/')
def index():
    with open('index.html', 'r', encoding='utf-8') as f: return render_template_string(f.read())

@app.route('/api/stats')
def get_stats():
    alive = [p for p in db.proxies if p.get("alive") and p["proxy"] not in db.blacklist]
    return jsonify({
        "total": len(db.proxies), "alive": len(alive), 
        "domestic": len([p for p in alive if p.get("region") == "国内"]), 
        "foreign": len([p for p in alive if p.get("region") == "国外"]),
        "blacklist": len(db.blacklist)
    })

@app.route('/api/load_local_sources', methods=['POST'])
def load_local_sources():
    stype = request.json.get('type', 'basic')
    if not os.path.exists(CONFIG["source_config"]):
        return jsonify({"success": False, "message": "未找到配置文件"})
    try:
        with open(CONFIG["source_config"], "r", encoding="utf-8") as f:
            data = json.load(f)
            sources = data.get(stype, {}).get("sources", [])
            added = 0
            for s in sources:
                if db.add_api(s['url'], s['tag']): added += 1
            return jsonify({"success": True, "count": added})
    except Exception as e: return jsonify({"success": False, "message": str(e)})

@app.route('/api/fetch_selected_apis', methods=['POST'])
def fetch_selected():
    ids = request.json.get('ids', [])
    use_proxy = request.json.get('use_proxy', CONFIG.get("use_fetch_proxy", False))
    targets = [a for a in db.apis if a['id'] in ids]
    
    async def fetch_single_api(client, api):
        try:
            print(f"[*] 正在并发请求: {api['url']}")
            resp = await client.get(api['url'])
            if resp.status_code == 200:
                matches = re.findall(r'\b(?:\d{1,3}\.){3}\d{1,3}:\d+\b', resp.text)
                proto = "socks5" if "socks5" in api['url'].lower() else "http"
                return [{"proxy": f"{proto}://{m}", "alive": False} for m in set(matches)]
        except Exception as e:
            print(f"[!] 采集失败 {api['url']}: {e}")
        return []

    async def run_fetch_all():
        proxies = CONFIG.get("fetch_proxy") if use_proxy else None
        limits = httpx.Limits(max_keepalive_connections=20, max_connections=50)
        async with httpx.AsyncClient(proxies=proxies, timeout=20, limits=limits, verify=False) as client:
            tasks = [fetch_single_api(client, api) for api in targets]
            results = await asyncio.gather(*tasks)
            all_p = []
            for r in results: all_p.extend(r)
            db.add_proxies(all_p)
            return len(all_p)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try: count = loop.run_until_complete(run_fetch_all())
    finally: loop.close()
    return jsonify({"success": True, "count": count})

@app.route('/api/add_api', methods=['POST'])
def add_api_route():
    success = db.add_api(request.json['url'], request.json.get('tag', ''))
    return jsonify({"success": success})

@app.route('/api/remove_api/<int:api_id>', methods=['DELETE'])
def remove_api_route(api_id):
    db.remove_api(api_id)
    return jsonify({"success": True})

@app.route('/api/clear_apis', methods=['POST'])
def clear_apis():
    db.apis = []
    db.save_to_disk()
    return jsonify({"success": True})

@app.route('/api/detect_all', methods=['POST'])
def detect_all():
    async def run_detect():
        async def task(p_str):
            try:
                start = time.time()
                async with httpx.AsyncClient(proxies={"http://": p_str, "https://": p_str}, timeout=3) as c:
                    r = await c.get("http://www.baidu.com")
                    if r.status_code == 200:
                        res = {"proxy": p_str, "alive": True, "latency": int((time.time()-start)*1000), "region": "国内"}
                        try:
                            r2 = await c.get("http://www.google.com", timeout=2)
                            if r2.status_code == 200: res["region"] = "国外"
                        except: pass
                        return res
            except: pass
            return {"proxy": p_str, "alive": False, "latency": 9999, "region": "未知"}
        return await asyncio.gather(*(task(p["proxy"]) for p in db.proxies))
    loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
    results = loop.run_until_complete(run_detect()); loop.close()
    db.alive_proxies = [r for r in results if r["alive"]]
    for r in results: db.update_proxy_status(r["proxy"], r)
    db.save_to_disk()
    return jsonify({"success": True, "count": len(db.alive_proxies)})

@app.route('/api/list_apis')
def list_apis(): return jsonify(db.apis)

@app.route('/api/list_proxies')
def list_proxies():
    sorted_p = sorted(db.proxies, key=lambda x: (not x.get("alive", False), x["proxy"] in db.blacklist))
    return jsonify(sorted_p[:100])

@app.route('/api/manual_switch', methods=['POST'])
def manual_switch():
    proxy_hub_server.current_index += 1
    return jsonify({"success": True})

@app.route('/api/clear_blacklist', methods=['POST'])
def clear_blacklist():
    db.blacklist.clear()
    proxy_hub_server.fail_counts.clear()
    return jsonify({"success": True})

@app.route('/api/update_hub_mode', methods=['POST'])
def update_hub_mode():
    proxy_hub_server.mode = request.json.get('mode', 'all')
    return jsonify({"success": True})

@app.route('/api/save_persistence', methods=['POST'])
def save_persistence():
    db.save_to_disk()
    return jsonify({"success": True, "message": "数据已持久化保存"})

@app.route('/api/import_proxies', methods=['POST'])
def import_proxies():
    data = request.json
    matches = re.findall(r'\b(?:\d{1,3}\.){3}\d{1,3}:\d+\b', data['text'])
    proxies = [{"proxy": f"{data['protocol']}://{m}", "alive": False} for m in set(matches)]
    db.add_proxies(proxies)
    return jsonify({"success": True, "count": len(proxies)})

@app.route('/api/clear_dead', methods=['POST'])
def clear_dead():
    db.proxies = [p for p in db.proxies if p.get("alive")]
    return jsonify({"success": True})

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5000, threaded=True), daemon=True).start()
    asyncio.run(proxy_hub_server.run())