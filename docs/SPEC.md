# Embodied Navigation Agent — Technical Specification

> Version: 1.0 | Status: Complete

---

## 1. Overview & Scope

### 1.1 What This System Does

An embodied navigation agent that accepts natural language commands ("请到沙发旁边") and navigates a wheeled robot to the specified target location in a simulated home environment, purely using vision (no privileged information).

### 1.2 In Scope

- Habitat-Sim v0.3.3 simulation on M1 Pro (macOS)
- Replica `apartment_0` scene with semantic labels
- Sphere Agent (simplified wheeled robot)
- CLIP-based visual perception (CPU inference)
- Habitat SimpleShortestPathFinder for navigation
- Flask backend with MJPEG streaming
- OpenClaw as high-level language brain (documentation-style Skill)
- HTML5 frontend with real-time video + thought chain display
- 5 navigation targets: sofa, bed, dining_table, desk, exit

### 1.3 Out of Scope

- Real robot deployment (Phase 2+)
- Training / fine-tuning (Phase 1 is zero-training)
- Speech input (Whisper ASR) — future work
- YOLO-World upgrade — future work
- Multi-floor navigation — single floor only
- Continuous learning (LeRobot) — Phase 4

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    User (HTML Frontend)                             │
│   Input: "请到沙发旁边"          Real-time MJPEG Video Stream        │
└──────┬──────────────────────────┬────────────────────────────────┘
       │                          │
       │  Web Browser             │  <img src="http://127.0.0.1:5000/video_feed">
       │  HTTP POST /api/navigate │  multipart/x-mixed-replace (10-15 FPS)
       │  ←─────────────────────  │
       │  JSON Response           │
       ↓                          ↓
┌───────────────────────────────────────────────────────┐
│            Flask Backend (port 5000)                   │
│                                                       │
│  /api/navigate ──┐                                   │
│                   ↓                                   │
│  ┌────────────────────────────────────────────┐      │
│  │           Navigator Module                  │      │
│  │  1. CLIP scan (6 views) → best direction   │      │
│  │  2. Find target position (semantic map)   │      │
│  │  3. PathFollower → navigate to target     │      │
│  └──────────────┬───────────────────────────┘      │
│                 ↓                                     │
│  ┌────────────────────────────────────────────┐      │
│  │           Habitat-Sim Engine                │      │
│  │  Scene (Replica) + Agent + Sensors         │      │
│  │  RGBA sensor → frame buffer → MJPEG encode │      │
│  └────────────────────────────────────────────┘      │
│                                                       │
│  /video_feed ──── MJPEG encoded frames ────────────→ │
└───────────────────────────────────────────────────────┘
       ↑
       │ exec → python scripts/navigate.py
       │ requests.post("http://127.0.0.1:5000/api/navigate")
       │
┌──────────────────────────────────────────────────────┐
│              OpenClaw (Language Brain)                │
│  Intent parsing → Skill trigger → Execute command   │
│  Thought chain: Perception → Plan → Action → Result│
│  Auto-ask: "还需要什么？" after task completion      │
└──────────────────────────────────────────────────────┘
```

### Module Responsibilities

| Module | File | Responsibility |
|--------|------|----------------|
| Vision | `modules/vision.py` | CLIP 6-view scan, best direction selection |
| Navigator | `modules/navigator.py` | Path planning, target finding via semantic map |
| Agent | `modules/agent.py` | Robot state get/set, rotation, position control |
| Server | `server/app.py` | Flask API, MJPEG encoding, route dispatch |
| Skill | `skills/embodied-nav/scripts/navigate.py` | OpenClaw tool script, HTTP bridge |
| Frontend | `frontend/index.html` | HTML control panel, video display |

---

## 3. Directory Structure

```
embodied-nav/
├── docs/
│   ├── proposal.md          # Research methodology
│   └── SPEC.md              # This document
├── modules/
│   ├── __init__.py
│   ├── vision.py           # CLIP 6-view scanning
│   ├── navigator.py        # Habitat PathFollower
│   └── agent.py            # Robot state control
├── server/
│   ├── __init__.py
│   └── app.py              # Flask backend + MJPEG stream
├── skills/
│   └── embodied-nav/
│       ├── SKILL.md        # Skill description
│       └── scripts/
│           └── navigate.py # OpenClaw tool script
├── frontend/
│   └── index.html         # HTML control panel
├── scripts/
│   ├── setup_env.sh       # Environment setup
│   └── test_integration.py # End-to-end test
├── data/                   # Replica scenes (download separately)
│   └── README.md          # Download instructions
├── .planning/
│   ├── STATE.md
│   ├── decisions/
│   └── *.md
├── README.md
├── requirements.txt
└── .gitignore
```

---

## 4. API Specification

### GET /video_feed

Returns MJPEG multipart stream of the agent's first-person view.

```
GET /video_feed

