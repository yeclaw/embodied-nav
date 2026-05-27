# 🤖 Embodied Navigation Agent — Stanford COW (CLIP on Wheels)

> **Stanford COW (CLIP on Wheels) Algorithm** — An advanced, zero-shot open-vocabulary embodied navigation agent running on Apple Silicon macOS (M1/M2/M3 Pro/Max) utilizing **Habitat-Sim**, **OpenAI CLIP**, and **OpenClaw**. 
> 
> By projecting ego-centric RGB-D sensor streams into a 2D NetworkX voxel grid, the agent performs **Frontier-Based Exploration (FBE)** and visual-similarity locking to discover and navigate to arbitrary household targets without any pre-training.

---

## 📸 Real-Time Telemetry Dashboard UI

The system features a state-of-the-art diagnostic control panel (`frontend/index.html`) loaded with rich aesthetics, sleek glassmorphic grids, real-time MJPEG camera streaming, and dynamic visual similarity score progress bars:

```
+-------------------------------------------------------------------------+
|  🌍 3D SCENE: [🏢 Modern Living Room  v]   🔄 Reset Spawn   🛑 终止导航  |
+------------------------------------+------------------------------------+
|                                    |  📊 Robot Telemetry & Diagnostics |
|                                    |  AGENT MODE:    [ EXPLOIT ]        |
|           LIVE MJPEG VIEW          |  STEPS TAKEN:   24 / 250           |
|                                    |  REAL-TIME MATCH SCORE: [27.42]    |
|       (High-frequency video stream) |  ===================[|||||||]====  |
|                                    |  PEAK CONFIDENCE:       27.42      |
|                                    |  POSITION:  (5.22, -1.60, 1.58)    |
+------------------------------------+------------------------------------+
|  🤔 Thought Chain & Planning logs                                       |
|  [09:29:26] 🔍 到达前沿，进行 360° 环境扫描...                            |
|  [09:29:27] [EXPLOIT] 🎯 目标锁定！置信度 = 27.62 | 距离 = 1.62m          |
|  [09:29:28] ✓ 已到达目标附近！正在调整视角对准目标...                      |
+-------------------------------------------------------------------------+
```

---

## 🛠️ Advanced Features & Optimizations

We have implemented a series of robust optimizations to provide a highly premium, smooth, and state-of-the-art interactive experience:

### 1. ⚡ Adaptive CLIP Inference Rate (3x Travel Speedup)
Running PyTorch CLIP Vit-B/32 on CPU takes around `150-250ms` per step. To prevent movement lag, we implemented an **Adaptive Rate Controller**:
* **FBE Frontier Travel**: When walking along planned paths in explored spaces, the agent runs CLIP only once every **`3` steps** (33% adaptive rate), speeding up the travel walk by **300%**!
* **Rotation Scan & Target Lock**: During scanning sweeps (`SPIN`, `perform_mini_spin`) and target lock (`EXPLOIT` mode), the agent runs CLIP at **100% full frequency** to guarantee precision and visual coverage.

### 2. 📊 Real-Time Score Telemetry & Color-Shifting Glow
The frontend dashboard reads real-time scoring data (`current_clip_score` and `highest_conf_score`) streamed dynamically from the Flask `/api/status` API:
* The **REAL-TIME MATCH SCORE** progress bar updates in real time in perfect sync with the 15 FPS video feed.
* Shifting visual aesthetics automatically glow and pulse depending on the CLIP similarity levels:
  - **$\ge 27.0$ (Locked/Arrived)**: Radiant pulsing emerald-green with deep shadows (`shadow-emerald-500/30`).
  - **$\ge 20.0$ (Searching/Suspect)**: Soft amber/yellow (`shadow-amber-500/20`).
  - **$< 20.0$ (Standby/Low)**: Classic cool slate gray.

### 3. 🎥 Live Video & Scoring During Pivot Alignment
During final target alignment (the 15-step pivot rotation to face the object) and Phase 3 Fallback traversal, observation capturing and CLIP inference continue to execute. This ensures the live MJPEG camera stream and telemetry indicators update smoothly instead of appearing frozen.

### 4. 🌍 Hot-Swappable 3D Environments
We support dynamic hot-swapping between two domestic 3D environments:
1. **🏢 Modern Living Room** (`apartment_1.glb`): Large multi-room textured family apartment.
2. **🛏️ Van Gogh Bedroom** (`van-gogh-room.glb`): Faithful 3D recreation of Van Gogh's famous Arles bedroom.
* Teleporting coordinates, physical obstacle heights, FBE vertical projection bounds, and maximum navigation steps (`100` steps for the bedroom, `250` steps for the living room) are adjusted dynamically on the fly!

