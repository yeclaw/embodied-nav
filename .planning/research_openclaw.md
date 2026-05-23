# OpenClaw + Flask 技术调研

> 调研时间：2026-05-23
> 目标：embodied-nav 具身导航项目技术选型

---

## 1. OpenClaw Skill 编写规范

### Skill 文件结构

OpenClaw Skill 的标准结构：

```
skill-name/
  SKILL.md              # 元数据 + 使用说明（必需）
  scripts/              # Python helper 脚本（可选）
  references/           # 详细文档（按需加载）
  assets/               # 模板/媒体资源
```

**SKILL.md 前台格式（必需）**：

```yaml
---
name: my-skill
description: "简短触发描述，触发词出现在此处时激活 Skill"
metadata:
  {
    "openclaw":
      {
        "emoji": "🎯",
        "requires": { "bins": ["python3"] },
        "config": { "env": { "MY_API_KEY": { "description": "...", "default": "..." } } },
        "install": [{ "id": "brew", "kind": "brew", "formula": "python3" }],
      },
  }
---

# Skill 名称

## 适用场景
...

## 命令/调用方式
...
```

### Skill 的两种形态

OpenClaw 中存在**两种 Skill 形态**，定位不同：

| 形态 | 说明 | 示例 |
|------|------|------|
| **内置 Skill（文档型）** | SKILL.md 纯文本描述工具调用方式，供 Agent 在对话中理解何时、如何调用外部脚本或命令 | weather, himalaya, openai-whisper |
| **Tool Plugin（JS/TypeScript）** | 通过 `defineToolPlugin` 注册为真正的 Agent 可调用 Tool，有 execute 函数 | Slack/Discord 消息 Plugin |

**embodied-nav 项目适用的是第一种（文档型 Skill）**，因为：
- 导航逻辑是 Python Flask 后端，不在 OpenClaw 进程内
- Agent 通过 `exec` 工具调用 shell 命令启动 Python 脚本
- SKILL.md 描述如何构建 HTTP 请求到 Flask 后端

### 文档型 Skill 的触发机制

Agent 在对话中发现匹配关键词（如 `navigate`、`导航`、`go to`）时：
1. 读取 SKILL.md 中描述的命令格式
2. 通过 `exec` 工具执行 shell 命令或 Python 脚本
3. 脚本内通过 `requests` 库向 Flask 后端发 HTTP 请求

**典型命令格式示例**（searxng skill）：

```bash
uv run {baseDir}/scripts/searxng.py search "query" -n 10
```

**Python 脚本架构**（minimax-speech）：

```python
#!/usr/bin/env python3
import argparse, os, sys, json

# 从环境变量读取认证
API_KEY = os.getenv("MINIMAX_TOKEN_PLAN_KEY") or os.getenv("MINIMAX_API_KEY")

def navigate(destination: str, mode: str = "fastest") -> dict:
    """调用导航 API"""
    import requests
    try:
        resp = requests.post(
            "http://127.0.0.1:5000/api/navigate",
            json={"destination": destination, "mode": mode},
            timeout=10
        )
        resp.raise_for_status()
        return {"success": True, "result": resp.json()}
    except requests.exceptions.RequestException as e:
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination")
    parser.add_argument("--mode", default="fastest")
    args = parser.parse_args()
    result = navigate(args.destination, args.mode)
    print(json.dumps(result))
```

### Tool Plugin 的注册方式（进阶）

如果需要将导航能力注册为真正的 OpenClaw Tool（而不只是 exec 命令），需要写 TypeScript Tool Plugin：

```typescript
// defineToolPlugin 方式（OpenClaw 2026.5.17+）
import { defineToolPlugin } from "openclaw/plugin-sdk/tool-plugin";

export default defineToolPlugin({
  id: "embodied-nav",
  name: "Embodied Navigation",
  description: "Navigate robot to destination via local Flask backend.",
  configSchema: Type.Object({
    baseUrl: Type.Optional(Type.String({ description: "Flask backend URL." })),
  }),
  tools: (tool) => [
    tool({
      name: "nav_execute",
      label: "Execute Navigation",
      description: "Send navigation command to robot.",
      parameters: Type.Object({
        destination: Type.String({ description: "Target location." }),
      }),
      async execute({ destination }, config) {
        const baseUrl = config.baseUrl ?? "http://127.0.0.1:5000";
        const resp = await fetch(`${baseUrl}/api/navigate`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ destination }),
        });
        return { success: true, data: await resp.json() };
      },
    }),
  ],
});
```

