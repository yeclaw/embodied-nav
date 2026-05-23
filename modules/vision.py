"""
modules/vision.py — Visual Perception Module

Phase 1: Uses CLIP (CPU) for 360° visual scanning.
When torch/transformers not available, falls back to a rule-based mock scanner.
"""

from dataclasses import dataclass
from typing import Optional

# Target label text templates for CLIP
TARGET_LABELS: dict[str, str] = {
    "sofa": "a photo of a sofa in a living room",
    "bed": "a photo of a bed in a bedroom",
    "dining_table": "a photo of a dining table in a kitchen or dining area",
    "desk": "a photo of a desk in an office or study",
    "exit": "a photo of a front door or room exit",
}

VIEW_DIRECTIONS = ["front", "right", "back", "left"]


@dataclass
class CLIPScanResult:
    """Result of a 6-view visual scan."""
    target: str
    view_scores: list[float]
    best_view: int
    best_direction: str
    confidence: float
    inference_time_ms: float


class CLIPPerception:
    """
    CLIP-based visual perception.
    Falls back to MockPerception when torch is unavailable.
    """

    def __init__(self, model_name: str = "openai/clip-vit-base-patch32"):
        try:
            import torch
            from transformers import CLIPModel, CLIPProcessor

            self.device = "cpu"
            print(f"[CLIP] Loading model '{model_name}' on {self.device}...")
            self.model = CLIPModel.from_pretrained(model_name)
            self.processor = CLIPProcessor.from_pretrained(model_name)
            self.model.eval()
            print(f"[CLIP] Model loaded successfully.")
            self._mode = "clip"
        except Exception as e:
            print(f"[CLIP] torch/transformers not available ({e}). Using mock perception.")
            self._mode = "mock"

    @property
    def mode(self) -> str:
        return self._mode

    def batch_score_images(self, images, target_label: str) -> list[float]:
        """Score multiple images for target label."""
        if self._mode == "mock":
            # Mock: return random-ish scores biased toward front
            import random
            scores = [random.uniform(0.1, 0.4) for _ in images]
            scores[0] = max(scores[0], 0.6)  # Bias front view slightly
            return scores
        else:
            import torch
            text = [target_label]
            inputs = self.processor(
                text=text, images=images, return_tensors="pt", padding=True
            )
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            with torch.no_grad():
                outputs = self.model(**inputs)
            logits = outputs.logits_per_image
            probs = logits.softmax(dim=-1)
            return probs[:, 0].tolist()

    def score_image_for_target(self, image, target_label: str) -> float:
        scores = self.batch_score_images([image], target_label)
        return scores[0] if scores else 0.0


def _set_agent_state(sim, position, rotation):
    """Set agent state, works with both real and mock simulators."""
    pos_list = list(position)
    rot_list = list(rotation)
    try:
        import habitat_sim
        sim.geometric_plugin.set_agent_state(pos_list, rot_list)
    except Exception:
        sim.set_agent_state(pos_list, rot_list)

def scan_for_target(
    sim,
    agent,
    target_label: str,
    n_views: int = 4,
    clip_perception: Optional[CLIPPerception] = None,
) -> CLIPScanResult:
    """
    Rotate agent 360° and scan for target using CLIP (or mock scanner).

    Args:
        sim: Simulator instance
        agent: Agent instance
        target_label: one of TARGET_LABELS keys
        n_views: number of views (default 4 = every 90°)
        clip_perception: CLIPPerception instance (creates one if None)

    Returns:
        CLIPScanResult with best direction and confidence
    """
    import time

    if clip_perception is None:
        clip_perception = CLIPPerception()

    if target_label not in TARGET_LABELS:
        raise ValueError(
            f"Unknown target: {target_label}. Valid: {list(TARGET_LABELS.keys())}"
        )

    text_template = TARGET_LABELS[target_label]
    angle_step = 360.0 / n_views

    images = []
    initial_state = sim.get_agent_state(agent.agent_id)

    for i in range(n_views):
        obs = sim.get_sensor_observations(agent_id=agent.agent_id)
        rgba = obs.get("rgba_camera", obs.get("rgba", None))

        if rgba is not None:
            # Convert to PIL Image for CLIP
            from PIL import Image
            if rgba.shape[2] == 4:
                rgb = rgba[:, :, :3]
            else:
                rgb = rgba
            img = Image.fromarray(rgb)
            images.append(img)

        # Rotate agent for next view
        if i < n_views - 1:
            current = sim.get_agent_state(agent.agent_id)
            current_pos = current.position
            current_rot = current.rotation

            # Simple yaw rotation via quaternion
            import numpy as np
            try:
                import math
                half_angle = math.radians(angle_step) / 2
                sin_a = np.sin(half_angle)
                cos_a = np.cos(half_angle)
                # Rotate around Y axis
                delta_rot = np.array([0.0, sin_a, 0.0, cos_a])

                # Quaternion multiply: current * delta
                ax, ay, az, aw = current_rot[0], current_rot[1], current_rot[2], current_rot[3]
                bx, by, bz, bw = delta_rot[0], delta_rot[1], delta_rot[2], delta_rot[3]
                new_rot = np.array([
                    ax*bw + aw*bx + ay*bz - az*by,
                    ay*bw + aw*by + az*bx - ax*bz,
                    az*bw + aw*bz + ax*by - ay*bx,
                    aw*bw - ax*bx - ay*by - az*bz,
                ])

                _set_agent_state(
                    list(current_pos), list(new_rot)
                )
            except Exception:
                pass

    # Reset agent
    try:
        _set_agent_state(
            list(initial_state.position), list(initial_state.rotation)
        )
    except Exception:
        pass

    # CLIP inference
    t0 = time.time()
    if clip_perception._mode == "mock":
        scores = clip_perception.batch_score_images(images or [None] * n_views, text_template)
    else:
        scores = clip_perception.batch_score_images(images, text_template)
    inference_time = (time.time() - t0) * 1000

    # Find best view
    import numpy as np
    best_view = int(np.argmax(scores))
    best_direction = VIEW_DIRECTIONS[best_view] if best_view < len(VIEW_DIRECTIONS) else "front"
    confidence = float(scores[best_view]) if scores else 0.0

    return CLIPScanResult(
        target=target_label,
        view_scores=[float(s) for s in scores],
        best_view=best_view,
        best_direction=best_direction,
        confidence=confidence,
        inference_time_ms=inference_time,
    )