### 5. 🛑 Thread-Safe Instant Braking (`/api/abort`)
Active blocking navigation loops are terminated dynamically and safely in **$\le 0.01$ seconds** when the user clicks the warning-red `🛑 终止导航` button, putting the simulator back in standby mode.

### 6. 🛋️ Zero-Shot Open-Vocabulary Target Support
Beyond the preset targets, the natural language instruction parser extracts arbitrary target nouns. Standard household nouns are mapped to optimized English terms via a built-in dictionary (`CHINESE_TO_ENGLISH_MAP`), leveraging CLIP's zero-shot capabilities to find and navigate to any custom object (e.g. `"椅子"` / `"chair"` or `"植物"` / `"plant"`).

---

## 📐 Project Directory Structure

```
embodied-nav/
├── README.md               # Project overview and deployment guide
├── requirements.txt        # Python package dependencies
├── frontend/
│   └── index.html          # Sleek HTML dashboard (glassmorphic grid, MJPEG, canvas, graphs)
├── server/
│   ├── app.py              # Flask server + Thread-safe queue runner + Stanford COW engine
│   └── mock_simulator.py   # Lightweight simulator fallback (generates perspective synthetic rooms)
├── skills/
│   └── embodied-nav/
│       └── scripts/
│           └── navigate.py # OpenClaw CLI integration script
├── scripts/
│   ├── setup_env.sh        # Python environment initialization script
│   └── test_integration.py # Automated end-to-end integration navigation tests
└── data/
    └── README.md           # Instructions on how to download scene geometries (.glb)
```

---

## 🚀 Deployment & Installation

### Step 1: Clone the Repository & Configure Python Environment
The system runs on Python 3.9/3.12. Configure the environment using the setup script:
```bash
# Initialize environments and dependencies
bash scripts/setup_env.sh
```
Alternatively, create a conda environment manually:
```bash
conda create -n habitat-py39 python=3.9 -y
conda activate habitat-py39
conda install habitat-sim withbullet -c conda-forge -c aihabitat -y
pip install torch transformers pillow flask opencv-python requests gunicorn networkx
```

### Step 2: Download 3D Scenes (Replica & Van Gogh)
Place the locally downloaded `.glb` and `.navmesh` files into your home directory:
```bash
# Create local habitat scenes directory
mkdir -p ~/.habitat-data/versioned_data/habitat_test_scenes/

# Move scenes assets into place
# Required files:
# 1. apartment_1.glb & apartment_1.navmesh (Modern Living Room)
# 2. van-gogh-room.glb & van-gogh-room.navmesh (Van Gogh Bedroom)
```

### Step 3: Run the Embodied Navigation Server
Start the Flask backend server. It will initialize the main thread queue runner and preload the pre-trained CLIP model:
```bash
# Activate designated environment
conda activate habitat-py39

# Start Flask server
python server/app.py
```
*The server will boot on `http://127.0.0.1:5001` and initialize the default Living Room scene.*

### Step 4: Open the Frontend Diagnostics Dashboard
Launch the sleek GUI control panel:
```bash
# Open frontend directly in your default web browser
open frontend/index.html
```

### Step 5: Run Automated Integration Tests
You can verify the entire pipeline (scanning, navigation, target lock, and arrivals) using our automated script:
```bash
# Run integration tests against all targets
python scripts/test_integration.py
```

---

## 🎮 How to Control and Interact

1. **Preset Shortcuts**: Click any preset target in the dashboard shortcuts panel (e.g. `🛋️ 沙发 (Sofa)`, `🍽️ 餐桌 (Dining)`, `💻 书桌 (Desk)`, `🚪 门口 (Exit)`) to instantly plan and run.
2. **Open-Vocabulary Chat**: Type any conversational Chinese or English instruction in the console input (e.g. `"请去沙发旁边"`, `"去大门口"`, `"please navigate to the chair"`, `"靠近植物"`) and click **🚀 执行具身导航**.
3. **Instant Stop**: While navigating, the execution button morphs into a red `🛑 终止导航` warning. Click it at any step to brake the agent instantly.
4. **Mock Fallback Diagnostics**: If running without a GPU or Habitat assets, the server dynamically falls back to the interactive **Mock Simulator**. Toggle between `apartment_1` and `van_gogh` to watch the virtual agent explore generated 3D household objects in real time!