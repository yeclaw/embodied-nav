"""
modules/navigator.py — Navigation Control Module

Uses Habitat-Sim's SimpleShortestPathFinder for path planning.
Falls back to a simple direct navigation when habitat_sim is unavailable.
"""

import math
import numpy as np
from dataclasses import dataclass
from typing import Optional

try:
    import habitat_sim
except ImportError:
    habitat_sim = None  # type: ignore


@dataclass
class NavigationResult:
    """Result of a navigation action."""
    success: bool
    arrived: bool
    target: str
    target_position: tuple[float, float, float]
    arrived_position: tuple[float, float, float]
    path_length: float
    error: Optional[str]
    code: Optional[str]


# Phase 1 anchor points (predefined positions per scene)
ANCHOR_POINTS = {
    "apartment_0": {
        "sofa": (3.2, 0.0, 1.5),
        "bed": (0.5, 0.0, 4.8),
        "dining_table": (2.0, 0.0, 3.0),
        "desk": (1.0, 0.0, 1.0),
        "exit": (4.5, 0.0, 4.5),
        "front_door": (4.5, 0.0, 4.5),
    },
    "frl_apartment_0": {
        "sofa": (2.0, 0.0, 2.5),
        "bed": (5.0, 0.0, 1.0),
        "dining_table": (3.0, 0.0, 3.0),
        "desk": (1.0, 0.0, 5.0),
        "exit": (0.0, 0.0, 0.0),
        "front_door": (0.0, 0.0, 0.0),
    },
    "room_0": {
        "sofa": (2.0, 0.0, 2.0),
        "bed": (1.0, 0.0, 4.0),
        "dining_table": (3.0, 0.0, 3.0),
        "desk": (0.5, 0.0, 0.5),
        "exit": (5.0, 0.0, 5.0),
        "front_door": (5.0, 0.0, 5.0),
    },
}


def find_nearest_object(sim, object_class: str) -> Optional[tuple[float, float, float]]:
    """
    Find the nearest object of a given semantic class.

    Phase 1: Uses predefined anchor points (no semantic map parsing).
    """
    # Get scene name from simulator
    scene_name = "apartment_0"
    try:
        if sim is not None and hasattr(sim, "curr_scene_name"):
            scene_id = sim.curr_scene_name
            if scene_id:
                scene_name = scene_id.split("/")[-1].replace(".glb", "").replace(".ply", "")
    except Exception:
        pass

    anchors = ANCHOR_POINTS.get(scene_name, ANCHOR_POINTS["apartment_0"])

    if object_class in anchors:
        return anchors[object_class]

    # Normalize and try to match
    normalized = object_class.replace("-", "_").replace(" ", "_")
    for key, pos in anchors.items():
        if key.replace("_", "") == normalized.replace("_", ""):
            return pos

    return None


def _set_agent_state(sim, position, rotation):
    """Set agent state, works with both real and mock simulators."""
    pos_list = list(position)
    rot_list = list(rotation)
    if habitat_sim is not None:
        new_state = habitat_sim.AgentState()
        new_state.position = pos_list
        new_state.rotation = rot_list
        sim.geometric_plugin.set_agent_state(pos_list, rot_list)
    else:
        sim.set_agent_state(pos_list, rot_list)


def navigate_to_target(
    sim,
    agent,
    target_position: tuple[float, float, float],
    tolerance: float = 0.5,
    speed: float = 1.0,
    max_steps: int = 200,
) -> NavigationResult:
    """
    Navigate from current agent position to target.

    Falls back to simple direct-step navigation when habitat_sim is unavailable.
    """
    if sim is None or agent is None:
        return NavigationResult(
            success=False, arrived=False, target="unknown",
            target_position=target_position, arrived_position=(0, 0, 0),
            path_length=0, error="Simulator not initialized", code="SIM_NOT_READY",
        )

    # Get start state
    try:
        state = sim.get_agent_state(agent.agent_id)
        start_pos = np.array(state.position)
    except Exception:
        start_pos = np.array([0.0, 0.0, 0.0])

    target_pos = np.array(target_position)
    path_length = float(np.linalg.norm(target_pos - start_pos))

    # Check if we have real Habitat pathfinder
    has_real_pathfinder = (
        habitat_sim is not None
        and sim is not None
        and hasattr(sim, "pathfinder")
        and sim.pathfinder is not None
        and hasattr(sim.pathfinder, "is_navigable")
    )

    if has_real_pathfinder:
        # Use Habitat pathfinder
        try:
            path = habitat_sim.nav.Path()
            path.requested_start = start_pos
            path.requested_end = target_pos
            sim.pathfinder.find_path(path)
            path_found = path.found and len(path.points) >= 2
        except Exception:
            path_found = False

        if path_found:
            return _navigate_along_path(
                sim, agent, path.points, target_pos, tolerance, speed, max_steps, path_length
            )

    # Fallback: simple direct navigation (mock simulator or path failed)
    return _navigate_direct(
        sim, agent, start_pos, target_pos, tolerance, path_length
    )


