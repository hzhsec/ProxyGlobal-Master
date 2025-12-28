# ProxyGlobal Master v2.0

### 智能内容识别与高性能分布式代理分发系统

**ProxyGlobal Master** 是一款专为渗透测试、信息搜集及自动化采集设计的深度代理管理工具。在 v2.0 版本中，系统引入了**应用层智能识别逻辑**，能够根据目标网站返回的状态码和内容自动切换 IP，彻底解决被 WAF 拦截的问题。

------

##  v2.0 核心特性

- **智能响应识别 (New)**：实时检测 HTTP 状态码（如 403、429）和响应体关键字（如“验证码”、“访问被拒绝”），发现被拦截时自动无感切换下一个代理。
- **真正并发采集**：采用 `asyncio.gather` 并行技术，秒级完成对多个 GitHub 远程源的采集，不再因单源延迟阻塞整体进度。
- **自动重连与黑名单**：内置 5 次自动切换重试机制，并将连续失效的 IP 锁定至黑名单，保障链路极速稳定。
- **精准归属地识别**：集成 GeoIP2 数据库（需手动配置），支持“仅国内”、“仅国外”分流策略。
- **数据持久化**：所有源配置及检测存活的代理均保存至 `proxies_data.json`，实现重启后秒开使用，无需重复检测。
- **采集代理支持**：支持配置本地采集代理（如 Clash 7897 端口），解决国内无法直接拉取 GitHub 代理源的问题。

------

## 环境配置

1. **Python 版本**：推荐 **Python 3.8**（已完成兼容性优化）。

2. **安装依赖**：

   ```
   python -m venv venv
   venv\Scripts\activate.bat
   ```

   ```
   pip install -r requirements.txt -i -i https://mirrors.aliyun.com/pypi/simple/
   ```

3. **GeoIP 配置**（可选）：

   - 从 [GeoLite2-Country.mmdb下载](https://github.com/P3TERX/GeoLite.mmdb) 下载 `GeoLite2-Country.mmdb`。
   - 将文件放入程序根目录，即可开启国内外地区识别功能。

------

## 进阶配置项 (`app.py` / `CONFIG`)

您可以在 `app.py` 的 `CONFIG` 字典中深度定制行为：

| **配置项**            | **默认值**                           | **功能描述**                         |
| --------------------- | ------------------------------------ | ------------------------------------ |
| `switch_status_codes` | `[403, 429, 502, 503, 504]`          | 遇到这些 HTTP 状态码时自动更换 IP    |
| `switch_keywords`     | `["验证码", "Forbidden", "CAPTCHA"]` | 响应内容包含这些词时自动更换 IP      |
| `fetch_proxy`         | `http://127.0.0.1:7897`              | 用于采集 GitHub 远程源的本地加速代理 |
| `max_retries`         | `5`                                  | 单次请求失败后的最大自动切跳次数     |
| `fail_threshold`      | `3`                                  | 代理连续连接失败多少次后拉入黑名单   |

------

## 操作指南

### 1. 启动服务

```
python app.py
```
<img width="1426" height="764" alt="image" src="https://github.com/user-attachments/assets/a5afb2ee-7090-4006-a2c2-31b9d6eb1d46" />

- **Web 管理端**：`http://127.0.0.1:5000`
- **代理分发 Hub**：`127.0.0.1:8888`

### 2. 采集与保存

- 在管理页面点击 **“加载代理源”**，从 `api_sources.json` 预设中提取 URL。

<img width="822" height="485" alt="image" src="https://github.com/user-attachments/assets/7e3b032c-7893-431c-a274-78ae89c28c27" />

- 勾选目标源并点击 **“采集勾选源”**。
<img width="813" height="744" alt="image" src="https://github.com/user-attachments/assets/a932f246-da50-41f5-a166-454ac72112c6" />

- 检测采集代理活性(一定要做)
<img width="1326" height="567" alt="image" src="https://github.com/user-attachments/assets/51fcf229-33ac-4ff6-8503-f9875bfa4bb1" />

- 耐心等待,获取到有效代理

<img width="1430" height="717" alt="image" src="https://github.com/user-attachments/assets/ba87097f-68ef-448b-876d-4bb67183fb61" />


- 点击 **“保存当前状态”**，确保数据在下次启动时依然可用。

### 3. 应用代理转发

- 将您的浏览器（SwitchyOmega）或爬虫脚本代理设为 `127.0.0.1:8888`。
- 系统会根据您在界面选定的“轮询模式”（全部/国内/国外）自动筛选 IP 进行分发。

------

## 法律免责声明

本工具仅用于授权环境下的安全研究与渗透测试。用户在使用过程中应遵守当地法律法规，严禁利用本工具从事任何未经授权的非法网络活动。因使用不当产生的后果由使用者自行承担。