这种方式需要 `openclaw plugins init` 脚手架，不推荐在第一阶段使用。

### auth/api key 配置机制

通过 SKILL.md 的 `metadata.openclaw.config.env` 声明环境变量：

```yaml
metadata:
  openclaw:
    config:
      env:
        FLASK_BASE_URL:
          description: "Flask backend URL"
          default: "http://127.0.0.1:5000"
          required: true
```

环境变量通过 OpenClaw 配置系统注入，Agent 在 exec 命令时会自动使用。

---

## 2. OpenClaw 与 Python 后端的通信

### Tool 函数中 `requests.post` 可行性

**完全可行**。文档型 Skill 的 Python 脚本运行在 exec 工具的 shell 环境中，可以自由使用 `requests` 库向本地 Flask 发送请求。

关键路径：
```
User message → OpenClaw LLM → exec tool → python script → requests.post(Flask) → result → exec output → LLM → response
```

### Flask 后端端口

**推荐默认端口：5000**（Flask 默认端口）。也可以使用其他端口如 5001，通过环境变量配置。

```python
# Flask app startup
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
```

如果需要支持同一局域网内多设备访问，使用 `host="0.0.0.0"`（注意安全）。

### Flask 后端挂掉时的错误处理

```python
import requests

def nav_execute(destination: str) -> dict:
    try:
        resp = requests.post(
            "http://127.0.0.1:5000/api/navigate",
            json={"destination": destination},
            timeout=10  # 超时设置
        )
        resp.raise_for_status()
        return {"success": True, "data": resp.json()}
    except requests.exceptions.ConnectionError:
        return {"success": False, "error": "Flask backend not running. Start with: python server.py"}
    except requests.exceptions.Timeout:
        return {"success": False, "error": "Navigation request timed out."}
    except requests.exceptions.HTTPError as e:
        return {"success": False, "error": f"HTTP {e.response.status_code}: {e.response.text}"}
```

LLM 会读取这个返回的 dict，并在回复中告知用户后端未运行。

### session/chat history 作为 context 传入 Tool

**直接 exec 方式**：session history 不直接传入 Tool 函数，而是通过 shell 命令行参数传递。

```python
import argparse, json, sys

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", required=True)
    parser.add_argument("--session-context", default="{}")  # JSON 字符串
    args = parser.parse_args()
    
    context = json.loads(args.session_context)
    # 可以从 context 中读取之前的导航历史、当前位置等
    
    result = do_navigate(args.destination, context)
    print(json.dumps(result))

if __name__ == "__main__":
    main()
```

OpenClaw 的 exec 工具支持将对话中的上下文信息作为命令行参数传入脚本。

---

## 3. Flask MJPEG 推流方案

### 最小可用的 MJPEG Streaming 代码框架

```python
# flask_mjpeg_stream.py
from flask import Flask, Response, request
import cv2
import numpy as np
import threading

app = Flask(__name__)

# 全局帧缓冲区
current_frame = None
lock = threading.Lock()

def generate_frames():
    """MJPEG 流生成器"""
    global current_frame
    while True:
        with lock:
            if current_frame is None:
                continue
            # numpy array → JPEG
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 85]
            _, buffer = cv2.imencode('.jpg', current_frame, encode_param)
            jpg_bytes = buffer.tobytes()
        
        # 构建 MJPEG 多部分帧
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + jpg_bytes + b'\r\n')

@app.route('/video_feed')
def video_feed():
    """MJPEG 流端点"""
    return Response(
        generate_frames(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )

@app.route('/api/update_frame', methods=['POST'])
def update_frame():
    """接收 numpy array 帧并更新全局缓冲区"""
    global current_frame
    data = request.get_json()
    # 假设发送的是 base64 编码的图像或原始字节
    # 这里简化处理，实际从机器人获取帧的方式各异
    return {"status": "ok"}

def update_from_array(frame: np.ndarray):
    """从外部代码更新当前帧（用于机器人控制循环）"""
    global current_frame
    with lock:
        current_frame = frame.copy()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, threaded=True)
```