Response:
  Content-Type: multipart/x-mixed-replace; boundary=frame
  Resolution: 640x480
  Quality: 85 (JPEG)
  Frame rate: 10-15 FPS
```

### POST /api/navigate

Send a navigation command. Blocks until navigation completes or fails.

```
POST /api/navigate
Content-Type: application/json

Request:
{
  "destination": "sofa" | "bed" | "dining_table" | "desk" | "exit",
  "user_input": "请到沙发旁边"  // optional, for logging
}

Response (success):
{
  "success": true,
  "arrived": true,
  "target": "sofa",
  "target_position": [3.2, 0.0, 1.5],
  "arrived_position": [3.1, 0.0, 1.6],
  "path_length": 4.2,
  "message": "已到达沙发旁边"
}

Response (error):
{
  "success": false,
  "arrived": false,
  "error": "error description",
  "code": "CLIP_NOT_FOUND" | "NAV_FAILED" | "SIM_NOT_READY" | "TIMEOUT" | "SCENE_LOAD_ERROR"
}
```

### POST /api/scan

Trigger a CLIP scan to find target direction (internal API).

```
POST /api/scan
Content-Type: application/json

Request:
{ "target": "sofa" }

Response:
{
  "success": true,
  "target": "sofa",
  "view_scores": [0.1, 0.92, 0.3, 0.05, 0.2, 0.1],  // 6 views
  "best_view": 1,
  "best_direction": "right",
  "confidence": 0.92,
  "agent_state": {
    "position": [0.0, 0.0, 0.0],
    "rotation": 1.57,
    "timestamp": 1747977600000
  },
  "inference_time_ms": 2400
}
```

### GET /api/status

Get current simulator and agent status.

```
GET /api/status

Response:
{
  "simulator": "ready" | "busy" | "error",
  "agent_position": [x, y, z],
  "current_target": "sofa" | null,
  "uptime_seconds": 3600
}
```

### POST /api/reset

Reset agent to spawn point.

```
POST /api/reset

Response:
{ "success": true }
```

---

## 5. Data Structures

### AgentState

```python
@dataclass
class AgentState:
    position: tuple[float, float, float]  # x, y, z in meters
    rotation: float                       # yaw in radians
    timestamp: int                         # ms since epoch
```

### NavigationResult

```python
@dataclass
class NavigationResult:
    success: bool
    arrived: bool
    target: str                            # "sofa" | "bed" | ...
    target_position: tuple[float, float, float]
    arrived_position: tuple[float, float, float]
    path_length: float                     # meters
    error: str | None
    code: str | None                        # error code if failed
```

### CLIPScanResult

```python
@dataclass
class CLIPScanResult:
    target: str
    view_scores: list[float]               # scores for 6 views
    best_view: int                        # index 0-5
    best_direction: str                   # "front" | "right" | "back" | "left" | "up" | "down"
    confidence: float
    inference_time_ms: float
```

---

## 6. Module Specifications

### modules/vision.py

```python
TARGET_LABELS: dict[str, str] = {
    "sofa": "a photo of a sofa in a living room",
    "bed": "a photo of a bed in a bedroom",
    "dining_table": "a photo of a dining table in a kitchen",
    "desk": "a photo of a desk in an office",
    "exit": "a photo of a front door or room exit",
}

