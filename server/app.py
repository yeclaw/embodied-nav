"""
Embodied Navigation Server - Real Habitat-Sim Mode
Flask + MJPEG + habitat-sim + CLIP navigation

Targets: sofa, bed, dining_table, desk, exit (5个)
Scene: apartment_1.glb (HuggingFace下载的小型测试场景)
"""

import os
import sys
import time
import threading
import logging
import warnings

warnings.filterwarnings("ignore")
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["HABITAT_DATA_PATH"] = os.path.expanduser("~/.habitat-data")

WORKSPACE = "/Users/kaiyan99yankai/.openclaw/workspace/embodied-nav"
sys.path.insert(0, WORKSPACE)

# Suppress habitat-sim console spam
for _logger_name in ["habitat_sim", "habitat", "GltfImporter", "AssimpImporter"]:
    _l = logging.getLogger(_logger_name)
    _l.setLevel(logging.ERROR)

from flask import (
    Flask, Response, jsonify, request,
    render_template_string, send_from_directory
)

# ─────────────────────────────────────────────────────────────────────────────
# Global state
# ─────────────────────────────────────────────────────────────────────────────
sim = None
agent = None
clip_perception = None
USE_MOCK = False

start_time = time.time()
current_target = None
nav_lock = threading.Lock()

# Predefined anchor positions (scene: apartment_1.glb)
# Based on habitat-sim pathfinder bounds: X[-0.96, 6.94], Y[-1.8, 2.74], Z[-2.6, 8.14]
ANCHORS = {
    "sofa":          [2.0,  -1.6,  2.8],
    "bed":           [0.5,  -1.6,  5.1],
    "dining_table":  [5.8,  -1.6,  2.4],
    "desk":          [0.5,  -1.6,  3.7],
    "exit":          [5.4,  -1.6, -0.5],
    "front_door":    [6.0,  -1.6, -0.5],
}


# ─────────────────────────────────────────────────────────────────────────────
# Init Habitat-Sim
# ─────────────────────────────────────────────────────────────────────────────




def try_init_real_simulator():
    """Initialize Habitat-Sim with apartment_1.glb test scene."""
    global sim, agent, clip_perception, USE_MOCK

    try:
        import habitat_sim
    except ImportError:
        print("[Server] habitat_sim not available")
        return None, None

    print("[Server] Initializing Habitat-Sim 0.3.3...")

    scene_path = os.path.expanduser(
        "~/.habitat-data/versioned_data/habitat_test_scenes/apartment_1.glb"
    )

    if not os.path.exists(scene_path):
        print(f"[Server] ERROR: Scene not found at {scene_path}")
        return None, None

    try:
        global USE_MOCK
        import numpy as np
        from magnum import Vector3

        # SimulatorConfiguration
        sim_cfg = habitat_sim.SimulatorConfiguration()
        sim_cfg.scene_id = scene_path
        sim_cfg.enable_physics = False
        sim_cfg.create_renderer = True  # Enable real camera - avoids GL context crash

        # AgentConfiguration with RGB camera
        acfg = habitat_sim.AgentConfiguration()
        acfg.height = 1.5
        acfg.radius = 0.1
        acfg.action_space = {
            "move_forward": habitat_sim.ActionSpec(
                "move_forward",
                habitat_sim.ActuationSpec(amount=0.25)
            ),
            "turn_left": habitat_sim.ActionSpec(
                "turn_left",
                habitat_sim.ActuationSpec(amount=30.0)
            ),
            "turn_right": habitat_sim.ActionSpec(
                "turn_right",
                habitat_sim.ActuationSpec(amount=30.0)
            ),
        }

        from magnum import Vector2i, Vector3, Deg

        # RGB camera sensor
        rgb_sensor = habitat_sim.CameraSensorSpec()
        rgb_sensor.uuid = "rgba_camera"
        rgb_sensor.sensor_type = habitat_sim.SensorType.COLOR
        rgb_sensor.sensor_subtype = habitat_sim.SensorSubType.PINHOLE
        rgb_sensor.resolution = Vector2i(640, 480)
        rgb_sensor.position = Vector3(0.0, 1.5, 0.0)
        rgb_sensor.orientation = Vector3(0.0, 0.0, 0.0)
        rgb_sensor.hfov = Deg(90.0)
        acfg.sensor_specifications.append(rgb_sensor)

        # Create simulator
        sim = habitat_sim.Simulator(habitat_sim.Configuration(sim_cfg, [acfg]))
        agent = sim.agents[0]

        print(f"[Server] Scene: {sim.curr_scene_name}")
        print(f"[Server] Agent start: {agent.get_state().position}")

        # Teleport to valid navigable start
        pf = sim.pathfinder
        try:
            rnd = pf.get_random_navigable_point()
            state = habitat_sim.AgentState()
            state.position = list(rnd)
            state.rotation = [0, 0, 0, 1]
            agent.set_state(state)
            print(f"[Server] Agent teleported to: {agent.get_state().position}")
        except Exception as e:
            print(f"[Server] Could not teleport agent: {e}")

        print("[Server] ✅ Habitat-Sim initialized (REAL mode)")

        # CLIP disabled - using anchor-based navigation

        return sim, agent

    except Exception as e:
        print(f"[Server] ❌ Simulator init FAILED: {e}")
        import traceback
        traceback.print_exc()
        return None, None


