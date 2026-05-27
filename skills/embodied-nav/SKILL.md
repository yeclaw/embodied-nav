---
name: embodied-nav
description: "当用户要求机器人移动、导航、走到房间里的某个地点（沙发/床/餐桌/书桌/门口）时触发。Trigger: 导航, 带我到, 去, navigate, go to, 带我到, 我想出门, 去沙发, 去床边"
metadata:
  openclaw:
    emoji: "🤖"
    requires:
      bins: ["python3"]
    config:
      env:
        FLASK_BASE_URL:
          description: "Flask backend URL"
          default: "http://127.0.0.1:5001"
---

# Embodied Navigation Skill

## Overview

调用本地 Flask 后端（Habitat-Sim 仿真器），控制机器人导航到指定目标地点。

**支持的导航目标：**

| 目标 | 标签 | 示例指令 |
|------|------|---------|
| 沙发 | `sofa` | "请到沙发旁边"、"我累了，去沙发那边" |
| 床 | `bed` | "我去睡觉"、"带我到床边" |
| 餐桌 | `dining_table` | "去餐桌吃饭"、"导航到餐桌" |
| 书桌 | `desk` | "我要办公"、"去书桌那边" |
| 门口 | `exit` | "带我出去"、"我想出门" |

## Usage

OpenClaw 分析用户意图后，通过 `exec` 工具调用导航脚本：

```bash
python3 skills/embodied-nav/scripts/navigate.py --destination <target> --user-input "<original input>"
```

**示例调用：**

```bash
python3 skills/embodied-nav/scripts/navigate.py --destination sofa --user-input "请到沙发旁边"
```

## Flow

```
用户输入 → OpenClaw 意图解析 → Skill 触发
    → exec python navigate.py → Flask /api/navigate
    → Habitat-Sim 导航 → MJPEG 流推送到前端
    → OpenClaw 打印结果 + "还需要什么？"
```

## Prerequisites

1. **启动 Flask 后端**（先运行）：
   ```bash
   conda activate embodied-nav
   python server/app.py
   ```

2. **确保 Replica 场景数据已下载**：
   ```bash
   bash scripts/download_replica.sh
   ```

## Error Handling

| 错误码 | 含义 | 修复方式 |
|--------|------|---------|
| `SIM_NOT_READY` | 仿真器未启动 | 运行 `python server/app.py` |
| `CLIP_NOT_FOUND` | 视觉扫描失败 | 重试，或换个位置 |
| `NAV_FAILED` | 路径规划失败 | 检查障碍物 |
| `TIMEOUT` | 导航超时 | 手动检查仿真器状态 |

## Notes

- Skill 通过 HTTP 与 Flask 后端通信，不直接在仿真器进程中运行
- 导航目标通过 `--destination` 参数传递，不支持任意字符串
- 可同时支持中文和英文输入