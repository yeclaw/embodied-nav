"""
server/app.py — Flask Backend with MJPEG Streaming

Provides:
  GET  /video_feed          MJPEG multipart stream
  POST /api/navigate        Main navigation endpoint
  POST /api/scan            CLIP scan endpoint
  GET  /api/status          Simulator status
  POST /api/reset           Reset agent to spawn

Auto-detects environment:
  - If habitat-sim is installed + Replica data exists → use real simulator
  - Otherwise → use mock simulator (synthetic room images, works immediately)
"""

import os
import sys
import time
import json
import threading
import traceback
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from flask import Flask, Response, request

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

app = Flask(__name__)

# ── Global State ─────────────────────────────────────────────────────────────
sim: Optional[object] = None
agent: Optional[object] = None
clip_perception: Optional[object] = None
current_frame: Optional[np.ndarray] = None
frame_lock = threading.Lock()
start_time: float = time.time()
current_target: Optional[str] = None
USE_MOCK: bool = False

# ── Simulator Detection ────────────────────────────────────────────────────────
def try_init_real_simulator(scene_path: Optional[str] = None, data_path: Optional[str] = None):
    """Try to initialize Habitat-Sim. Returns (sim, agent) or None."""
    global USE_MOCK

    try:
        import habitat_sim
    except ImportError:
        return None, None

    if data_path is None:
        data_path = os.environ.get("HABITAT_DATA_PATH", str(PROJECT_ROOT / "data"))

    if scene_path is None:
        scene_candidates = [
            Path(data_path) / "Replica" / "apartment_0" / "habitat" / "mesh_semantic.ply",
            Path(data_path) / "apartment_0" / "habitat" / "mesh_semantic.ply",
            Path(data_path) / "apartment_0.glb",
        ]
        for candidate in scene_candidates:
            if candidate.exists():
                scene_path = str(candidate)
                break

    if scene_path is None or not Path(scene_path).exists():
        return None, None

    print(f"[Server] Loading real Habitat-Sim scene: {scene_path}")
    sim_cfg = habitat_sim.SimulatorConfiguration()
    sim_cfg.scene.id = scene_path
    sim_cfg.enable_physics = False

    agent_cfg = habitat_sim.AgentConfiguration()
    agent_cfg.height = 1.5
    agent_cfg.radius = 0.1

    sensor_cfg = habitat_sim.CameraSensorSpecification()
    sensor_cfg.sensor_type = habitat_sim.SensorType.COLOR
    sensor_cfg.resolution = [640, 480]
    sensor_cfg.position = [0.0, 1.5, 0.0]
    agent_cfg.sensor_specifications.append(sensor_cfg)

    sim = habitat_sim.Simulator(habitat_sim.Configuration(sim_cfg, [agent_cfg]))
    agent = sim.get_agent(0)
    USE_MOCK = False
    return sim, agent


def init_simulator(scene_path: Optional[str] = None, data_path: Optional[str] = None):
    """Initialize simulator (real or mock)."""
    global sim, agent, clip_perception, USE_MOCK

    # Try real simulator first
    sim, agent = try_init_real_simulator(scene_path, data_path)

    if sim is not None:
        print("[Server] ✅ Real Habitat-Sim simulator initialized.")

        # Try to init CLIP
        try:
            from modules.vision import CLIPPerception
            clip_perception = CLIPPerception()
            print("[Server] ✅ CLIP model loaded.")
        except Exception as e:
            print(f"[Server] ⚠️  CLIP init failed: {e}. Visual scan disabled.")
            clip_perception = None
        return

    # Fall back to mock simulator
    print("[Server] ⚠️  Habitat-Sim not available — using mock simulator.")
    print("[Server] 💡 For full simulation, run: bash scripts/setup_env.sh")
    USE_MOCK = True

    from server.mock_simulator import create_mock_simulator
    sim, agent = create_mock_simulator("apartment_0")
    clip_perception = None
    print("[Server] ✅ Mock simulator ready.")


# ── MJPEG Stream ───────────────────────────────────────────────────────────────
def generate_frames():
    """Generator yielding MJPEG frames from the simulator."""
    global current_frame

    while True:
        with frame_lock:
            frame = current_frame

        if frame is None:
            placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
            ret, buf = cv2.imencode('.jpg', placeholder, [cv2.IMWRITE_JPEG_QUALITY, 60])
            if ret:
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' +
                       buf.tobytes() + b'\r\n')
        else:
            ret, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ret:
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' +
                       buf.tobytes() + b'\r\n')

        time.sleep(0.07)  # ~14 FPS


@app.route('/video_feed')
def video_feed():
    """MJPEG multipart streaming endpoint."""
    return Response(
        generate_frames(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )


# ── Background Frame Capture ────────────────────────────────────────────────────
def frame_capture_loop():
    """Background thread: capture frames from simulator."""
    global current_frame

    while True:
        if sim is not None and agent is not None:
            try:
                obs = sim.get_sensor_observations(agent_id=agent.agent_id)
                rgba = obs.get("rgba_camera", obs.get("rgba", None))

                if rgba is not None:
                    if rgba.shape[2] == 4:
                        bgr = cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGR)
                    else:
                        bgr = rgba

                    with frame_lock:
                        current_frame = bgr
            except Exception:
                pass

        time.sleep(0.07)


# ── Navigation Logic (shared between real and mock) ────────────────────────────
def do_navigate(destination: str):
    """Execute navigation to destination. Returns NavigationResult."""
    from modules.navigator import navigate_by_destination
    return navigate_by_destination(sim, agent, destination)


