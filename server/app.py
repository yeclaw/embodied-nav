#!/usr/bin/env python3
"""
Embodied Navigation Server - Stanford COW (CLIP on Wheels) Algorithm
Flask + Multi-threaded Queue Synchronization + habitat-sim + CLIP FBE/EXPLOIT

This server implements:
1. Main-Thread Simulator Runner: Solves macOS Metal/OpenGL context crashes
   by confining all Habitat-Sim calls strictly to the main thread.
2. Stanford COW Core State Machine:
   - SPIN: 360° initialization scan (12 steps of 30°), updating voxel map with CLIP.
   - EXPLORE: Frontier-Based Exploration (FBE) over FREE voxels using NetworkX A*.
   - EXPLOIT: Region of Interest (ROI) lock when target is spotted with high confidence.
3. Proportional Heading Controller: Proportional heading control using local coordinates.
4. Blocking `/api/navigate` API: Blocks request thread until navigation completes.
"""

import os
import sys
import time
import math
import queue
import logging
import warnings
import threading
import numpy as np
from PIL import Image
import cv2
import networkx as nx

# Suppress console spams
warnings.filterwarnings("ignore")
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["HABITAT_DATA_PATH"] = os.path.expanduser("~/.habitat-data")

for _logger_name in ["habitat_sim", "habitat", "GltfImporter", "AssimpImporter"]:
    logging.getLogger(_logger_name).setLevel(logging.ERROR)

from flask import Flask, Response, jsonify, request

# Flask Setup
app = Flask(__name__, static_folder="../frontend", static_url_path="")
app.config["JSON_AS_ASCII"] = False

# ─────────────────────────────────────────────────────────────────────────────
# Global Settings & Constants
# ─────────────────────────────────────────────────────────────────────────────
PORT = 5001
VOXEL_SIZE_M = 0.2        # Voxel grid resolution in meters
ARRIVE = 24.0             # CLIP score threshold for ROI target lock (adjusted slightly lower for robustness)
MODEL_TYPE = "siglip"     # Dynamic hot-swappable visual model: "siglip" or "clip"
MAX_STEPS = 250           # Max navigation steps for long-range exploration
AGENT_HEIGHT = 1.20       # Robot camera height in meters
FLOOR_MIN = -1.8          # Floor height range min in meters
FLOOR_MAX = -1.3          # Floor height range max in meters
OBSTACLE_MAX = 0.5        # Obstacle height range max in meters
HFOV = 90.0               # Camera Horizontal Field of View (degrees)

# Target-specific CLIP prompts mapping to frontend names
TARGET_LABELS = {
    "sofa": "a photo of a sofa in a living room",
    "dining_table": "a photo of a dining table in a kitchen",
    "desk": "a photo of a desk in an office",
    "exit": "a photo of a door or hallway exit",
    "television": "a photo of a television screen in a living room",
    "chair": "a photo of a chair in a room",
}

# Comprehensive Chinese-to-English translation dictionary for common household objects
CHINESE_TO_ENGLISH_MAP = {
    # Predefined targets and aliases
    "沙发": "sofa",
    "床": "bed",
    "卧室": "bed",
    "餐桌": "dining_table",
    "桌子": "dining_table",
    "书桌": "desk",
    "办公桌": "desk",
    "出口": "exit",
    "门口": "exit",
    "门": "exit",
    
    # Common household objects for open-vocabulary visual search
    "椅子": "chair",
    "凳子": "chair",
    "靠椅": "chair",
    "餐椅": "chair",
    "植物": "plant",
    "盆栽": "potted plant",
    "绿植": "potted plant",
    "花": "flower",
    "花盆": "potted plant",
    "冰箱": "refrigerator",
    "电视": "television",
    "电视机": "television",
    "电视柜": "tv stand",
    "马桶": "toilet",
    "厕所": "toilet",
    "卫生间": "toilet",
    "洗手池": "sink",
    "水槽": "sink",
    "洗手盆": "sink",
    "柜子": "cabinet",
    "衣柜": "wardrobe",
    "书柜": "bookcase",
    "储物柜": "cabinet",
    "灯": "lamp",
    "台灯": "lamp",
    "落地灯": "floor lamp",
    "微波炉": "microwave",
    "烤箱": "oven",
    "洗衣机": "washing machine",
    "窗户": "window",
    "窗": "window",
    "地毯": "carpet",
    "地垫": "carpet",
    "镜子": "mirror",
    "垃圾桶": "trash can",
    "饮水机": "water dispenser",
    "电脑": "computer",
    "书": "book",
    "杯子": "cup",
    "水杯": "cup",
    "茶杯": "cup",
    "枕头": "pillow",
    "拖鞋": "slippers",
}


# ─────────────────────────────────────────────────────────────────────────────
# Thread-safe Communication Queues for main-thread simulator calls
# ─────────────────────────────────────────────────────────────────────────────
sim_request_queue = queue.Queue()
sim_response_queue = queue.Queue()
sim_lock = threading.Lock()

def sim_execute(cmd, *args):
    """Put task in request queue and block thread-safely until result is ready."""
    with sim_lock:
        sim_request_queue.put((cmd, args))
        res = sim_response_queue.get()
        if isinstance(res, Exception):
            raise res
        return res

# Global State Shared thread-safely
sim_initialized = False
sim_use_mock = False
clip_initialized = False
siglip_model = None
siglip_processor = None
clip_model_openai = None
clip_processor_openai = None
clip_device = None

current_frame_bytes = b""
frame_lock = threading.Lock()
last_action_taken = "move_forward"
recently_targeted_frontiers = []

nav_state = {
    "status": "idle",       # "idle", "navigating", "done", "error"
    "destination": None,
    "mode": "SPIN",         # "SPIN", "EXPLORE", "EXPLOIT"
    "thinking_logs": [],
    "steps_walked": 0,
    "arrived": False,
    "error_msg": "",
    "error_code": None,
    "position": [0.0, 0.0, 0.0],
    "current_scene": "apartment_1",
    "max_steps": 250,
    "abort_requested": False,
    "current_clip_score": 0.0,
    "highest_conf_score": 0.0,
}
nav_state_lock = threading.Lock()

# NetworkX Voxel Graph
# Node format: (x_grid, z_grid)
# Voxel properties:
#   - voxel_type: 1=FREE (navigable ground), 2=OCCUPIED (obstacle)
#   - obj_conf: maximum CLIP score logged
voxel_graph = nx.Graph()
voxel_lock = threading.Lock()

def add_thinking(log_line):
    """Thread-safe append to thinking logs."""
    timestamp = time.strftime("[%H:%M:%S]")
    sys.stderr.write(f"{timestamp} {log_line}\n")
    sys.stderr.flush()
    with nav_state_lock:
        nav_state["thinking_logs"].append(f"{timestamp} {log_line}")
        if len(nav_state["thinking_logs"]) > 200:
            nav_state["thinking_logs"] = nav_state["thinking_logs"][-200:]

# ─────────────────────────────────────────────────────────────────────────────
# CLIP Inference (Thread-safe, PyTorch runs fine in Flask threads)
# ─────────────────────────────────────────────────────────────────────────────
def load_clip():
    """Load both SigLIP and original OpenAI CLIP models into memory."""
    global siglip_model, siglip_processor, clip_model_openai, clip_processor_openai, clip_device, clip_initialized
    try:
        import torch
        from transformers import SiglipModel, SiglipProcessor, CLIPModel, CLIPProcessor
        
        clip_device = torch.device("cpu") # Robust CPU inference
        
        sys.stderr.write("[CLIP Init] Loading SigLIP model (google/siglip-base-patch16-224)...\n")
        sys.stderr.flush()
        siglip_model = SiglipModel.from_pretrained("google/siglip-base-patch16-224")
        siglip_processor = SiglipProcessor.from_pretrained("google/siglip-base-patch16-224")
        siglip_model.to(clip_device)
        siglip_model.eval()
        
        sys.stderr.write("[CLIP Init] Loading original CLIP model (openai/clip-vit-base-patch32)...\n")
        sys.stderr.flush()
        clip_model_openai = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
        clip_processor_openai = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
        clip_model_openai.to(clip_device)
        clip_model_openai.eval()
        
        clip_initialized = True
        sys.stderr.write("[CLIP Init] Both SigLIP and OpenAI CLIP models successfully loaded!\n")
        sys.stderr.flush()
    except Exception as e:
        sys.stderr.write(f"[CLIP Init Error] Failed to load models: {e}\n")
        sys.stderr.flush()

def wait_for_clip(timeout=20):
    """Wait for CLIP model to finish loading in the background thread."""
    start_time = time.time()
    while not clip_initialized:
        if time.time() - start_time > timeout:
            return False
        time.sleep(0.2)
    return True

# Caching global variables for tokenized target text features and temporal smoothing
cached_target_text_features = None
cached_target_prompt = None
smoothed_clip_score = 0.0