### numpy array → JPEG 效率（M1 Pro 实测估算）

M1 Pro（Apple Silicon）使用 `cv2.imencode` 利用了苹果的 Accelerate 框架和 AVFoundation 硬件加速。

实测估算（理论值，仅供参考，建议实际 Benchmark）：

| 分辨率 | JPEG quality | 每帧编码耗时 | 理论最大 FPS |
|--------|-------------|-------------|-------------|
| 640×480 | 85 | ~2-5ms | 200+ FPS |
| 1280×720 | 85 | ~5-12ms | 80-100 FPS |
| 1920×1080 | 85 | ~10-25ms | 40-60 FPS |

**实际导航场景建议**：
- 目标帧率：15-30 FPS（足够流畅）
- 推荐分辨率：640×480 或 1280×720
- JPEG quality：80-85（平衡画质与带宽）

### 前端 HTML 直接加载 MJPEG 流

```html
<!DOCTYPE html>
<html lang="zh">
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Robot View</title>
  <style>
    body { margin: 0; background: #111; display: flex; flex-direction: column; align-items: center; }
    img#stream { max-width: 100%; border: 2px solid #333; }
    #status { color: #0f0; font-family: monospace; padding: 10px; }
  </style>
</head>
<body>
  <img id="stream" src="http://127.0.0.1:5000/video_feed" alt="Robot Camera">
  <div id="status">Connecting...</div>

  <script>
    const img = document.getElementById('stream');
    img.onload = () => { document.getElementById('status').textContent = 'LIVE'; };
    img.onerror = () => { document.getElementById('status').textContent = 'DISCONNECTED'; };
  </script>
</body>
</html>
```

一行 `<img src="...">` 即可加载 MJPEG 流，浏览器自动处理多部分边界解析。

### 延迟实测数据（理论估算）

MJPEG 端到端延迟链路：
```
相机采集 → 编码传输 → Flask 接收 → 全局缓冲区 → 下一帧被请求 → 解码渲染
```

每帧总延迟 ≈ `1/FPS`（30FPS ≈ 33ms 帧间隔）+ 编码延迟 + 网络延迟

- 理论总延迟（30FPS，720p）：~50-80ms
- 实际浏览器渲染额外：~16ms（60Hz 屏幕）
- **实测建议**：使用 `ping` 测量 RTT，实际端到端应在 50-150ms 范围

### 替代方案对比

| 方案 | 延迟 | 实现复杂度 | 带宽占用 | 适用场景 | 推荐 |
|------|------|-----------|---------|---------|------|
| **MJPEG** | 低（~50-150ms） | 极低 | 中（每帧独立 JPEG） | 嵌入式摄像机、简单实现 | ⭐ 首选 |
| **WebSocket** | 极低（<50ms） | 中 | 低（二进制帧） | 需要双向通信、实时控制 | ⭐ 备选 |
| **HLS/DASH** | 高（3-10s） | 高 | 低（分片） | 广域网分发、不适合实时控制 | ✗ 不适合 |
| **WebRTC** | 极低（<30ms） | 高 | 极低 | 低延迟实时互动 | 过度设计 |

**结论**：MJPEG 是嵌入式机器人场景的最佳选择，实现极简、延迟可接受、浏览器原生支持。

---

## 4. 自然语言对话闭环

### "任务完成"信号后的自动询问

OpenClaw 的 Tool 返回值会作为 LLM 对话上下文的一部分。**Tool 返回值的措辞决定了后续对话走向**。

### 全链路流程设计