def _navigate_along_path(
    sim, agent, path_points, target_pos, tolerance, speed, max_steps, path_length
):
    """Navigate along a precomputed path."""
    arrived = False
    arrived_position = tuple(path_points[0].tolist())

    for step in range(max_steps):
        current = sim.get_agent_state(agent.agent_id)
        current_pos = np.array(current.position)

        min_dist = float("inf")
        next_point = None
        for pt in path_points[1:]:
            dist = float(np.linalg.norm(current_pos - pt))
            if dist < min_dist:
                min_dist = dist
                next_point = pt

        if next_point is None or min_dist < tolerance:
            arrived = True
            arrived_position = tuple(current_pos.tolist())
            break

        direction = next_point - current_pos
        dist_to_next = float(np.linalg.norm(direction))
        direction = direction / dist_to_next * min(speed * 0.1, dist_to_next)
        new_pos = current_pos + direction

        try:
            if sim.pathfinder.is_navigable(new_pos):
                new_state = habitat_sim.AgentState()
                new_state.position = new_pos.tolist()
                new_state.rotation = current.rotation
                _set_agent_state(sim, new_state.position, new_state.rotation)
                arrived_position = tuple(new_pos.tolist())
        except Exception:
            break

    final_pos = np.array(arrived_position)
    dist_to_target = float(np.linalg.norm(final_pos - target_pos))

    return NavigationResult(
        success=True,
        arrived=dist_to_target < tolerance or arrived,
        target="unknown",
        target_position=tuple(target_pos.tolist()),
        arrived_position=arrived_position,
        path_length=path_length,
        error=None,
        code=None,
    )


def _navigate_direct(sim, agent, start_pos, target_pos, tolerance, path_length) -> NavigationResult:
    """
    Simple direct navigation for mock simulator.
    Just moves agent directly toward target position.
    """
    arrived_position = tuple(start_pos.tolist())
    arrived = False

    for step in range(200):
        current = sim.get_agent_state(agent.agent_id)
        current_pos = np.array(current.position)

        direction = target_pos - current_pos
        dist = float(np.linalg.norm(direction))

        if dist < tolerance:
            arrived = True
            arrived_position = tuple(current_pos.tolist())
            break

        if dist < 0.01:
            break

        # Move toward target (0.3m per step)
        step_size = min(0.3, dist)
        move_vec = (direction / dist) * step_size
        new_pos = current_pos + move_vec

        try:
            _set_agent_state(
                sim,
                new_pos.tolist(),
                current.rotation.tolist() if hasattr(current.rotation, 'tolist') else list(current.rotation)
            )
            arrived_position = tuple(new_pos.tolist())
        except Exception:
            pass

        import time
        time.sleep(0.01)

    final_dist = float(np.linalg.norm(np.array(arrived_position) - target_pos))
    return NavigationResult(
        success=True,
        arrived=final_dist < tolerance,
        target="unknown",
        target_position=tuple(target_pos.tolist()),
        arrived_position=arrived_position,
        path_length=path_length,
        error=None,
        code=None,
    )


def navigate_by_destination(
    sim, agent, destination: str, tolerance: float = 0.5
) -> NavigationResult:
    """
    High-level navigation: resolve destination → position → navigate.
    """
    target_pos = find_nearest_object(sim, destination)
    if target_pos is None:
        return NavigationResult(
            success=False, arrived=False, target=destination,
            target_position=(0, 0, 0), arrived_position=(0, 0, 0),
            path_length=0,
            error=f"Could not find position for target: {destination}",
            code="CLIP_NOT_FOUND",
        )

    result = navigate_to_target(sim, agent, target_pos, tolerance=tolerance)
    result.target = destination
    return result