def get_clip_score(image: Image.Image, target: str, alpha: float = 0.4) -> float:
    """Compute scoring dynamically based on configured MODEL_TYPE."""
    global cached_target_text_features, cached_target_prompt, smoothed_clip_score
    if not clip_initialized:
        wait_for_clip(20)
    if not clip_initialized:
        return 0.0
    try:
        import torch
        prompt = TARGET_LABELS.get(target, f"a photo of a {target}")
        
        if MODEL_TYPE == "siglip":
            if siglip_model is None or siglip_processor is None:
                return 0.0
            neg_prompt = "a photo of walls, floor or empty space"
            
            # Reset cache if prompt changes or last model was not siglip
            if cached_target_text_features is None or cached_target_prompt != prompt or getattr(get_clip_score, "last_model_type", None) != "siglip":
                text_inputs = siglip_processor(text=[prompt, neg_prompt], padding="max_length", return_tensors="pt")
                text_inputs = {k: v.to(clip_device) for k, v in text_inputs.items()}
                with torch.no_grad():
                    text_features = siglip_model.get_text_features(**text_inputs)
                    text_features = text_features / text_features.norm(dim=-1, keepdim=True)
                    cached_target_text_features = text_features
                    cached_target_prompt = prompt
                    get_clip_score.last_model_type = "siglip"
            
            # Compute image features
            image_inputs = siglip_processor(images=[image], return_tensors="pt")
            image_inputs = {k: v.to(clip_device) for k, v in image_inputs.items()}
            with torch.no_grad():
                image_features = siglip_model.get_image_features(**image_inputs)
                image_features = image_features / image_features.norm(dim=-1, keepdim=True)
                
                logit_scale = siglip_model.logit_scale.exp().item()
                logits = (image_features @ cached_target_text_features.T) * logit_scale
                
                # Softmax relative target probability (Idea A)
                probs = torch.softmax(logits, dim=-1)
                target_prob = probs[0, 0].item()
                raw_similarity = target_prob * 30.0
                
            # EMA Smoothing (Idea B) with Adaptive Alpha support
            if smoothed_clip_score == 0.0:
                smoothed_clip_score = raw_similarity
            else:
                smoothed_clip_score = alpha * raw_similarity + (1 - alpha) * smoothed_clip_score
                
            return smoothed_clip_score
            
        else:
            # Original OpenAI CLIP mode
            if clip_model_openai is None or clip_processor_openai is None:
                return 0.0
            
            # Reset cache if prompt changes or last model was not clip
            if cached_target_text_features is None or cached_target_prompt != prompt or getattr(get_clip_score, "last_model_type", None) != "clip":
                text_inputs = clip_processor_openai(text=[prompt], padding=True, return_tensors="pt")
                text_inputs = {k: v.to(clip_device) for k, v in text_inputs.items()}
                with torch.no_grad():
                    text_features = clip_model_openai.get_text_features(**text_inputs)
                    text_features = text_features / text_features.norm(dim=-1, keepdim=True)
                    cached_target_text_features = text_features
                    cached_target_prompt = prompt
                    get_clip_score.last_model_type = "clip"
                    
            image_inputs = clip_processor_openai(images=[image], return_tensors="pt")
            image_inputs = {k: v.to(clip_device) for k, v in image_inputs.items()}
            with torch.no_grad():
                image_features = clip_model_openai.get_image_features(**image_inputs)
                image_features = image_features / image_features.norm(dim=-1, keepdim=True)
                
                logit_scale = clip_model_openai.logit_scale.exp().item()
                raw_similarity = (image_features @ cached_target_text_features.T).item() * logit_scale
                
            return raw_similarity
            
    except Exception as e:
        sys.stderr.write(f"[CLIP Inference Error] {e}\n")
        sys.stderr.flush()
        return 0.0

# ─────────────────────────────────────────────────────────────────────────────
# Stanford COW Algorithm Helpers
# ─────────────────────────────────────────────────────────────────────────────
def project_depth_to_voxels(rgb_np, depth_np, clip_score):
    """
    Project depth frame to X-Z 2D ground plane grid voxels.
    - Ground elements (height inside FLOOR_MIN to FLOOR_MAX) are marked FREE (1).
    - Obstacles (height inside FLOOR_MAX to OBSTACLE_MAX) are marked OCCUPIED (2) with CLIP score.
    """
    global voxel_graph
    
    # Downsample depth to 32x32 for ultra-fast processing
    H, W = depth_np.shape
    dr = cv2.resize(depth_np, (32, 32), interpolation=cv2.INTER_NEAREST)
    
    # Get current agent pose from simulator
    pose = sim_execute("observe")
    pos = np.array(pose["position"])
    rot_q = pose["rotation"] # Real: [w, x, y, z], Mock: [x, y, z, w]
    
    # Construct rotation matrix R from agent orientation quaternion
    if sim_use_mock:
        qx, qy, qz, qw = rot_q[0], rot_q[1], rot_q[2], rot_q[3]
    else:
        qw, qx, qy, qz = rot_q[0], rot_q[1], rot_q[2], rot_q[3]
        
    R = np.array([
        [1-2*(qy**2+qz**2), 2*(qx*qy-qw*qz), 2*(qx*qz+qw*qy)],
        [2*(qx*qy+qw*qz), 1-2*(qx**2+qz**2), 2*(qy*qz-qw*qx)],
        [2*(qx*qz-qw*qy), 2*(qy*qz+qw*qx), 1-2*(qx**2+qy**2)]
    ], dtype=np.float32)
    
    # Project camera-space coordinates to 3D world space
    scale = math.tan(math.radians(HFOV / 2.0))
    
    # Dynamic ground and floor range detection based on the current agent base position Y
    ground_y = pos[1]
    floor_min = ground_y - 0.20
    floor_max = ground_y + 0.30
    obstacle_max = ground_y + 1.80
    
    with voxel_lock:
        # Mark current agent voxel as FREE
        agent_vx = int(round(pos[0] / VOXEL_SIZE_M))
        agent_vz = int(round(pos[2] / VOXEL_SIZE_M))
        if (agent_vx, agent_vz) not in voxel_graph.nodes:
            voxel_graph.add_node((agent_vx, agent_vz), voxel_type=1, obj_conf=0.0)
        else:
            voxel_graph.nodes[(agent_vx, agent_vz)]["voxel_type"] = 1
            
        for i in range(32):
            y_c = (i + 0.5) / 32.0 * 2.0 - 1.0
            y_cam = -y_c * scale
            for j in range(32):
                x_c = (j + 0.5) / 32.0 * 2.0 - 1.0
                x_cam = x_c * scale * (W / H)
                
                z_cam = dr[i, j]
                if z_cam <= 0.05 or z_cam > 8.0:
                    continue # Ignore invalid or too distant depth points
                    
                # Camera space coordinates
                p_cam = np.array([x_cam * z_cam, y_cam * z_cam, -z_cam], dtype=np.float32)
                
                # Transform to 3D world coordinate
                # Camera Y up, agent standard Camera position height
                p_world = R @ p_cam + pos
                p_world[1] += AGENT_HEIGHT # Add sensor height
                
                xw, yw, zw = p_world[0], p_world[1], p_world[2]
                
                # Voxel X-Z grid index
                vx = int(round(xw / VOXEL_SIZE_M))
                vz = int(round(zw / VOXEL_SIZE_M))
                
                if yw >= floor_min and yw < floor_max:
                    # Ground surface -> mark FREE
                    if (vx, vz) not in voxel_graph.nodes:
                        voxel_graph.add_node((vx, vz), voxel_type=1, obj_conf=0.0)
                    elif voxel_graph.nodes[(vx, vz)]["voxel_type"] == 2:
                        # Ground overrides obstacles if multiple points overlap
                        voxel_graph.nodes[(vx, vz)]["voxel_type"] = 1
                elif yw >= floor_max and yw < obstacle_max:
                    # Obstacle surface -> mark OCCUPIED
                    if (vx, vz) not in voxel_graph.nodes:
                        voxel_graph.add_node((vx, vz), voxel_type=2, obj_conf=clip_score)
                    else:
                        if voxel_graph.nodes[(vx, vz)]["voxel_type"] != 1:
                            voxel_graph.nodes[(vx, vz)]["voxel_type"] = 2
                            voxel_graph.nodes[(vx, vz)]["obj_conf"] = max(
                                voxel_graph.nodes[(vx, vz)].get("obj_conf", 0.0),
                                clip_score
                            )
                            
        # Connect 4-neighbor adjacency edges for FREE nodes in NetworkX
        for n in list(voxel_graph.nodes):
            if voxel_graph.nodes[n]["voxel_type"] != 1:
                continue
            x, z = n
            for dx, dz in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                nb = (x + dx, z + dz)
                if nb in voxel_graph.nodes and voxel_graph.nodes[nb]["voxel_type"] == 1:
                    if not voxel_graph.has_edge(n, nb):
                        voxel_graph.add_edge(n, nb, weight=1.0)