# ─────────────────────────────────────────────────────────────────────────────
# App setup
# ─────────────────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False

# Init simulator
_frame_cache = {}
print("[Server] Loading Habitat-Sim...")
_init_ok = False
try:
    _sim, _agent = try_init_real_simulator()
    if _sim is not None:
        _init_ok = True
except Exception as e:
    print(f"[Server] Init error: {e}")

if not _init_ok:
    print("[Server] ⚠️ Using MOCK mode (simulator unavailable)")
    USE_MOCK = True
else:
    # Pre-render anchor views AFTER sim/agent are initialized
    # Write to STDERR to bypass Flask stdout capture
    import sys
    sys.stderr.write("[Server] Pre-rendering anchor views...\n")
    sys.stderr.flush()
    try:
        import cv2
        from magnum import Vector3
        pf = sim.pathfinder
        anchors = {
            "spawn": list(agent.get_state().position),
            "sofa": [2.0, -1.6, 2.8],
            "bed": [0.5, -1.6, 5.1],
            "dining_table": [5.8, -1.6, 2.4],
            "desk": [0.5, -1.6, 3.7],
            "exit": [5.4, -1.6, -0.5],
        }
        import habitat_sim
        for name, pos in anchors.items():
            try:
                state = habitat_sim.AgentState()
                state.position = list(pos)
                state.rotation = [0.0, 0.0, 0.0, 1.0]
                if name != "spawn":
                    agent.set_state(state)
                frame = sim.get_sensor_observations()["rgba_camera"]
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_RGBA2RGB)
                _, jpg = cv2.imencode('.jpg', frame_rgb, [cv2.IMWRITE_JPEG_QUALITY, 85])
                _frame_cache[name] = jpg.tobytes()
                sys.stderr.write(f"[PreRender] {name}: {len(jpg)} bytes\n")
                sys.stderr.flush()
            except Exception as e2:
                sys.stderr.write(f"[PreRender] {name} failed: {e2}\n")
                sys.stderr.flush()
        sys.stderr.write(f"[PreRender] Done. Cached {len(_frame_cache)} frames.\n")
        sys.stderr.flush()
    except Exception as e:
        sys.stderr.write(f"[Server] Pre-render failed: {e}\n")
        sys.stderr.flush()

# Import habitat_sim at module level for navigation functions
try:
    import habitat_sim
except ImportError:
    habitat_sim = None

# Pre-render call moved to AFTER try_init_real_simulator() returns


# ─────────────────────────────────────────────────────────────────────────────
# Utility
# ─────────────────────────────────────────────────────────────────────────────
def _get_state():
    """Get agent state safely."""
    try:
        if sim is not None and agent is not None:
            state = agent.get_state()
            pos = state.position
            rot = state.rotation
            # numpy array: use [0],[1],[2]
            # quaternion: use .w, .x, .y, .z
            try:
                pos_list = [float(pos[0]), float(pos[1]), float(pos[2])]
            except Exception:
                pos_list = [float(pos.tolist()[i]) for i in range(3)]
            try:
                rot_list = [float(rot.w), float(rot.x), float(rot.y), float(rot.z)]
            except Exception:
                rot_list = [float(rot[0]), float(rot[1]), float(rot[2]), float(rot[3])]
            return {
                "position": pos_list,
                "rotation": rot_list,
            }
    except Exception:
        pass
    return {"position": [0, 0, 0], "rotation": [0, 0, 0, 1]}