def do_scan(target: str):
    """Execute CLIP scan. Returns CLIPScanResult or error dict."""
    from modules.vision import scan_for_target, CLIPScanResult
    from modules.agent import get_agent_state

    if clip_perception is None:
        return {"success": False, "code": "CLIP_NOT_FOUND",
                "error": "CLIP not available (mock simulator mode)"}

    scan_result = scan_for_target(
        sim, agent, target, n_views=4,
        clip_perception=clip_perception
    )
    state = get_agent_state(sim, agent)
    return {
        "success": True,
        "target": scan_result.target,
        "view_scores": scan_result.view_scores,
        "best_view": scan_result.best_view,
        "best_direction": scan_result.best_direction,
        "confidence": scan_result.confidence,
        "agent_state": {
            "position": list(state.position),
            "rotation": list(state.rotation),
            "timestamp": state.timestamp,
        },
        "inference_time_ms": scan_result.inference_time_ms,
    }


# ── API Routes ────────────────────────────────────────────────────────────────
@app.route('/api/navigate', methods=['POST'])
def api_navigate():
    """Main navigation endpoint."""
    global current_target

    req = request.get_json() or {}
    destination = req.get("destination", "")
    user_input = req.get("user_input", "")

    destinations = ["sofa", "bed", "dining_table", "desk", "exit", "front_door"]
    if destination not in destinations:
        return {
            "success": False,
            "code": "INVALID_DESTINATION",
            "error": f"Unknown destination: {destination}. Valid: {destinations}"
        }

    if sim is None or agent is None:
        return {
            "success": False,
            "code": "SIM_NOT_READY",
            "error": "仿真器未启动，请先运行: python server/app.py"
        }

    current_target = destination
    print(f"[Server] Navigate to: {destination} | input: '{user_input}'")

    try:
        result = do_navigate(destination)
        response = {
            "success": result.success,
            "arrived": result.arrived,
            "target": result.target,
            "target_position": list(result.target_position),
            "arrived_position": list(result.arrived_position),
            "path_length": result.path_length,
            "message": f"已到达{destination}旁边" if result.arrived else f"无法到达{destination}",
        }
        if result.error:
            response["error"] = result.error
            response["code"] = result.code

        current_target = None
        return response

    except Exception as e:
        traceback.print_exc()
        current_target = None
        return {"success": False, "code": "NAV_FAILED", "error": str(e)}


@app.route('/api/scan', methods=['POST'])
def api_scan():
    """CLIP scan endpoint."""
    req = request.get_json() or {}
    target = req.get("target", "")

    if sim is None or agent is None:
        return {"success": False, "code": "SIM_NOT_READY", "error": "仿真器未启动"}

    try:
        return do_scan(target)
    except Exception as e:
        traceback.print_exc()
        return {"success": False, "code": "CLIP_NOT_FOUND", "error": str(e)}


@app.route('/api/status', methods=['GET'])
def api_status():
    """Simulator and agent status."""
    global sim, agent, start_time, current_target, USE_MOCK

    from modules.agent import get_agent_state

    if sim is None or agent is None:
        return {
            "simulator": "error",
            "agent_position": [0, 0, 0],
            "current_target": None,
            "uptime_seconds": int(time.time() - start_time),
            "mode": "unknown",
        }

    try:
        state = get_agent_state(sim, agent)
        return {
            "simulator": "ready",
            "agent_position": list(state.position),
            "current_target": current_target,
            "uptime_seconds": int(time.time() - start_time),
            "mode": "mock" if USE_MOCK else "habitat-sim",
        }
    except Exception:
        return {
            "simulator": "busy",
            "agent_position": [0, 0, 0],
            "current_target": current_target,
            "uptime_seconds": int(time.time() - start_time),
            "mode": "mock" if USE_MOCK else "habitat-sim",
        }


@app.route('/api/reset', methods=['POST'])
def api_reset():
    """Reset agent to spawn position."""
    global sim, agent, current_target

    if sim is None or agent is None:
        return {"success": False, "code": "SIM_NOT_READY"}

    try:
        from modules.agent import reset_agent
        reset_agent(sim, agent, "apartment_0")
        current_target = None
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.route('/api/health', methods=['GET'])
def api_health():
    """Health check."""
    return {"status": "ok", "time": time.time()}


# ── Main ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Embodied Nav Flask Server")
    parser.add_argument("--scene", default=os.environ.get("HABITAT_SCENE_PATH", None))
    parser.add_argument("--data", default=os.environ.get("HABITAT_DATA_PATH", None))
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--force-mock", action="store_true",
                        help="Force mock simulator even if habitat-sim is available")
    args = parser.parse_args()

    if args.force_mock:
        os.environ["USE_MOCK"] = "1"

    # Initialize simulator
    init_simulator(scene_path=args.scene, data_path=args.data)

    # Start frame capture thread
    capture_thread = threading.Thread(target=frame_capture_loop, daemon=True)
    capture_thread.start()

    print(f"\n[Server] 🚀 Flask running on http://127.0.0.1:{args.port}")
    print(f"[Server] 📹 MJPEG stream: http://127.0.0.1:{args.port}/video_feed")
    print(f"[Server] 🔗 API: http://127.0.0.1:{args.port}/api/navigate")

    app.run(host="127.0.0.1", port=args.port, debug=False, threaded=True)