def find_frontiers() -> list:
    """Find all FREE voxels adjacent to at least one unexplored voxel, sorted by distance."""
    global voxel_graph
    frontiers = []
    pose = sim_execute("observe")
    pos = pose["position"]
    agent_vx = int(round(pos[0] / VOXEL_SIZE_M))
    agent_vz = int(round(pos[2] / VOXEL_SIZE_M))
    
    with voxel_lock:
        for n in voxel_graph.nodes:
            if voxel_graph.nodes[n]["voxel_type"] != 1:
                continue
            x, z = n
            is_frontier = False
            for dx, dz in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                nb = (x + dx, z + dz)
                if nb not in voxel_graph.nodes:
                    is_frontier = True
                    break
            if is_frontier:
                frontiers.append(n)
                
    # Sort frontiers by distance to the agent
    frontiers.sort(key=lambda node: math.sqrt((node[0] - agent_vx)**2 + (node[1] - agent_vz)**2))
    
    # Filter out frontiers that are too close to the agent (within 1.2m)
    # This forces the agent to actually navigate to new rooms/areas rather than skipping locally!
    filtered_frontiers = []
    for node in frontiers:
        dist_m = math.sqrt((node[0] - agent_vx)**2 + (node[1] - agent_vz)**2) * VOXEL_SIZE_M
        if dist_m >= 1.2:
            filtered_frontiers.append(node)
            
    # Fallback to all frontiers if none are further than 1.2m
    if not filtered_frontiers:
        filtered_frontiers = frontiers
        
    # Filter out recently targeted frontiers to prevent back-and-forth oscillations
    non_recent_frontiers = []
    for node in filtered_frontiers:
        # Check if too close to any recently targeted frontier (within 5 voxels / 1.0m)
        too_close = False
        for r_node in recently_targeted_frontiers:
            if math.sqrt((node[0] - r_node[0])**2 + (node[1] - r_node[1])**2) < 5.0:
                too_close = True
                break
        if not too_close:
            non_recent_frontiers.append(node)
            
    if non_recent_frontiers:
        filtered_frontiers = non_recent_frontiers
        
    return filtered_frontiers

# ─────────────────────────────────────────────────────────────────────────────
# Proportional Local Heading Waypoint Follower
# ─────────────────────────────────────────────────────────────────────────────
def move_towards_waypoint(waypoint_pt, only_rotate=False, fine_align=False) -> bool:
    """
    Realistic Local projected 2D proportional heading controller:
    - Rotate agent if heading deviation is > 15 degrees (or > 2.5 degrees if fine_align).
    - Move forward once aligned.
    - only_rotate: If True, only rotate to face target, never move forward (avoids wall-crashing).
    Returns True if waypoint is reached or successfully aligned.
    """
    pose = sim_execute("observe")
    pos = np.array(pose["position"])
    rot_q = pose["rotation"] # Real: [w, x, y, z], Mock: [x, y, z, w]
    
    # 2D Vector in world X-Z coordinates
    vec_world = waypoint_pt - pos
    dist = math.sqrt(vec_world[0]**2 + vec_world[2]**2)
    
    # Tolerance set to 0.15m (smaller than forward step of 0.25m) to guarantee physical steps
    if dist < 0.15 and not only_rotate:
        return True # Reached waypoint
        
    # Correct quaternion parsing based on simulator mode
    if sim_use_mock:
        qx, qy, qz, qw = rot_q[0], rot_q[1], rot_q[2], rot_q[3]
    else:
        qw, qx, qy, qz = rot_q[0], rot_q[1], rot_q[2], rot_q[3]
    
    # Construct complete 3D rotation matrix R from quaternion to handle any pitch/roll tilt robustly
    R = np.array([
        [1-2*(qy**2+qz**2), 2*(qx*qy-qw*qz), 2*(qx*qz+qw*qy)],
        [2*(qx*qy+qw*qz), 1-2*(qx**2+qz**2), 2*(qy*qz-qw*qx)],
        [2*(qx*qz-qw*qy), 2*(qy*qz+qw*qx), 1-2*(qx**2+qy**2)]
    ], dtype=np.float32)
    
    # Project the 3D world offset onto the agent's local camera frame using transpose of R (inverse)
    vec_local = R.T @ vec_world
    
    # Map to local forward and right directions based on simulator type
    if sim_use_mock:
        # In Mock simulator, straight ahead is +Z, right is +X
        v_forward = vec_local[2]
    else:
        # In Habitat-Sim, straight ahead is -Z, right is +X
        v_forward = -vec_local[2]
        
    v_right = vec_local[0]
    
    # Heading angle in local space
    # Positive is right (+X), negative is left (-X)
    local_angle = math.atan2(v_right, v_forward)
    
    # Align rotation if angle deviation > 15 degrees (or > 2.5 degrees if fine_align)
    threshold = math.radians(2.5) if fine_align else math.radians(15)
    
    global last_action_taken
    if abs(local_angle) > threshold:
        if local_angle > 0:
            action = "turn_right_fine" if fine_align else "turn_right"
            sim_execute("act", action)
            last_action_taken = action
        else:
            action = "turn_left_fine" if fine_align else "turn_left"
            sim_execute("act", action)
            last_action_taken = action
    else:
        if only_rotate:
            return True # Target aligned!
        sim_execute("act", "move_forward")
        last_action_taken = "move_forward"
        
    return False

