"""
server/mock_simulator.py — Lightweight simulation fallback

Generates synthetic RGB images for rooms without needing Habitat-Sim or Replica data.
API-compatible with the Habitat-Sim simulator used in server/app.py.
"""

import math
import threading
import numpy as np
from PIL import Image, ImageDraw


class MockAgentState:
    """Mock AgentState compatible object."""
    def __init__(self, position, rotation):
        self.position = np.array(position)
        self.rotation = np.array(rotation)


class MockAgent:
    """Mock agent, API-compatible."""
    def __init__(self, agent_id: int = 0):
        self.agent_id = agent_id


class MockSimulator:
    """
    Mock simulator that generates synthetic room images.
    API-compatible subset of habitat_sim.Simulator.
    """

    def __init__(self, scene_name: str = "apartment_0"):
        self.scene_name = scene_name
        self.curr_scene_name = scene_name
        self._agent_state = {
            "position": [0.0, 0.0, 0.0],
            "rotation": [0.0, 0.0, 0.0, 1.0],
            "yaw": 0.0,
        }
        self._lock = threading.Lock()
        self._navigate_target: Optional[tuple] = None
        self._navigate_done = threading.Event()
        self._template = ROOM_TEMPLATES.get(scene_name, ROOM_TEMPLATES["apartment_0"])
        self._frame_count = 0

    def get_agent_state(self, agent_id: int = 0):
        """Return current agent state."""
        return MockAgentState(
            position=self._agent_state["position"],
            rotation=self._agent_state["rotation"],
        )

    def get_sensor_observations(self, agent_id: int = 0):
        """Return RGB observation (mock camera)."""
        rgb = self._render_view()
        return {"rgba_camera": rgb, "rgba": rgb}

    def geometric_plugin(self):
        """Compatibility shim — returns self for set_agent_state calls."""
        return self

    def set_agent_state(self, position, rotation):
        """Set agent position and rotation."""
        with self._lock:
            self._agent_state["position"] = list(position)
            self._agent_state["rotation"] = list(rotation)
            if len(rotation) >= 4:
                q = list(rotation)
                siny_cosp = 2 * (q[3]*q[1] + q[0]*q[2])
                cosy_cosp = 1 - 2*(q[1]**2 + q[2]**2)
                self._agent_state["yaw"] = math.atan2(siny_cosp, cosy_cosp)

    # Alias for navigator.py compatibility
    def set_agent_position(self, position, rotation=None):
        """Mock: just update agent state directly."""
        if rotation is None:
            rotation = [0.0, 0.0, 0.0, 1.0]
        self.set_agent_state(position, rotation)

    @property
    def pathfinder(self):
        """Mock pathfinder (always navigable)."""
        return self

    def is_navigable(self, point) -> bool:
        return True

    def find_path(self, path):
        """Stub — always finds path."""
        path.found = True

    def _render_view(self) -> np.ndarray:
        """Render a simple perspective room view."""
        tpl = self._template
        W, H = tpl["size"]
        agent_x = self._agent_state["position"][0]
        agent_z = self._agent_state["position"][2]
        agent_yaw = self._agent_state["yaw"]

        self._frame_count += 1

        img = Image.new("RGB", (W, H))
        draw = ImageDraw.Draw(img)

        # Sky gradient (upper half)
        for y in range(H // 2):
            t = y / (H // 2)
            r = int(30 + (60 - 30) * t)
            g = int(30 + (50 - 30) * t)
            b = int(50 + (80 - 50) * t)
            draw.line([(0, y), (W, y)], fill=(r, g, b))

        # Floor gradient (lower half)
        for y in range(H // 2, H):
            t = (y - H // 2) / (H // 2)
            r = int(80 - 20 * t)
            g = int(60 - 10 * t)
            b = int(40 - 5 * t)
            draw.line([(0, y), (W, y)], fill=(r, g, b))

        # Draw perspective grid on floor
        for gz in np.arange(-2, 10, 1.0):
            for gx in np.arange(-2, 10, 1.0):
                sx, sy = _world_to_screen(gx, gz, agent_x, agent_z, agent_yaw, W, H)
                if sx and 0 < sx < W and H//2 < sy < H:
                    draw.ellipse([sx-2, sy-2, sx+2, sy+2], fill=(50, 40, 30))

        # Draw objects in scene
        for obj in tpl["objects"]:
            wx, _, wz = obj["pos"]
            screen_pos = _world_to_screen(wx, wz, agent_x, agent_z, agent_yaw, W, H)

            if screen_pos:
                sx, sy = screen_pos
                depth = math.sqrt((wx - agent_x)**2 + (wz - agent_z)**2)
                size = max(20, min(100, int(3000 / max(depth, 1))))

                color = obj["color"]
                x0, y0 = sx - size//2, sy - size//3
                x1, y1 = sx + size//2, sy + size//3

                draw.rectangle([x0, y0, x1, y1], fill=color,
                               outline=(255, 255, 255), width=2)
                draw.text((sx - size//4, sy - size//6),
                          obj["label"], fill=(255, 255, 255))

        # Agent POV indicator
        draw.ellipse([W//2 - 4, H - 20, W//2 + 4, H - 12],
                     fill=(0, 200, 100))

        # HUD
        draw.rectangle([5, 5, 200, 45], fill=(0, 0, 0))
        draw.text((8, 8), f"APARTMENT_0", fill=(0, 200, 100))
        pos = self._agent_state["position"]
        draw.text((8, 22), f"x={pos[0]:.1f} z={pos[2]:.1f}", fill=(150, 150, 150))
        draw.text((8, 36), f"yaw={math.degrees(agent_yaw):.0f}deg", fill=(150, 150, 150))

        return np.array(img)


def _world_to_screen(wx, wz, agent_x, agent_z, agent_yaw, width, height, fov=60):
    """Convert world coords to screen coords based on agent pose."""
    rx = wx - agent_x
    rz = wz - agent_z

    cos_yaw = math.cos(-agent_yaw)
    sin_yaw = math.sin(-agent_yaw)
    dx = rx * cos_yaw - rz * sin_yaw
    dz = rx * sin_yaw + rz * cos_yaw

    if dz <= 0.1:
        return None

    f = width / (2 * math.tan(math.radians(fov / 2)))
    sx = width / 2 + (dx / dz) * f
    sy = height / 2 - (0.5 / dz) * f

    return int(sx), int(sy)


# Room templates
ROOM_TEMPLATES = {
    "apartment_0": {
        "size": (640, 480),
        "spawn": (0.0, 0.0, 0.0),
        "objects": [
            {"name": "sofa", "pos": (3.2, 0.0, 1.5), "color": (80, 100, 200), "label": "SOFA"},
            {"name": "bed", "pos": (0.5, 0.0, 4.8), "color": (150, 100, 80), "label": "BED"},
            {"name": "dining_table", "pos": (2.0, 0.0, 3.0), "color": (120, 80, 60), "label": "TABLE"},
            {"name": "desk", "pos": (1.0, 0.0, 1.0), "color": (100, 90, 70), "label": "DESK"},
            {"name": "exit", "pos": (4.5, 0.0, 4.5), "color": (60, 140, 60), "label": "EXIT"},
        ],
    }
}


def create_mock_simulator(scene_name: str = "apartment_0"):
    """Factory function — creates mock simulator."""
    sim = MockSimulator(scene_name)
    agent = MockAgent(0)
    return sim, agent