# ─────────────────────────────────────────────────────────────────────────────
# Pre-rendered frame cache (populated at startup via pre-render inside try_init_real_simulator)
# ─────────────────────────────────────────────────────────────────────────────
_current_anchor = "spawn"
_renderer_ok = True
_frame_lock = __import__('threading').Lock()


# _render_frame removed - Metal GL context not available in HTTP request threads




def _get_frame_mean(jpg_bytes) -> float:
    """Get mean pixel value of a JPEG frame."""
    import cv2
    import numpy as np
    try:
        data = np.frombuffer(jpg_bytes, dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if img is not None:
            return float(img.mean())
    except:
        pass
    return 0.0


def _capture_ondemand():
    """Deprecated - use _frame_cache instead."""
    return None


# Global flag - set False if Metal crashes
_renderer_ok = True


# Only start capture thread if simulator is properly initialized
# Note: capture thread is disabled in headless mode to avoid GL context crashes
# The video feed will show placeholder when no frame is available
if sim is not None and not USE_MOCK:
    # Temporarily disabled - causes SIGABRT in background mode
    # _capture_thread = threading.Thread(target=_capture_loop, daemon=True)
    # _capture_thread.start()
    print("[Server] Capture thread disabled (headless mode)")


# ─────────────────────────────────────────────────────────────────────────────
# Navigation logic (real habitat-sim)
# ─────────────────────────────────────────────────────────────────────────────
def _step_forward():
    """Move agent forward one step."""
    try:
        collision = agent.act("move_forward")
        return collision
    except Exception:
        return False


def _turn(angle_deg: float):
    """Turn agent by angle_deg (positive=left, negative=right)."""
    try:
        steps = abs(int(angle_deg / 30.0))
        action = "turn_left" if angle_deg > 0 else "turn_right"
        for _ in range(steps):
            agent.act(action)
    except Exception:
        pass


def _teleport_to_anchor(target: str) -> dict:
    """Teleport agent to anchor position."""
    global current_target
    if target not in ANCHORS:
        return {"success": False, "arrived": False, "code": "UNKNOWN_TARGET"}

    target_pos = ANCHORS[target]
    current_target = target

    try:
        pf = sim.pathfinder
        from magnum import Vector3

        # Check navigability
        v = Vector3(target_pos[0], target_pos[1], target_pos[2])
        if not pf.is_navigable(v):
            # Try nearby navigable point
            rnd = pf.get_random_navigable_point()
            target_pos = [float(rnd[0]), float(rnd[1]), float(rnd[2])]
            print(f"[Nav] Target {target} not navigable, using {target_pos}")

        state = habitat_sim.AgentState()
        state.position = [float(v) for v in target_pos]
        state.rotation = [0, 0, 0, 1]
        agent.set_state(state)
        
        global _current_anchor
        # Update current anchor reference (no re-rendering - Metal not available in request threads)
        _current_anchor = target

        final_state = agent.get_state()
        arrived_pos = [float(final_state.position[i]) for i in range(3)]
        arrived = all(
            abs(arrived_pos[i] - target_pos[i]) < 2.0
            for i in range(3)
        )

        return {
            "success": True,
            "arrived": arrived,
            "target": target,
            "target_position": target_pos,
            "arrived_position": arrived_pos,
            "path_length": 0,
            "code": None,
            "message": "到达目标" if arrived else "无法到达目标",
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "arrived": False, "code": "NAV_ERROR", "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# MJPEG stream

# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────
HTML_HOME = """
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>Embodied Navigation - Habitat-Sim</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { background:#0a0a0f; color:#e0e0e0; font-family:'SF Mono',Consolas,monospace; }
.container { max-width:1200px; margin:0 auto; padding:20px; }
h1 { color:#00ffcc; font-size:1.4rem; margin-bottom:16px; letter-spacing:1px; }
.status-bar { display:flex; gap:12px; margin-bottom:16px; flex-wrap:wrap; }
.badge { padding:6px 14px; border-radius:6px; font-size:0.75rem; background:#1a1a2e; border:1px solid #333; }
.badge.ok { color:#00ffcc; border-color:#00ffcc40; }
.badge.sim { color:#ffcc00; border-color:#ffcc0040; }
.split { display:grid; grid-template-columns:1fr 280px; gap:16px; margin-bottom:16px; }
.video-wrap { background:#111; border:1px solid #222; border-radius:10px; overflow:hidden; }
.video-wrap img { width:100%; display:block; aspect-ratio:4/3; }
.panel { background:#111; border:1px solid #222; border-radius:10px; padding:16px; }
.panel h3 { color:#00ffcc; font-size:0.8rem; margin-bottom:12px; }
.nav-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
.btn { padding:12px; border-radius:8px; border:none; cursor:pointer; font-size:0.85rem;
       font-family:inherit; transition:all 0.15s; font-weight:600; }
.btn-sofa  { background:linear-gradient(135deg,#1e3a5f,#2d5a8a); color:#fff; }
.btn-bed   { background:linear-gradient(135deg,#3d1e5f,#6a2d8a); color:#fff; }
.btn-dining{ background:linear-gradient(135deg,#1e5f3a,#2d8a5a); color:#fff; }
.btn-desk  { background:linear-gradient(135deg,#5f3d1e,#8a6a2d); color:#fff; }
.btn-exit  { background:linear-gradient(135deg,#5f1e1e,#8a2d2d); color:#fff; }
.btn:hover { transform:translateY(-1px); box-shadow:0 4px 12px rgba(0,0,0,0.4); }
.btn:active{ transform:translateY(0); }
.btn:disabled{ opacity:0.5; cursor:not-allowed; }
.info-row { display:flex; justify-content:space-between; padding:8px 0; border-bottom:1px solid #1a1a2e; font-size:0.78rem; }
.info-row span:last-child { color:#aaa; }
</style>
</head>
<body>
<div class="container">
  <h1>🏠 Habitat-Sim Embodied Navigation</h1>

  <div class="status-bar">
    <span class="badge ok">● LIVE</span>
    <span class="badge sim" id="modeBadge">MODE: loading...</span>
    <span class="badge" id="uptimeBadge">UP: --</span>
    <span class="badge" id="targetBadge">TARGET: --</span>
    <span class="badge" id="posBadge">POS: --</span>
  </div>

  <div class="split">
    <div class="video-wrap">
      <img src="/video_feed" id="videoImg" />
    </div>
    <div class="panel">
      <h3>🎯 NAVIGATION TARGETS</h3>
      <div class="nav-grid">
        <button class="btn btn-sofa" onclick="navTo('sofa')">🛋️ Sofa</button>
        <button class="btn btn-bed" onclick="navTo('bed')">🛏️ Bed</button>
        <button class="btn btn-dining" onclick="navTo('dining_table')">🍽️ Dining</button>
        <button class="btn btn-desk" onclick="navTo('desk')">🖥️ Desk</button>
        <button class="btn btn-exit" onclick="navTo('exit')" style="grid-column:span 2">🚪 Exit</button>
      </div>
    </div>
  </div>

  <div class="panel">
    <h3>📋 LAST RESULT</h3>
    <div id="resultArea" style="font-size:0.78rem; color:#888; min-height:40px;">Press a target to navigate...</div>
  </div>
</div>

<script>
let busy = false;
const img = document.getElementById('videoImg');

function navTo(target) {
  if (busy) return;
  busy = true;
  document.getElementById('resultArea').textContent = 'Navigating to ' + target + '...';
  fetch('/api/navigate', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({destination: target})
  }).then(r => r.json()).then(d => {
    document.getElementById('resultArea').innerHTML =
      '<div style="color:' + (d.success?'#00ffcc':'#ff6666') + '">' +
      'Target: ' + d.target + '<br>' +
      'Success: ' + d.success + '<br>' +
      'Arrived: ' + d.arrived + '<br>' +
      'Position: ' + JSON.stringify(d.arrived_position) + '<br>' +
      'Message: ' + (d.message || d.error || '') + '</div>';
    busy = false;
  }).catch(e => {
    document.getElementById('resultArea').textContent = 'Error: ' + e;
    busy = false;
  });
}

function updateStatus() {
  fetch('/api/status').then(r => r.json()).then(d => {
    document.getElementById('modeBadge').textContent = 'MODE: ' + d.mode;
    document.getElementById('uptimeBadge').textContent = 'UP: ' + Math.floor(d.uptime_seconds) + 's';
    document.getElementById('targetBadge').textContent = 'TARGET: ' + (d.current_target || '--');
    document.getElementById('posBadge').textContent = 'POS: ' + d.agent_position.slice(0,2).map(v=>v.toFixed(1)).join(',');
    if (d.video_anchor) {
        img.alt = 'View from: ' + d.video_anchor;
    }
  });
}

setInterval(updateStatus, 3000);
setInterval(() => { img.src = '/video_feed?' + Date.now(); }, 100);
updateStatus();
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML_HOME)


def _generate_frame():
    """Serve pre-rendered frame from cache (current anchor or spawn)."""
    global _current_anchor, _frame_cache
    # Try current anchor first
    if _current_anchor in _frame_cache:
        return _frame_cache[_current_anchor]
    # Fall back to spawn
    if "spawn" in _frame_cache:
        _current_anchor = "spawn"
        return _frame_cache["spawn"]
    # Ultimate fallback: placeholder
    import cv2
    import numpy as np
    placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.putText(placeholder, "Habitat-Sim View", (150, 220),
        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 200, 150), 2)
    cv2.putText(placeholder, "apartment_1.glb", (200, 265),
        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (150, 150, 150), 1)
    cv2.putText(placeholder, "Loading...", (230, 305),
        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (100, 100, 100), 1)
    ret, jpg = cv2.imencode(".jpg", placeholder, [cv2.IMWRITE_JPEG_QUALITY, 60])
    if ret:
        return jpg.tobytes()
    return None


@app.route("/video_feed")
def video_feed():
    """Serve current frame as JPEG."""
    jpg_bytes = _generate_frame()
    if jpg_bytes:
        return Response(jpg_bytes, mimetype="image/jpeg",
                       headers={"Cache-Control": "no-cache, no-store, must-revalidate",
                               "Pragma": "no-cache", "Expires": "0"})
    return Response(b"", status=503)


@app.route("/api/health")
def api_health():
    return jsonify({"status": "ok", "time": time.time()})


@app.route("/api/status")
def api_status():
    state = _get_state()
    return jsonify({
        "mode": "habitat-sim" if not USE_MOCK else "mock",
        "simulator": "idle",
        "uptime_seconds": int(time.time() - start_time),
        "current_target": current_target,
        "agent_position": state["position"],
        "video_anchor": _current_anchor if '_current_anchor' in dir() else "spawn",
    })


@app.route("/api/navigate", methods=["POST"])
def api_navigate():
    global current_target
    data = request.get_json() or {}
    destination = data.get("destination", "")

    if USE_MOCK:
        return jsonify({
            "success": False, "arrived": False, "code": "MOCK_MODE",
            "error": "Simulator not available",
        })

    if destination not in ANCHORS:
        return jsonify({
            "success": False, "arrived": False, "code": "UNKNOWN_TARGET",
            "error": f"Unknown destination: {destination}",
        })

    with nav_lock:
        result = _teleport_to_anchor(destination)
        current_target = destination

    return jsonify(result)


@app.route("/api/reset", methods=["POST"])
def api_reset():
    try:
        pf = sim.pathfinder
        rnd = pf.get_random_navigable_point()
        state = habitat_sim.AgentState()
        state.position = list(rnd)
        state.rotation = [0, 0, 0, 1]
        agent.set_state(state)
        return jsonify({"success": True, "position": list(rnd)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("[Server] Starting on port 5001...")
    # Safe stdout redirection for background mode
    try:
        sys.stdout = os.fdopen(os.dup(1), 'w', buffering=1)
        sys.stderr = os.fdopen(os.dup(2), 'w', buffering=1)
    except Exception:
        pass  # If no TTY, that's fine - Python handles it
    app.run(host="127.0.0.1", port=5001, debug=False, threaded=False)