```
用户: "去厨房" 
  → OpenClaw LLM 
  → exec Tool: python nav.py --dest "厨房"
  → 脚本执行 requests.post Flask
  → Flask 返回 {"status": "arrived", "position": "厨房"}
  → exec output → LLM
  → LLM 根据返回内容决定回复
  → "已到达厨房！需要我做其他事情吗？"
```

### 在 Tool 返回值中嵌入后续询问

```python
def navigate(destination: str) -> dict:
    result = call_flask_navigate(destination)
    if result["status"] == "arrived":
        return {
            "success": True,
            "result": result,
            "next_prompt": "已到达{destination}。我可以帮你做：\n1. 再去一个地方\n2. 查看周围环境\n3. 执行其他任务\n请告诉我下一步？"
        }
    else:
        return {
            "success": False,
            "error": result.get("error", "Unknown error"),
            "next_prompt": "导航失败了：{error}。我可以重试或换个目标地点，要怎么做？"
        }
```

OpenClaw LLM 会将 `next_prompt` 字段的内容整合进回复。

### OpenClaw 判断导航成功/失败

通过返回值结构化数据：

```python
# 成功
return {"success": True, "arrived": True, "location": "厨房", "distance_m": 3.2}

# 失败
return {"success": False, "error": "path_blocked", "message": "检测到路径被阻挡"}
```

OpenClaw LLM 能理解这些字段并生成相应的自然语言回复。

---

## 5. 可视化界面设计

### 现代化 HTML 交互界面核心要素

基于嵌入式/Web 控制面板最佳实践：

**核心布局**：
- 全屏或大半屏视频流作为主视觉（70%+ 视觉权重）
- 底部或侧边悬浮控制面板（方向按钮、状态指示）
- 顶部状态栏（连接状态、电量、当前位置）

**关键要素**：
```html
<!-- 响应式布局 -->
<div class="container">
  <!-- 视频流 -->
  <div class="video-wrapper">
    <img src="http://127.0.0.1:5000/video_feed">
    <div class="status-badge">● LIVE</div>
  </div>
  
  <!-- 控制面板 -->
  <div class="control-panel">
    <div class="direction-pad">
      <!-- 十字方向键 -->
    </div>
    <div class="status-info">
      <div>Battery: 78%</div>
      <div>Position: Kitchen</div>
    </div>
  </div>
</div>
```

**样式重点**：
- 深色主题（机器人场景更实用）
- 高对比度按钮（机器人操作需要清晰视觉反馈）
- 触摸友好的按钮尺寸（最小 44×44px，iOS 标准）
- 振动/动画反馈

### 登录/鉴权

**本地网络场景**：通常不需要鉴权，Flask 后端仅监听 `127.0.0.1`。

**如果需要对外暴露**：使用 HTTP Basic Auth 或 Token：

```python
from functools import wraps

API_TOKEN = os.getenv("NAV_API_TOKEN", "changeme")

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if token != API_TOKEN:
            return {"error": "Unauthorized"}, 401
        return f(*args, **kwargs)
    return decorated

@app.route('/api/navigate')
@require_auth
def navigate(): ...
```

### 移动端适配

使用 Viewport meta 和 CSS Flexbox/Grid：

```html
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<style>
  .container { display: flex; flex-direction: column; height: 100dvh; }
  .video-wrapper { flex: 1; min-height: 0; }
  .control-panel { flex: 0 0 auto; padding: 16px; }
</style>
```

`100dvh`（dynamic viewport height）解决移动浏览器地址栏导致的 100vh 问题。

---

## 6. 部署方式

### 本地 Mac 对外暴露

**ngrok（推荐，免费额度够用）**：
```bash
# 安装
brew install ngrok

# 对 Flask 5000 端口创建隧道
ngrok http 5000

# 输出：Forwarding https://xxxx.ngrok.io -> http://127.0.0.1:5000
```

**Cloudflare Tunnel（免费，更稳定）**：
```bash
# 安装 cloudflared
brew install cloudflare/cloudflare/cloudflared

# 创建隧道
cloudflared tunnel --url http://localhost:5000
```

**注意事项**：
- Flask 后端需要同时支持 WebSocket（如果用 WebSocket 方案）和 MJPEG 流
- ngrok 免费版有连接数限制（每个 tunnel 1 个）
- Cloudflare Tunnel 不限连接数，更适合长时间运行