def perform_mini_spin(target: str, highest_conf_score: float, highest_conf_voxel):
    """Perform a quick 360° mini-spin (24 steps of 15°) to scan the new area."""
    global current_frame_bytes
    add_thinking("🔍 到达前沿，进行 360° 高频细粒度扫描...")
    for spin_idx in range(24):
        # 15 degrees turn is 3 turn_right_fine calls
        sim_execute("act", "turn_right_fine")
        sim_execute("act", "turn_right_fine")
        sim_execute("act", "turn_right_fine")
        time.sleep(0.05)
        
        obs = sim_execute("observe")
        rgb = obs["rgb"]
        depth = obs["depth"]
        pil_img = Image.fromarray(rgb[:, :, :3]) if rgb is not None else None
        clip_score = get_clip_score(pil_img, target) if pil_img is not None else 0.0
        
        with nav_state_lock:
            nav_state["current_clip_score"] = float(clip_score)
            if float(clip_score) > nav_state["highest_conf_score"]:
                nav_state["highest_conf_score"] = float(clip_score)
        
        if rgb is not None:
            rgb_bgr = cv2.cvtColor(rgb, cv2.COLOR_RGBA2BGR)
            ret, jpg_img = cv2.imencode('.jpg', rgb_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ret:
                with frame_lock:
                    current_frame_bytes = jpg_img.tobytes()
        
        if depth is not None:
            project_depth_to_voxels(rgb, depth, clip_score)
            
    # Update highest conf from new voxel data
    with voxel_lock:
        for node in voxel_graph.nodes:
            if voxel_graph.nodes[node]["voxel_type"] == 2:
                score = voxel_graph.nodes[node].get("obj_conf", 0.0)
                if score > highest_conf_score:
                    highest_conf_score = score
                    highest_conf_voxel = node
                    
    with nav_state_lock:
        nav_state["highest_conf_score"] = float(highest_conf_score)
                    
    return highest_conf_score, highest_conf_voxel

# ─────────────────────────────────────────────────────────────────────────────
# Stanford COW Navigation Thread Loop (Runs Inside Flask Thread blocking)
# ─────────────────────────────────────────────────────────────────────────────
def run_stanford_cow_navigation(target: str):
    """
    Blocking navigation sequence. Blocks request thread, running step-by-step:
    1. SPIN: 360° rotation (12 steps of 30°), updates voxel grid.
    2. FBE (Frontier-Based Exploration): Search for target if not locked.
    3. EXPLOIT (ROI lock): Direct path finding to highest confidence voxel.
    """
    global voxel_graph, current_frame_bytes, recently_targeted_frontiers, smoothed_clip_score
    
    add_thinking(f"🚀 开始具身导航，目标: {target.upper()}")
    
    # Reset navigation state
    recently_targeted_frontiers = []
    smoothed_clip_score = 0.0
    unreachable_target_voxels = set()
    with nav_state_lock:
        nav_state["status"] = "navigating"
        nav_state["destination"] = target
        nav_state["mode"] = "SPIN"
        nav_state["thinking_logs"] = []
        nav_state["steps_walked"] = 0
        nav_state["arrived"] = False
        nav_state["error_msg"] = ""
        nav_state["error_code"] = None
        nav_state["current_clip_score"] = 0.0
        nav_state["highest_conf_score"] = 0.0
        
    with voxel_lock:
        voxel_graph.clear()
        
    add_thinking("[SPIN] 🤖 启动 360° 初始化高频环境扫描...")
    
    # ─────────────────────────────────────────────────────────────────────────
    # Phase 1: 360° SPIN Initialization
    # ─────────────────────────────────────────────────────────────────────────
    highest_conf_voxel = None
    highest_conf_score = 0.0
    
    for spin_idx in range(24):
        # 15 degrees turn is 3 turn_right_fine calls
        sim_execute("act", "turn_right_fine")
        sim_execute("act", "turn_right_fine")
        sim_execute("act", "turn_right_fine")
        time.sleep(0.1) # Small simulation settling sleep
        
        # Get sensor observations from simulator via main thread queue
        obs = sim_execute("observe")
        rgb = obs["rgb"]
        depth = obs["depth"]
        pos = obs["position"]
        
        # Save frame to JPEG frame buffer
        if rgb is not None:
            rgb_bgr = cv2.cvtColor(rgb, cv2.COLOR_RGBA2BGR)
            ret, jpg_img = cv2.imencode('.jpg', rgb_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ret:
                with frame_lock:
                    current_frame_bytes = jpg_img.tobytes()
                    
        # Compute CLIP similarity score (runs concurrently in Flask thread)
        pil_img = Image.fromarray(rgb[:, :, :3]) if rgb is not None else None
        clip_score = get_clip_score(pil_img, target) if pil_img is not None else 0.0
        
        with nav_state_lock:
            nav_state["current_clip_score"] = float(clip_score)
            if float(clip_score) > nav_state["highest_conf_score"]:
                nav_state["highest_conf_score"] = float(clip_score)
        
        # Voxel Map projection
        if depth is not None:
            project_depth_to_voxels(rgb, depth, clip_score)
            
        add_thinking(f"[SPIN Step {spin_idx+1}/24] 旋转扫描 {(spin_idx+1)*15}° | 当前 CLIP 置信度 = {clip_score:.2f}")
        
    # Check if target is located during SPIN
    with voxel_lock:
        for node in voxel_graph.nodes:
            if voxel_graph.nodes[node]["voxel_type"] == 2:
                score = voxel_graph.nodes[node].get("obj_conf", 0.0)
                if score > highest_conf_score:
                    highest_conf_score = score
                    highest_conf_voxel = node
                    
    with nav_state_lock:
        nav_state["highest_conf_score"] = float(highest_conf_score)
                    
    add_thinking(f"[SPIN Done] 扫描完成。当前地图体素数量: {len(voxel_graph.nodes)}")
    
    # Set step to 1 for the completed 360 SPIN initialization
    with nav_state_lock:
        nav_state["steps_walked"] = 1
    
    # ─────────────────────────────────────────────────────────────────────────
    # Phase 2: Main Search & Navigate Loop (FBE / EXPLOIT)
    # ─────────────────────────────────────────────────────────────────────────
    stuck_counter = 0
    prev_pos = None
    current_waypoint_idx = 0
    active_path_points = []
    
    with nav_state_lock:
        max_steps = nav_state.get("max_steps", 250)
        
    for step in range(2, max_steps + 1):
        # Check for user-requested abort
        with nav_state_lock:
            if nav_state.get("abort_requested", False):
                nav_state["abort_requested"] = False
                nav_state["status"] = "idle"
                nav_state["arrived"] = False
                nav_state["error_msg"] = "用户手动终止了导航"
                nav_state["error_code"] = "USER_ABORTED"
                
        with nav_state_lock:
            aborted = (nav_state.get("error_code") == "USER_ABORTED")
        if aborted:
            add_thinking("🛑 [ABORT] 用户手动终止了导航，智能体已停止。")
            return False
            
        with nav_state_lock:
            nav_state["steps_walked"] = step
            
        # 1. Observe current frame and compute CLIP
        obs = sim_execute("observe")
        rgb = obs["rgb"]
        depth = obs["depth"]
        pos = np.array(obs["position"])
        
        # Save image frame
        if rgb is not None:
            rgb_bgr = cv2.cvtColor(rgb, cv2.COLOR_RGBA2BGR)
            ret, jpg_img = cv2.imencode('.jpg', rgb_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ret:
                with frame_lock:
                    current_frame_bytes = jpg_img.tobytes()
                    
        # Determine if we can run adaptive/skipped CLIP inference to optimize CPU
        # Run CLIP 100% of the time if:
        # 1. Target is locked (EXPLOIT mode)
        # 2. We are in SPIN phase (not EXPLORE yet)
        # 3. We are NOT actively traveling on a path (active_path_points is empty or finished)
        # Otherwise, in EXPLORE mode traveling to a frontier, run CLIP every 3 steps.
        is_exploit = (highest_conf_score >= ARRIVE)
        is_traveling_fbe = (not is_exploit) and (len(active_path_points) > 0 and current_waypoint_idx < len(active_path_points))
        
        should_run_clip = True
        if is_traveling_fbe:
            # Only run every 3rd step during FBE path traversal
            should_run_clip = (step % 3 == 1)
            
        if should_run_clip:
            pil_img = Image.fromarray(rgb[:, :, :3]) if rgb is not None else None
            clip_score = get_clip_score(pil_img, target) if pil_img is not None else 0.0
        else:
            # Use previous step's clip_score, or 0.0 if not defined yet
            if 'clip_score' not in locals():
                clip_score = 0.0
                
        with nav_state_lock:
            nav_state["current_clip_score"] = float(clip_score)
            
        # Project observation to Voxel map
        if depth is not None:
            project_depth_to_voxels(rgb, depth, clip_score)
            
        # Update best localized target
        highest_conf_score = 0.0
        highest_conf_voxel = None
        with voxel_lock:
            for node in voxel_graph.nodes:
                if voxel_graph.nodes[node]["voxel_type"] == 2:
                    if node in unreachable_target_voxels:
                        continue
                    score = voxel_graph.nodes[node].get("obj_conf", 0.0)
                    if score > highest_conf_score:
                        highest_conf_score = score
                        highest_conf_voxel = node
                        
        with nav_state_lock:
            nav_state["highest_conf_score"] = float(highest_conf_score)
                        
        # Stuck prevention: only check if we actually attempted to move forward!
        if last_action_taken == "move_forward":
            if prev_pos is not None and np.linalg.norm(pos - prev_pos) < 0.02:
                stuck_counter += 1
            else:
                stuck_counter = 0
        else:
            stuck_counter = 0 # Reset when rotating as we naturally don't change position
        prev_pos = pos.copy()
        
        if stuck_counter >= 4:
            add_thinking("⚠️ 检测到卡住！执行避障后撤绕行...")
            # Perform active stuck recovery actions
            sim_execute("act", "turn_right")
            sim_execute("act", "turn_right")
            sim_execute("act", "move_forward")
            stuck_counter = 0
            active_path_points = []
            continue
            
        # Target locked check (EXPLOIT threshold)
        target_locked = (highest_conf_score >= ARRIVE)
        
        if target_locked:
            # EXPLOIT Phase: Direct navigation to the best voxel
            with nav_state_lock:
                nav_state["mode"] = "EXPLOIT"
                
            voxel_pos_world = np.array([highest_conf_voxel[0] * VOXEL_SIZE_M, pos[1], highest_conf_voxel[1] * VOXEL_SIZE_M])
            dist_to_target = np.linalg.norm((voxel_pos_world - pos)[[0, 2]])
            
            add_thinking(f"[EXPLOIT] 🎯 目标锁定！当前置信度 = {clip_score:.2f} (地图峰值 = {highest_conf_score:.2f}) | 距离 = {dist_to_target:.2f}m")
            
            if dist_to_target < 1.2:
                # Close enough! Turn to face the target and complete navigation (rotation only)
                add_thinking("✓ 已到达目标附近！正在调整视角对准目标...")
                
                # Compute centroid of high-confidence voxels representing the target object around highest_conf_voxel
                with voxel_lock:
                    target_voxels = []
                    for node in voxel_graph.nodes:
                        if voxel_graph.nodes[node]["voxel_type"] == 2:
                            d = math.sqrt((node[0] - highest_conf_voxel[0])**2 + (node[1] - highest_conf_voxel[1])**2) * VOXEL_SIZE_M
                            if d <= 2.0 and voxel_graph.nodes[node].get("obj_conf", 0.0) >= (highest_conf_score - 3.0):
                                target_voxels.append(node)
                    
                    if target_voxels:
                        avg_x = sum(n[0] for n in target_voxels) / len(target_voxels)
                        avg_z = sum(n[1] for n in target_voxels) / len(target_voxels)
                        target_center_world = np.array([avg_x * VOXEL_SIZE_M, pos[1], avg_z * VOXEL_SIZE_M])
                    else:
                        target_center_world = voxel_pos_world
                
                # Stage 1: Coarse Alignment (30° big steps, down to 15° tolerance)
                add_thinking("🧭 [粗对齐阶段] 正在大步长快速转向目标...")
                for _ in range(15):
                    aligned = move_towards_waypoint(target_center_world, only_rotate=True, fine_align=False)
                    
                    obs = sim_execute("observe")
                    rgb = obs.get("rgb")
                    if rgb is not None:
                        rgb_bgr = cv2.cvtColor(rgb, cv2.COLOR_RGBA2BGR)
                        ret, jpg_img = cv2.imencode('.jpg', rgb_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
                        if ret:
                            with frame_lock:
                                current_frame_bytes = jpg_img.tobytes()
                    if aligned:
                        break
                    time.sleep(0.05)
                
                # Stage 2: Fine Alignment (5° fine steps, down to 2.5° tolerance)
                add_thinking("🎯 [精对齐阶段] 正在小步长高精度锁定中心...")
                for _ in range(15):
                    aligned = move_towards_waypoint(target_center_world, only_rotate=True, fine_align=True)
                    
                    obs = sim_execute("observe")
                    rgb = obs.get("rgb")
                    if rgb is not None:
                        rgb_bgr = cv2.cvtColor(rgb, cv2.COLOR_RGBA2BGR)
                        ret, jpg_img = cv2.imencode('.jpg', rgb_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
                        if ret:
                            with frame_lock:
                                current_frame_bytes = jpg_img.tobytes()
                        
                        pil_img = Image.fromarray(rgb[:, :, :3])
                        clip_score = get_clip_score(pil_img, target, alpha=1.0)
                        with nav_state_lock:
                            nav_state["current_clip_score"] = float(clip_score)
                            if float(clip_score) > nav_state["highest_conf_score"]:
                                nav_state["highest_conf_score"] = float(clip_score)
                    if aligned:
                        break
                    time.sleep(0.05)
                
                with nav_state_lock:
                    nav_state["status"] = "done"
                    nav_state["arrived"] = True
                    nav_state["position"] = [float(pos[0]), float(pos[1]), float(pos[2])]
                add_thinking("🎉 [DONE] 导航成功！任务顺利完成。")
                return True
                
            # If no active path or target moved, request PathFinder path
            if not active_path_points or current_waypoint_idx >= len(active_path_points):
                # Try finding valid navigation path directly using Habitat PathFinder
                path_points = sim_execute("find_path", voxel_pos_world)
                if path_points and len(path_points) > 1:
                    active_path_points = path_points
                    current_waypoint_idx = 1
                    add_thinking(f"📍 规划直达路径，共 {len(active_path_points)} 个路点")
                else:
                    # Target voxel is not navigable directly (e.g. inside a table), try neighbors
                    # Find a nearby FREE voxel to navigate to
                    with voxel_lock:
                        free_nodes = [n for n in voxel_graph.nodes if voxel_graph.nodes[n]["voxel_type"] == 1]
                    if free_nodes:
                        free_nodes.sort(key=lambda n: math.sqrt((n[0]-highest_conf_voxel[0])**2 + (n[1]-highest_conf_voxel[1])**2))
                        nearest_free = free_nodes[0]
                        free_world = np.array([nearest_free[0] * VOXEL_SIZE_M, pos[1], nearest_free[1] * VOXEL_SIZE_M])
                        path_points = sim_execute("find_path", free_world)
                        if path_points and len(path_points) > 1:
                            active_path_points = path_points
                            current_waypoint_idx = 1
                            add_thinking("📍 规划直达目标邻近FREE点路径")
                        else:
                            add_thinking("⚠️ 直达路径不可达，转为避障探索模式...")
                            if highest_conf_voxel is not None:
                                # Blacklist all target voxels within a 2.0m radius of the unreachable target
                                with voxel_lock:
                                    for node in list(voxel_graph.nodes):
                                        if voxel_graph.nodes[node]["voxel_type"] == 2:
                                            dist = math.sqrt((node[0] - highest_conf_voxel[0])**2 + (node[1] - highest_conf_voxel[1])**2) * VOXEL_SIZE_M
                                            if dist <= 2.0:
                                                unreachable_target_voxels.add(node)
                            target_locked = False # Fall back to exploration
                    else:
                        add_thinking("⚠️ 无可用邻近FREE点且直达路径不可达，转为避障探索模式...")
                        if highest_conf_voxel is not None:
                            # Blacklist all target voxels within a 2.0m radius of the unreachable target
                            with voxel_lock:
                                for node in list(voxel_graph.nodes):
                                    if voxel_graph.nodes[node]["voxel_type"] == 2:
                                        dist = math.sqrt((node[0] - highest_conf_voxel[0])**2 + (node[1] - highest_conf_voxel[1])**2) * VOXEL_SIZE_M
                                        if dist <= 2.0:
                                            unreachable_target_voxels.add(node)
                        target_locked = False
                        
        if not target_locked:
            # EXPLORE Phase: Frontier-Based Exploration (FBE)
            with nav_state_lock:
                nav_state["mode"] = "EXPLORE"
                
            frontiers = find_frontiers()
            add_thinking(f"[EXPLORE] 🔍 当前置信度 = {clip_score:.2f} (地图峰值 = {highest_conf_score:.2f}) | 当前可用前沿点 = {len(frontiers)}")
            
            if not frontiers:
                add_thinking("⚠️ 未检测到有效前沿点，执行原地随机旋转扫寻...")
                sim_execute("act", "turn_right")
                active_path_points = []
                continue
                
            # If no path, request path to nearest frontier
            if not active_path_points or current_waypoint_idx >= len(active_path_points):
                did_mini_spin = False
                # We arrived at a frontier! Perform a 6-step mini-spin to scan the newly discovered room in all directions.
                if active_path_points and current_waypoint_idx >= len(active_path_points):
                    unreachable_target_voxels.clear()  # Clear blacklisted target voxels ONLY upon arrival at a new frontier!
                    highest_conf_score, highest_conf_voxel = perform_mini_spin(target, highest_conf_score, highest_conf_voxel)
                    did_mini_spin = True
                    if highest_conf_score >= ARRIVE:
                        # Target locked during the mini-spin! Skip planning next frontier and lock on!
                        active_path_points = []
                        continue
                
                path_points = None
                for target_frontier in frontiers[:15]:
                    frontier_world = np.array([target_frontier[0] * VOXEL_SIZE_M, pos[1], target_frontier[1] * VOXEL_SIZE_M])
                    path_points = sim_execute("find_path", frontier_world)
                    if path_points and len(path_points) > 1:
                        active_path_points = path_points
                        current_waypoint_idx = 1
                        recently_targeted_frontiers.append(target_frontier)
                        if len(recently_targeted_frontiers) > 8:
                            recently_targeted_frontiers.pop(0)
                        add_thinking(f"🗺️ 规划前沿探索路径，朝向体素: {target_frontier}")
                        break
                
                if not path_points or len(path_points) <= 1:
                    # Random turning to search for another frontier
                    sim_execute("act", "turn_left")
                    active_path_points = []
                    continue
                
                if did_mini_spin:
                    # The mini-spin is completed and next frontier path is planned.
                    # End this step iteration here so the spin counts as exactly 1 step!
                    continue
                    
        # Execute movement towards next path waypoint
        if active_path_points and current_waypoint_idx < len(active_path_points):
            next_waypoint = active_path_points[current_waypoint_idx]
            arrived_waypoint = move_towards_waypoint(next_waypoint)
            if arrived_waypoint:
                current_waypoint_idx += 1
                
        time.sleep(0.05) # Simulation frequency cap
        
    # ─────────────────────────────────────────────────────────────────────────
    # Phase 3: Fallback (If ARRIVE threshold never met, head to best candidate)
    # ─────────────────────────────────────────────────────────────────────────
    if highest_conf_voxel is not None and highest_conf_score > 15.0:
        add_thinking(f"⚠️ 达到最大搜索步数！采取最佳候选方案，直奔置信度最高的目标 (当前置信度={clip_score:.2f}, 地图峰值={highest_conf_score:.2f})")
        
        # Candidate target might be an obstacle. Find a nearby FREE voxel to navigate to.
        with voxel_lock:
            free_nodes = [n for n in voxel_graph.nodes if voxel_graph.nodes[n]["voxel_type"] == 1]
        
        # Sort free voxels by 2D Euclidean distance to candidate voxel
        if free_nodes:
            free_nodes.sort(key=lambda n: math.sqrt((n[0]-highest_conf_voxel[0])**2 + (n[1]-highest_conf_voxel[1])**2))
            target_free = free_nodes[0]
            voxel_pos_world = np.array([target_free[0] * VOXEL_SIZE_M, pos[1], target_free[1] * VOXEL_SIZE_M])
            add_thinking(f"📍 候选目标体素 {highest_conf_voxel} 为障碍物，规划导航至最近 FREE 邻近点 {target_free}")
        else:
            voxel_pos_world = np.array([highest_conf_voxel[0] * VOXEL_SIZE_M, pos[1], highest_conf_voxel[1] * VOXEL_SIZE_M])
            
        # Navigate to candidate for up to 30 steps
        for fallback_step in range(30):
            obs = sim_execute("observe")
            pos = np.array(obs["position"])
            dist = np.linalg.norm((voxel_pos_world - pos)[[0, 2]])
            
            # Update real-time CLIP score and frame buffer during fallback traversal
            rgb = obs.get("rgb")
            if rgb is not None:
                rgb_bgr = cv2.cvtColor(rgb, cv2.COLOR_RGBA2BGR)
                ret, jpg_img = cv2.imencode('.jpg', rgb_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if ret:
                    with frame_lock:
                        current_frame_bytes = jpg_img.tobytes()
                pil_img = Image.fromarray(rgb[:, :, :3])
                clip_score = get_clip_score(pil_img, target)
                with nav_state_lock:
                    nav_state["current_clip_score"] = float(clip_score)
                    if float(clip_score) > nav_state["highest_conf_score"]:
                        nav_state["highest_conf_score"] = float(clip_score)
            
            if dist < 1.3:
                add_thinking("✓ 到达最佳候选物体附近！正在调整视角对准目标...")
                
                # Compute centroid of candidate high-confidence voxels representing the target object
                with voxel_lock:
                    cand_voxels = []
                    for node in voxel_graph.nodes:
                        if voxel_graph.nodes[node]["voxel_type"] == 2:
                            d = math.sqrt((node[0] - highest_conf_voxel[0])**2 + (node[1] - highest_conf_voxel[1])**2) * VOXEL_SIZE_M
                            if d <= 2.0 and voxel_graph.nodes[node].get("obj_conf", 0.0) >= (highest_conf_score - 3.0):
                                cand_voxels.append(node)
                    
                    if cand_voxels:
                        avg_x = sum(n[0] for n in cand_voxels) / len(cand_voxels)
                        avg_z = sum(n[1] for n in cand_voxels) / len(cand_voxels)
                        cand_pos_world = np.array([avg_x * VOXEL_SIZE_M, pos[1], avg_z * VOXEL_SIZE_M])
                    else:
                        cand_pos_world = np.array([highest_conf_voxel[0] * VOXEL_SIZE_M, pos[1], highest_conf_voxel[1] * VOXEL_SIZE_M])
                
                # Stage 1: Coarse Alignment (30° big steps, down to 15° tolerance)
                add_thinking("🧭 [粗对齐阶段] 正在大步长快速转向目标...")
                for _ in range(15):
                    aligned = move_towards_waypoint(cand_pos_world, only_rotate=True, fine_align=False)
                    
                    obs_align = sim_execute("observe")
                    rgb_align = obs_align.get("rgb")
                    if rgb_align is not None:
                        rgb_bgr = cv2.cvtColor(rgb_align, cv2.COLOR_RGBA2BGR)
                        ret, jpg_img = cv2.imencode('.jpg', rgb_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
                        if ret:
                            with frame_lock:
                                current_frame_bytes = jpg_img.tobytes()
                    if aligned:
                        break
                    time.sleep(0.05)
                
                # Stage 2: Fine Alignment (5° fine steps, down to 2.5° tolerance)
                add_thinking("🎯 [精对齐阶段] 正在小步长高精度锁定中心...")
                for _ in range(15):
                    aligned = move_towards_waypoint(cand_pos_world, only_rotate=True, fine_align=True)
                    
                    obs_align = sim_execute("observe")
                    rgb_align = obs_align.get("rgb")
                    if rgb_align is not None:
                        rgb_bgr = cv2.cvtColor(rgb_align, cv2.COLOR_RGBA2BGR)
                        ret, jpg_img = cv2.imencode('.jpg', rgb_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
                        if ret:
                            with frame_lock:
                                current_frame_bytes = jpg_img.tobytes()
                        pil_img = Image.fromarray(rgb_align[:, :, :3])
                        clip_score = get_clip_score(pil_img, target, alpha=1.0)
                        with nav_state_lock:
                            nav_state["current_clip_score"] = float(clip_score)
                            if float(clip_score) > nav_state["highest_conf_score"]:
                                nav_state["highest_conf_score"] = float(clip_score)
                                
                    if aligned:
                        break
                    time.sleep(0.05)
                with nav_state_lock:
                    nav_state["status"] = "done"
                    nav_state["arrived"] = True
                    nav_state["position"] = [float(pos[0]), float(pos[1]), float(pos[2])]
                return True
                
            path_points = sim_execute("find_path", voxel_pos_world)
            if path_points and len(path_points) > 1:
                move_towards_waypoint(path_points[1])
            else:
                # If pathfinder fails to the primary FREE node, try other neighboring FREE nodes
                found_alt = False
                if free_nodes and len(free_nodes) > 1:
                    for alt_node in free_nodes[1:10]: # Try next 9 closest free voxels
                        alt_pos = np.array([alt_node[0] * VOXEL_SIZE_M, pos[1], alt_node[1] * VOXEL_SIZE_M])
                        path_points = sim_execute("find_path", alt_pos)
                        if path_points and len(path_points) > 1:
                            voxel_pos_world = alt_pos
                            move_towards_waypoint(path_points[1])
                            found_alt = True
                            break
                if not found_alt:
                    break
            time.sleep(0.05)
            
    # Navigation Failure
    with nav_state_lock:
        nav_state["status"] = "error"
        nav_state["arrived"] = False
        nav_state["error_msg"] = "未能发现并导航到目标物体，或路径完全被阻隔。"
        nav_state["error_code"] = "CLIP_NOT_FOUND"
    add_thinking("❌ [FAIL] 导航失败：无法锁定且无可用路径。")
    return False

# ─────────────────────────────────────────────────────────────────────────────
# Flask APIs (Thread-safe, communicating with main thread via queues)
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return app.send_static_file("index.html")

@app.route("/video_feed")
def video_feed():
    """High-frequency MJPEG stream from the globally cached frame buffer."""
    def generate():
        while True:
            with frame_lock:
                jpg = current_frame_bytes
            if jpg:
                yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                       + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
            time.sleep(0.05)
    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/api/health")
def api_health():
    return jsonify({
        "status": "ok",
        "simulator_ready": sim_initialized,
        "clip_ready": clip_initialized,
        "mode": "habitat-sim" if not sim_use_mock else "mock"
    })

@app.route("/api/scan", methods=["POST"])
def api_scan():
    """Trigger a CLIP scan to find target direction (for compatibility with integration tests)."""
    global smoothed_clip_score
    smoothed_clip_score = 0.0
    data = request.get_json() or {}
    target = data.get("target", "sofa")
    
    start_t = time.time()
    view_scores = []
    
    # Take 6 views (60 degrees each)
    # 2 turns of turn_right is 60 degrees. So we do 2 turns, scan, 6 times.
    for i in range(6):
        sim_execute("act", "turn_right")
        sim_execute("act", "turn_right")
        time.sleep(0.05)
        
        obs = sim_execute("observe")
        rgb = obs["rgb"]
        pil_img = Image.fromarray(rgb[:, :, :3]) if rgb is not None else None
        score = get_clip_score(pil_img, target) if pil_img is not None else 0.0
        view_scores.append(score)
        
    best_idx = int(np.argmax(view_scores))
    directions = ["right", "back_right", "back_left", "left", "front_left", "front"]
    best_dir = directions[best_idx]
    
    end_t = time.time()
    obs = sim_execute("observe")
    pos = obs["position"]
    
    return jsonify({
        "success": True,
        "target": target,
        "view_scores": view_scores,
        "best_view": best_idx,
        "best_direction": best_dir,
        "confidence": float(view_scores[best_idx]),
        "agent_state": {
            "position": pos,
            "rotation": 0.0,
            "timestamp": int(time.time() * 1000)
        },
        "inference_time_ms": int((end_t - start_t) * 1000)
    })

@app.route("/api/status")
def api_status():
    """Retrieve agent status and real-time thinking logs."""
    obs = sim_execute("observe")
    agent_pos = obs["position"]
    
    with nav_state_lock:
        status_val = nav_state["status"]
        mode_val = nav_state["mode"]
        logs = list(nav_state["thinking_logs"])
        steps = nav_state["steps_walked"]
        arrived = nav_state["arrived"]
        err_msg = nav_state["error_msg"]
        err_code = nav_state["error_code"]
        target = nav_state["destination"]
        current_scene = nav_state.get("current_scene", "apartment_1")
        current_clip_score = nav_state.get("current_clip_score", 0.0)
        highest_conf_score = nav_state.get("highest_conf_score", 0.0)
        
    return jsonify({
        "simulator": "ready" if status_val != "navigating" else "busy",
        "nav_status": status_val,
        "agent_position": agent_pos,
        "mode": mode_val,
        "success": True,
        "step": steps,
        "max_steps": MAX_STEPS,
        "arrived": arrived,
        "thinking": logs,
        "error": err_msg,
        "code": err_code,
        "current_target": target,
        "current_scene": current_scene,
        "current_clip_score": current_clip_score,
        "highest_conf_score": highest_conf_score,
    })

@app.route("/api/change_scene", methods=["POST"])
def api_change_scene():
    """API endpoint to switch Habitat simulation scenes dynamically."""
    data = request.get_json() or {}
    scene_key = data.get("scene", "apartment_1")
    if scene_key not in ["apartment_1", "van_gogh"]:
        return jsonify({"success": False, "error": "无效的场景标识。"}), 400
        
    # Block scene changes if navigation is active
    with nav_state_lock:
        if nav_state["status"] == "navigating":
            return jsonify({"success": False, "error": "正在执行导航指令中，无法切换场景。"}), 409
            
    try:
        # Execute scene change on the main thread via our thread-safe communication queue
        res = sim_execute("change_scene", scene_key)
        
        # Determine max steps for the new scene
        if scene_key == "van_gogh":
            max_steps_for_scene = 100
        else:
            max_steps_for_scene = 250
            
        # Reset navigation logs, states, and voxel representation on Flask side
        with nav_state_lock:
            nav_state["status"] = "idle"
            nav_state["thinking_logs"] = []
            nav_state["steps_walked"] = 0
            nav_state["arrived"] = False
            nav_state["destination"] = None
            nav_state["mode"] = "SPIN"
            nav_state["current_scene"] = scene_key
            nav_state["max_steps"] = max_steps_for_scene
            
        add_thinking(f"🌍 成功切换仿真器场景为: {scene_key.upper()} | 最大探索步数 = {max_steps_for_scene}")
        return jsonify(res)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/abort", methods=["POST"])
def api_abort():
    """Endpoint to request aborting the active navigation loop."""
    with nav_state_lock:
        if nav_state["status"] == "navigating":
            nav_state["abort_requested"] = True
            return jsonify({"success": True, "message": "已成功发送终止导航指令。"})
        else:
            return jsonify({"success": False, "error": "当前没有正在进行的导航任务。"})

@app.route("/api/navigate", methods=["POST"])
def api_navigate():
    """
    Main blocking navigation endpoint.
    Spawns blocking navigation logic, resolving only when reached or failed.
    """
    data = request.get_json() or {}
    destination = data.get("destination", "")
    user_input = data.get("user_input", "")
    
    if not destination:
        return jsonify({
            "success": False,
            "arrived": False,
            "code": "EMPTY_TARGET",
            "error": "导航目标不能为空。"
        }), 400
        
    # Translate target using CHINESE_TO_ENGLISH_MAP if it matches
    dest_key = destination.strip().lower()
    english_dest = CHINESE_TO_ENGLISH_MAP.get(dest_key, dest_key)
    
    with nav_state_lock:
        if nav_state["status"] == "navigating":
            return jsonify({
                "success": False,
                "arrived": False,
                "code": "BUSY",
                "error": "导航指令执行中，请稍后再试。"
            }), 409
            
    # Run navigation (blocks Flask request thread thread-safely)
    success = run_stanford_cow_navigation(english_dest)
    
    with nav_state_lock:
        status_val = nav_state["status"]
        arrived = nav_state["arrived"]
        err_msg = nav_state["error_msg"]
        err_code = nav_state["error_code"]
        pos = nav_state["position"]
        steps = nav_state["steps_walked"]
        highest_conf = nav_state["highest_conf_score"]
        
    return jsonify({
        "success": success and arrived,
        "arrived": arrived,
        "target": destination,
        "arrived_position": pos,
        "steps": steps,
        "highest_conf": highest_conf,
        "path_length": steps * 0.25,
        "error": err_msg if not arrived else None,
        "code": err_code if not arrived else None
    })

@app.route("/api/reset", methods=["POST"])
def api_reset():
    """Teleport agent to a random navigable spawn point."""
    try:
        res = sim_execute("reset")
        with nav_state_lock:
            nav_state["status"] = "idle"
            nav_state["thinking_logs"] = []
            nav_state["steps_walked"] = 0
            nav_state["arrived"] = False
        add_thinking("🏠 智能体已复位到起始点。")
        return jsonify({"success": True, "position": res["position"]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/api/teleport", methods=["POST"])
def api_teleport():
    """Teleport agent to a specific coordinate [x, y, z] and rotation [w, x, y, z] for benchmarking."""
    data = request.get_json() or {}
    position = data.get("position")
    rotation = data.get("rotation", [1.0, 0.0, 0.0, 0.0]) # Default rotation [w, x, y, z]
    if position is None:
        return jsonify({"success": False, "error": "Missing position parameter"}), 400
    try:
        res = sim_execute("teleport", position, rotation)
        with nav_state_lock:
            nav_state["status"] = "idle"
            nav_state["thinking_logs"] = []
            nav_state["steps_walked"] = 0
            nav_state["arrived"] = False
        add_thinking(f"🏠 智能体已传送至指定点: {position}。")
        return jsonify({"success": True, "position": res["position"]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/api/config", methods=["POST"])
def api_config():
    """Dynamically configure the active model type and score arrival threshold."""
    global MODEL_TYPE, ARRIVE
    data = request.get_json() or {}
    if "model_type" in data:
        MODEL_TYPE = data["model_type"].lower()
    if "arrive_threshold" in data:
        ARRIVE = float(data["arrive_threshold"])
    add_thinking(f"⚙️ 系统配置已更新: MODEL_TYPE={MODEL_TYPE}, ARRIVE={ARRIVE}")
    return jsonify({"success": True, "model_type": MODEL_TYPE, "arrive_threshold": ARRIVE})

# ─────────────────────────────────────────────────────────────────────────────
# Main Thread Simulator Runner Loop
# ─────────────────────────────────────────────────────────────────────────────
def run_main_thread_simulator_loop():
    """
    Main simulator runner. Runs strictly on the process's main thread
    to prevent Metal context crashes on macOS.
    """
    global sim_initialized, sim_use_mock, current_frame_bytes
    
    sys.stderr.write("[Main Thread] Initializing Habitat-Sim...\n")
    sys.stderr.flush()
    
    sim = None
    agent = None
    scene_path = os.path.expanduser(
        "~/.habitat-data/versioned_data/habitat_test_scenes/apartment_1.glb"
    )
    
    # Try importing habitat_sim and initializing
    try:
        import habitat_sim
        from magnum import Vector2i, Vector3, Deg
        
        # Configure Habitat-Sim
        sim_cfg = habitat_sim.SimulatorConfiguration()
        sim_cfg.scene_id = scene_path
        sim_cfg.enable_physics = False
        sim_cfg.create_renderer = True # Metal context bound strictly to main thread
        
        # Agent configuration with Color (RGB) + Depth sensors
        acfg = habitat_sim.AgentConfiguration()
        acfg.height = AGENT_HEIGHT
        acfg.radius = 0.1
        
        # Action space configurations
        acfg.action_space = {
            "move_forward": habitat_sim.ActionSpec("move_forward", habitat_sim.ActuationSpec(amount=0.25)),
            "turn_left": habitat_sim.ActionSpec("turn_left", habitat_sim.ActuationSpec(amount=30.0)),
            "turn_right": habitat_sim.ActionSpec("turn_right", habitat_sim.ActuationSpec(amount=30.0)),
            "turn_left_fine": habitat_sim.ActionSpec("turn_left", habitat_sim.ActuationSpec(amount=5.0)),
            "turn_right_fine": habitat_sim.ActionSpec("turn_right", habitat_sim.ActuationSpec(amount=5.0)),
        }
        
        # RGB camera sensor specification
        rgb_sensor = habitat_sim.CameraSensorSpec()
        rgb_sensor.uuid = "rgba_camera"
        rgb_sensor.sensor_type = habitat_sim.SensorType.COLOR
        rgb_sensor.sensor_subtype = habitat_sim.SensorSubType.PINHOLE
        rgb_sensor.resolution = Vector2i(640, 480)
        rgb_sensor.position = Vector3(0.0, AGENT_HEIGHT, 0.0) # Correct elevated eye-level POV
        rgb_sensor.orientation = Vector3(0.0, 0.0, 0.0)
        rgb_sensor.hfov = Deg(HFOV)
        acfg.sensor_specifications.append(rgb_sensor)
        
        # Depth sensor specification
        depth_sensor = habitat_sim.CameraSensorSpec()
        depth_sensor.uuid = "depth_camera"
        depth_sensor.sensor_type = habitat_sim.SensorType.DEPTH
        depth_sensor.sensor_subtype = habitat_sim.SensorSubType.PINHOLE
        depth_sensor.resolution = Vector2i(640, 480)
        depth_sensor.position = Vector3(0.0, AGENT_HEIGHT, 0.0) # Correct elevated eye-level POV
        depth_sensor.orientation = Vector3(0.0, 0.0, 0.0)
        depth_sensor.hfov = Deg(HFOV)
        acfg.sensor_specifications.append(depth_sensor)
        
        # Initialize simulator instance
        sim = habitat_sim.Simulator(habitat_sim.Configuration(sim_cfg, [acfg]))
        agent = sim.agents[0]
        
        # Teleport to navigable spawn point
        pf = sim.pathfinder
        rnd = pf.get_random_navigable_point()
        state = habitat_sim.AgentState()
        state.position = list(rnd)
        state.rotation = [0, 0, 0, 1]
        agent.set_state(state)
        
        sim_initialized = True
        sys.stderr.write(f"[Main Thread] ✅ Habitat-Sim successfully initialized! Spawn point: {rnd}\n")
        sys.stderr.flush()
        
        # Generate initial cached frame
        obs = sim.get_sensor_observations()
        rgb = obs.get("rgba_camera")
        if rgb is not None:
            rgb_bgr = cv2.cvtColor(rgb, cv2.COLOR_RGBA2BGR)
            _, jpg = cv2.imencode('.jpg', rgb_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
            with frame_lock:
                current_frame_bytes = jpg.tobytes()
                
    except Exception as e:
        sys.stderr.write(f"[Main Thread Init Error] Habitat-Sim initialization failed: {e}\n")
        sys.stderr.write("[Main Thread] ⚠️ Switching to MockSimulator fallback mode.\n")
        sys.stderr.flush()
        
        from mock_simulator import create_mock_simulator
        sim, agent = create_mock_simulator("apartment_0")
        sim_initialized = True
        sim_use_mock = True
        
        # Generate initial mock frame
        obs = sim.get_sensor_observations()
        rgb = obs.get("rgba_camera")
        if rgb is not None:
            rgb_bgr = cv2.cvtColor(rgb, cv2.COLOR_RGBA2BGR)
            _, jpg = cv2.imencode('.jpg', rgb_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
            with frame_lock:
                current_frame_bytes = jpg.tobytes()

    # ─────────────────────────────────────────────────────────────────────────
    # Command loop running continuously on main thread
    # ─────────────────────────────────────────────────────────────────────────
    while True:
        try:
            try:
                cmd, args = sim_request_queue.get(timeout=0.01)
            except queue.Empty:
                continue
                
            res = None
            if cmd == "observe":
                obs = sim.get_sensor_observations()
                rgb = obs.get("rgba_camera")
                depth = obs.get("depth_camera")
                
                # Check mock vs real format
                if sim_use_mock:
                    pos = sim.get_agent_state().position
                    rot = sim.get_agent_state().rotation
                else:
                    pos = agent.get_state().position
                    rot = agent.get_state().rotation
                    
                res = {
                    "rgb": rgb.copy() if rgb is not None else None,
                    "depth": depth.copy() if depth is not None else None,
                    "position": [float(pos[0]), float(pos[1]), float(pos[2])],
                    "rotation": [float(rot.w), float(rot.x), float(rot.y), float(rot.z)] if not sim_use_mock else list(rot)
                }
            elif cmd == "act":
                action = args[0]
                collision = agent.act(action)
                res = {"collision": collision}
                
                # Immediately capture observations and update the cached frame buffer!
                # This guarantees that the MJPEG video stream displays intermediate turns and movement in real-time.
                obs = sim.get_sensor_observations()
                rgb = obs.get("rgba_camera")
                if rgb is not None:
                    rgb_bgr = cv2.cvtColor(rgb, cv2.COLOR_RGBA2BGR)
                    ret, jpg = cv2.imencode('.jpg', rgb_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    if ret:
                        with frame_lock:
                            current_frame_bytes = jpg.tobytes()
            elif cmd == "reset":
                pf = sim.pathfinder
                rnd = pf.get_random_navigable_point()
                if sim_use_mock:
                    sim.set_agent_position(list(rnd))
                else:
                    st = habitat_sim.AgentState()
                    st.position = list(rnd)
                    st.rotation = [0, 0, 0, 1]
                    agent.set_state(st)
                res = {"position": list(rnd)}
            elif cmd == "teleport":
                pos = args[0]
                rot = args[1]
                if sim_use_mock:
                    sim.set_agent_position(pos)
                else:
                    st = habitat_sim.AgentState()
                    st.position = pos
                    st.rotation = [rot[1], rot[2], rot[3], rot[0]] # [x, y, z, w]
                    agent.set_state(st)
                res = {"position": pos}
            elif cmd == "change_scene":
                new_scene_key = args[0]
                base_dir = os.path.expanduser("~/.habitat-data/versioned_data/habitat_test_scenes")
                if new_scene_key == "van_gogh":
                    glb_path = os.path.join(base_dir, "van-gogh-room.glb")
                else:
                    # Both apartment_1 and kitchen utilize the large domestic apartment geometry!
                    glb_path = os.path.join(base_dir, "apartment_1.glb")
                
                if not os.path.exists(glb_path):
                    raise FileNotFoundError(f"Scene asset not found: {glb_path}")
                    
                if sim_use_mock:
                    from mock_simulator import create_mock_simulator
                    sim, agent = create_mock_simulator(new_scene_key)
                else:
                    sim_cfg = habitat_sim.SimulatorConfiguration()
                    sim_cfg.scene_id = glb_path
                    sim_cfg.enable_physics = False
                    sim_cfg.create_renderer = True
                    
                    acfg = habitat_sim.AgentConfiguration()
                    acfg.height = AGENT_HEIGHT
                    acfg.radius = 0.1
                    acfg.action_space = {
                        "move_forward": habitat_sim.ActionSpec("move_forward", habitat_sim.ActuationSpec(amount=0.25)),
                        "turn_left": habitat_sim.ActionSpec("turn_left", habitat_sim.ActuationSpec(amount=30.0)),
                        "turn_right": habitat_sim.ActionSpec("turn_right", habitat_sim.ActuationSpec(amount=30.0)),
                        "turn_left_fine": habitat_sim.ActionSpec("turn_left", habitat_sim.ActuationSpec(amount=5.0)),
                        "turn_right_fine": habitat_sim.ActionSpec("turn_right", habitat_sim.ActuationSpec(amount=5.0)),
                    }
                    
                    rgb_sensor = habitat_sim.CameraSensorSpec()
                    rgb_sensor.uuid = "rgba_camera"
                    rgb_sensor.sensor_type = habitat_sim.SensorType.COLOR
                    rgb_sensor.sensor_subtype = habitat_sim.SensorSubType.PINHOLE
                    rgb_sensor.resolution = Vector2i(640, 480)
                    rgb_sensor.position = Vector3(0.0, AGENT_HEIGHT, 0.0)
                    rgb_sensor.orientation = Vector3(0.0, 0.0, 0.0)
                    rgb_sensor.hfov = Deg(HFOV)
                    acfg.sensor_specifications.append(rgb_sensor)
                    
                    depth_sensor = habitat_sim.CameraSensorSpec()
                    depth_sensor.uuid = "depth_camera"
                    depth_sensor.sensor_type = habitat_sim.SensorType.DEPTH
                    depth_sensor.sensor_subtype = habitat_sim.SensorSubType.PINHOLE
                    depth_sensor.resolution = Vector2i(640, 480)
                    depth_sensor.position = Vector3(0.0, AGENT_HEIGHT, 0.0)
                    depth_sensor.orientation = Vector3(0.0, 0.0, 0.0)
                    depth_sensor.hfov = Deg(HFOV)
                    acfg.sensor_specifications.append(depth_sensor)
                    
                    sim.reconfigure(habitat_sim.Configuration(sim_cfg, [acfg]))
                    agent = sim.agents[0]
                    
                pf = sim.pathfinder
                if not sim_use_mock:
                    if new_scene_key == "apartment_1":
                        # Teleport to Living Room coordinate
                        spawn_pt = pf.snap_point(Vector3(6.15748, -1.60025, -0.607536))
                    else:
                        spawn_pt = pf.get_random_navigable_point()
                else:
                    spawn_pt = pf.get_random_navigable_point()
                    
                if sim_use_mock:
                    sim.set_agent_position(list(spawn_pt))
                else:
                    st = habitat_sim.AgentState()
                    st.position = list(spawn_pt)
                    st.rotation = [0, 0, 0, 1]
                    agent.set_state(st)
                    
                obs = sim.get_sensor_observations()
                rgb = obs.get("rgba_camera")
                if rgb is not None:
                    rgb_bgr = cv2.cvtColor(rgb, cv2.COLOR_RGBA2BGR)
                    _, jpg = cv2.imencode('.jpg', rgb_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    with frame_lock:
                        current_frame_bytes = jpg.tobytes()
                        
                with voxel_lock:
                    voxel_graph.clear()
                    
                sys.stderr.write(f"[Main Thread] ✅ Successfully switched to scene: {new_scene_key}!\n")
                sys.stderr.flush()
                res = {"success": True, "scene": new_scene_key, "spawn_point": list(spawn_pt)}
            elif cmd == "find_path":
                target_pt = args[0]
                if sim_use_mock:
                    # In mock mode, pathfinder always returns straight line
                    res = [list(sim.get_agent_state().position), list(target_pt)]
                else:
                    path = habitat_sim.ShortestPath()
                    # Snap start and end points to the closest navigable mesh positions to prevent pathfinding failures
                    snapped_start = sim.pathfinder.snap_point(agent.get_state().position)
                    snapped_end = sim.pathfinder.snap_point(list(target_pt))
                    path.requested_start = snapped_start
                    path.requested_end = snapped_end
                    if sim.pathfinder.find_path(path):
                        res = [list(p) for p in path.points]
                    else:
                        # Fallback to raw unsnapped path planning
                        path.requested_start = agent.get_state().position
                        path.requested_end = list(target_pt)
                        if sim.pathfinder.find_path(path):
                            res = [list(p) for p in path.points]
                        else:
                            res = []
                        
            sim_response_queue.put(res)
        except Exception as e:
            sys.stderr.write(f"[Main Thread Command Execution Error] {e}\n")
            sys.stderr.flush()
            sim_response_queue.put(e)

# ─────────────────────────────────────────────────────────────────────────────
# Server Execution entrypoint
# ─────────────────────────────────────────────────────────────────────────────
def run_flask_background():
    """Start Flask app server in background thread."""
    sys.stderr.write(f"[Server] Starting Flask backend on http://127.0.0.1:{PORT}...\n")
    sys.stderr.flush()
    # Enable threaded=True so multiple Flask requests can be processed concurrently
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True, use_reloader=False)

if __name__ == "__main__":
    # 1. Spawn CLIP loader thread
    clip_thread = threading.Thread(target=load_clip, daemon=True)
    clip_thread.start()
    
    # 2. Spawn Flask server background thread
    flask_thread = threading.Thread(target=run_flask_background, daemon=True)
    flask_thread.start()
    
    # 3. Enter main thread block simulator polling loop (blocks current process)
    run_main_thread_simulator_loop()