def scan_for_target(
    sim: habitat_sim.Simulator,
    agent: habitat_sim.Agent,
    target_label: str,
    n_views: int = 6
) -> CLIPScanResult:
    """
    Rotate agent 360°, capture n_views images,
    run CLIP inference on each, return best direction.
    
    Args:
        sim: Habitat-Sim simulator instance
        agent: Habitat-Sim agent instance
        target_label: one of TARGET_LABELS keys
        n_views: number of views (default 6 = every 60°)
    
    Returns:
        CLIPScanResult with best direction and confidence
    """
```

**Implementation notes:**
- Use `sim.get_sensor_observations()` for RGB frame capture
- CLIP model: `openai/clip-vit-base-patch32` (CPU inference)
- Processor: `CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")`
- Batch process all 6 images in one forward pass (faster)
- Return direction as compass: front=0°, right=60°, back=120°, left=180°, up=240°, down=300°

### modules/navigator.py

```python
def navigate_to_target(
    sim: habitat_sim.Simulator,
    agent: habitat_sim.Agent,
    target_position: tuple[float, float, float],
    tolerance: float = 0.5
) -> NavigationResult:
    """
    Navigate from current position to target using Habitat PathFollower.
    
    Args:
        target_position: (x, y, z) world coordinates
        tolerance: arrival threshold in meters (default 0.5m)
    
    Returns:
        NavigationResult with success/failure info
    """
```

```python
def find_nearest_object(
    sim: habitat_sim.Simulator,
    object_class: str
) -> tuple[float, float, float] | None:
    """
    Use Replica semantic labels to find nearest object of given class.
    Returns position (x, y, z) or None if not found.
    """
```

### modules/agent.py

```python
def get_agent_state(sim, agent) -> AgentState:
    """Get current agent state from simulator."""

def set_agent_position(sim, agent, position: tuple[float, float, float]) -> None:
    """Teleport agent to position."""

def rotate_agent(sim, agent, angle_degrees: float) -> None:
    """Rotate agent by angle_degrees relative to current orientation."""
```

### server/app.py

```python
# Global state
sim: habitat_sim.Simulator | None = None
agent: habitat_sim.Agent | None = None
current_frame: np.ndarray | None = None
lock: threading.Lock = threading.Lock()

# Flask routes
@app.route("/video_feed")
def video_feed():
    """MJPEG multipart stream."""

@app.route("/api/navigate", methods=["POST"])
def api_navigate():
    """Main navigation endpoint."""

@app.route("/api/scan", methods=["POST"])
def api_scan():
    """CLIP scan endpoint."""

@app.route("/api/status", methods=["GET"])
def api_status():
    """Status endpoint."""

@app.route("/api/reset", methods=["POST"])
def api_reset():
    """Reset agent to spawn."""
```

**Startup sequence:**
1. Load Replica scene via `habitat_sim`
2. Create sphere agent at spawn point
3. Attach RGB sensor to agent
4. Start MJPEG background thread
5. Start Flask app on port 5000

---

## 7. OpenClaw Skill Interface

### skills/embodied-nav/SKILL.md

```yaml
---
name: embodied-nav
description: "当用户要求机器人移动、导航、走到房间里的某个地点时触发。支持：沙发(sofa)、床(bed)、餐桌(dining_table)、书桌(desk)、门口(exit)。Trigger: 导航, 带我到, 去, navigate, go to"
metadata:
  openclaw:
    emoji: "🤖"
    requires:
      bins: ["python3"]
    config:
      env:
        FLASK_BASE_URL:
          description: "Flask backend URL"
          default: "http://127.0.0.1:5000"
---

# Embodied Navigation Skill

## Overview
调用本地 Flask 后端，控制 Habitat-Sim 仿真器中的机器人导航到指定目标。

## Usage
OpenClaw 分析用户意图后，通过 exec 工具调用：
bash
python3 skills/embodied-nav/scripts/navigate.py --destination <target> --user-input "<original input>"
```

### skills/embodied-nav/scripts/navigate.py