### GitHub Pages 静态托管 + Flask 后端

**GitHub Pages 只能托管纯静态文件**（HTML/CSS/JS），不能跑 Flask 后端。

**可行方案**：
1. **静态页面部署到 GitHub Pages**：HTML/JS/CSS 在 GitHub Pages
2. **Flask 后端部署到其他地方**：Railway/Render/Railway（见下）

前端代码通过环境变量配置后端 URL：
```javascript
const BASE_URL = window.location.hostname === 'your-github-pages domain' 
  ? 'https://your-railway-app.railway.app' 
  : 'http://127.0.0.1:5000';
```

### Flask 后端免费部署方案

| 平台 | 免费额度 | 冷启动 | WebSocket | 适合场景 |
|------|---------|--------|-----------|---------|
| **Render** | 750h/月，休眠后唤醒 | ~30s | 支持 | ⭐ 推荐，文档清晰 |
| **Railway** | $5/月额度，实际可跑1个小服务 | ~10s | 支持 | ⭐ 也不错 |
| **Fly.io** | 3 shared VMs免费 | ~10s+ | 支持 | 有时长限制 |
| **Cyclic** | 无限期免费 | 快 | 不支持 | 不适合 |
| **Deta** | 免费 | 快 | 不支持 | 不适合 |

**Railway 部署 Flask 最小示例**：
1. `railway init` → 选择 Python Flask
2. `railway up`
3. 设置环境变量 `FLASK_PORT=8080`
4. Railway 会自动检测 `requirements.txt` 并安装依赖

**注意事项**：
- 免费平台的休眠机制：Railway 休眠需要手动 wake 或使用 uptime monitor
- MJPEG 流需要持续连接，不适合有休眠的平台
- 如果需要 24/7 在线，建议购买最便宜的付费计划（~$5/月）

### 综合部署架构建议

**开发/测试阶段**：
```
Mac 本地
├── Flask (127.0.0.1:5000) -- 机器人控制 + MJPEG 流
└── OpenClaw Gateway -- 调度 + 对话
```

**生产对外暴露**：
```
用户浏览器
└── GitHub Pages (静态前端)
    └── 前端通过 Railway/Railway Flask API (HTTPS)
         └── 机器人所在 Mac 通过 ngrok/cloudflare tunnel 反向代理
```

---

## N. 综合评估

### 推荐的具身导航技术栈

| 层级 | 技术选型 | 理由 |
|------|---------|------|
| **Agent 调度** | OpenClaw（现有框架）| 已集成，支持 exec/Skill |
| **Agent ↔ 后端通信** | Python requests → Flask HTTP API | 最简单实现，无额外依赖 |
| **视频推流** | Flask MJPEG | 极简代码，浏览器原生支持，延迟 ~50-150ms |
| **控制指令** | Flask REST API (`/api/navigate`, `/api/command`) | 结构清晰，易于扩展 |
| **前端界面** | 单 HTML 文件（无框架）| 极轻量，移动端友好 |
| **对外暴露** | Cloudflare Tunnel（Mac 常驻） | 免费、稳定、不限连接数 |
| **长期部署** | Railway Flask 备用 | 付费$5/月，稳定 |

### 快速启动优先级

1. **第一阶段**：Flask MJPEG 流 + REST API（纯 Python，1-2 天）
2. **第二阶段**：OpenClaw Skill 编写 + exec 调用 Python 脚本
3. **第三阶段**：HTML 控制界面 + Cloudflare Tunnel
4. **第四阶段**：可选 Tool Plugin（TypeScript，需要额外开发）

### 风险点

- **MJPEG 带宽**：高分辨率下带宽占用较高（720p ~1-2Mbps），局域网足够，广域网需压缩
- **Flask 线程模型**：使用 `threaded=True`，注意全局状态线程安全
- **OpenClaw session context**：需要手动通过命令行参数传递，不支持自动上下文注入 exec

---

*调研人：OpenClaw Subagent | 日期：2026-05-23*