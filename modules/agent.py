"""
modules/agent.py — Robot Agent Control Module

Wraps Habitat-Sim agent state get/set operations.
Handles both real Habitat-Sim and mock simulator modes.
"""

from dataclasses import dataclass
from typing import Optional
import time
import numpy as np

try:
    import habitat_sim
except ImportError:
    habitat_sim = None  # type: ignore


@dataclass
class AgentState:
    """Current state of the robot agent."""
    position: tuple[float, float, float]  # x, y, z in meters
    rotation: tuple[float, float, float, float]  # quaternion (x, y, z, w)
    timestamp: int  # ms since epoch


SPAWN_POSITIONS = {
    "apartment_0": (0.0, 0.0, 0.0),
    "frl_apartment_0": (0.0, 0.0, 0.0),
    "room_0": (0.0, 0.0, 0.0),
}


def get_agent_state(sim, agent) -> AgentState:
    """Get current state of the agent from the simulator."""
    if sim is None or agent is None:
        return AgentState(
            position=(0.0, 0.0, 0.0),
            rotation=(0.0, 0.0, 0.0, 1.0),
            timestamp=int(time.time() * 1000),
        )

    # Real Habitat-Sim: agent.get_state()
    # Mock: sim.get_agent_state(agent.agent_id) or sim.get_agent_state()
    try:
        state = agent.get_state()
        pos = np.array(state.position)
        rot = np.array(state.rotation)
    except (TypeError, AttributeError):
        try:
            state = sim.get_agent_state()
            pos = np.array(state.position)
            rot = np.array(state.rotation)
        except Exception:
            pos = np.array([0.0, 0.0, 0.0])
            rot = np.array([0.0, 0.0, 0.0, 1.0])

    return AgentState(
        position=tuple(pos.tolist()),
        rotation=tuple(rot.tolist()),
        timestamp=int(time.time() * 1000),
    )


def set_agent_position(
    sim, agent,
    position: tuple[float, float, float],
    rotation: Optional[tuple[float, float, float, float]] = None,
) -> None:
    """Teleport agent to a specific position."""
    if sim is None or agent is None:
        return

    if rotation is None:
        rotation = (0.0, 0.0, 0.0, 1.0)

    pos_list = list(position)
    rot_list = list(rotation)

    if habitat_sim is not None:
        try:
            new_state = habitat_sim.AgentState()
            new_state.position = pos_list
            new_state.rotation = rot_list
            agent.set_state(new_state)
        except (TypeError, AttributeError):
            try:
                sim.pathfinder.set_agent_state(pos_list, rot_list)
            except Exception:
                pass
    else:
        # Mock simulator
        sim.set_agent_state(pos_list, rot_list)


def rotate_agent(sim, agent, angle_degrees: float) -> None:
    """Rotate agent by angle_degrees relative to current orientation."""
    if sim is None or agent is None:
        return

    try:
        current = agent.get_state()
    except Exception:
        current = sim.get_agent_state()

    current_pos = current.position
    current_rot = np.array(current.rotation)

    angle_rad = angle_degrees * np.pi / 180.0
    cos_a = np.cos(angle_rad / 2)
    sin_a = np.sin(angle_rad / 2)
    delta_rot = np.array([0.0, sin_a, 0.0, cos_a])
    new_rot = quaternion_multiply(current_rot, delta_rot)

    set_agent_position(
        sim, agent,
        position=tuple(current_pos.tolist()) if hasattr(current_pos, 'tolist') else tuple(current_pos),
        rotation=tuple(new_rot.tolist()),
    )


def quaternion_multiply(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Multiply two quaternions a * b."""
    ax, ay, az, aw = a[0], a[1], a[2], a[3]
    bx, by, bz, bw = b[0], b[1], b[2], b[3]
    return np.array([
        ax*bw + aw*bx + ay*bz - az*by,
        ay*bw + aw*by + az*bx - ax*bz,
        az*bw + aw*bz + ax*by - ay*bx,
        aw*bw - ax*bx - ay*by - az*bz,
    ])


def reset_agent(sim, agent, scene_name: str = "apartment_0") -> None:
    """Reset agent to spawn position."""
    spawn = SPAWN_POSITIONS.get(scene_name, (0.0, 0.0, 0.0))
    set_agent_position(sim, agent, spawn, rotation=(0.0, 0.0, 0.0, 1.0))