```python
#!/usr/bin/env python3
import argparse, json, requests, sys

FLASK_BASE_URL = "http://127.0.0.1:5000"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", required=True)
    parser.add_argument("--user-input", default="")
    args = parser.parse_args()
    
    try:
        resp = requests.post(
            f"{FLASK_BASE_URL}/api/navigate",
            json={"destination": args.destination, "user_input": args.user_input},
            timeout=60
        )
        resp.raise_for_status()
        result = resp.json()
    except requests.exceptions.ConnectionError:
        print(json.dumps({
            "success": False,
            "code": "SIM_NOT_READY",
            "error": "仿真器未启动，请先运行: python server/app.py"
        }))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))
        sys.exit(1)
    
    print(json.dumps(result))

if __name__ == "__main__":
    main()
```

---

## 8. Frontend Specification

### Layout (3-column grid)

| Left (30%) | Center (40%) | Right (30%) |
|-----------|--------------|-------------|
| Text input | MJPEG video | Thought chain log |
| 5 quick buttons | `<img src="...">` | Auto-scrolling log |
| Status bar | | "还需要什么？" popup |

### Key Interactions

```javascript
// Send command to OpenClaw (via chat interface)
function sendCmd(destination) {
    const input = document.getElementById("cmdInput");
    const label = {sofa:"🛋️", bed:"🛏️", dining_table:"🍽️", desk:"💻", exit:"🚪"}[destination];
    input.value = `请到${label}旁边`;
    // OpenClaw handles the rest via Skill trigger
}

// Thought chain update (called from OpenClaw)
function appendLog(text) {
    const log = document.getElementById("logConsole");
    log.innerText += "\n" + text;
    log.scrollTop = log.scrollHeight;
}
```

### CSS Theme
- Background: `bg-slate-950`
- Accent: blue-400 / emerald-400 gradient text
- Font: system monospace for logs
- Animated pulse on "还需要什么？" popup

---

## 9. Acceptance Criteria

| ID | Criterion | Verification |
|----|-----------|---------------|
| A1 | Flask starts without errors | `python server/app.py` → no exception |
| A2 | MJPEG stream at /video_feed | Browser loads image |
| A3 | Navigate to sofa | Integration test passes |
| A4 | Navigate to bed | Integration test passes |
| A5 | Navigate to dining_table | Integration test passes |
| A6 | Navigate to desk | Integration test passes |
| A7 | Navigate to exit | Integration test passes |
| A8 | CLIP scan finds correct direction | Manual verification |
| A9 | HTML loads without errors | Browser console clean |
| A10 | MJPEG latency < 500ms | Estimated round-trip |
| A11 | Navigation error < 0.5m | Distance calculation |
| A12 | OpenClaw Skill triggers | Manual test with "去沙发" |
| A13 | GitHub repo created | `git remote -v` + README exists |
| A14 | Runs without sudo | No permission errors |

---

## 10. Error Codes

| Code | Meaning | User Message |
|------|---------|-------------|
| `SIM_NOT_READY` | Habitat not initialized | "仿真器未启动，请先运行 server/app.py" |
| `CLIP_NOT_FOUND` | No match above threshold | "抱歉，找不到这个物体" |
| `NAV_FAILED` | PathFinder cannot find path | "路径规划失败" |
| `TIMEOUT` | Navigation > 30s | "导航超时" |
| `SCENE_LOAD_ERROR` | Replica scene load failed | "场景加载失败" |

---

## 11. Performance Targets

| Metric | Target |
|--------|--------|
| CLIP inference per image | < 500ms (CPU) |
| 6-view scan total | < 3s |
| Navigation speed | ~1 m/s |
| MJPEG frame rate | 10-15 FPS |
| End-to-end latency | < 2s |
| Memory footprint | < 4GB |

---

## 12. Dependencies

```
# Environment: conda python=3.12
habitat-sim withbullet      # conda-forge / aihabitat
torch >= 2.0               # pip
transformers >= 4.0        # pip
pillow >= 10.0             # pip
flask >= 3.0               # pip
opencv-python >= 4.9       # pip
requests >= 2.31           # pip
gunicorn >= 21.0           # pip
```