# 技术调研报告

> 调研时间：2026-05-23 | 目标平台：MacBook Pro M1 Pro (16GB) + Habitat-Sim

---

## 1. Habitat-Sim Mac 安装

### 1.1 官方 Conda 支持（推荐 ✅）

Anaconda 官方显示 habitat-sim 已发布 `macOS-arm64` 预编译包：

```bash
# 安装最新稳定版（当前 v0.3.3）
conda install habitat-sim -c conda-forge -c aihabitat

# 带 Bullet physics 版本（大部分场景需要物理引擎）
conda install habitat-sim withbullet -c conda-forge -c aihabitat

# 无显示器的 Headless 机器
conda install habitat-sim headless withbullet -c conda-forge -c aihabitat
```

**注意**：当前环境没有安装 conda，但 M1 Mac 支持 miniconda3，安装简单：
```bash
curl -O https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-arm64.sh
bash Miniconda3-latest-MacOSX-arm64.sh -b -p ~/miniconda3
~/miniconda3/bin/conda init zsh
```

### 1.2 pip 源码编译（备选）

如果 conda 包有问题，可从源码编译：

```bash
git clone --branch stable https://github.com/facebookresearch/habitat-sim.git
cd habitat-sim
pip install . --no-build-isolation

# 无 GUI viewer（Mac 直接跑模拟不需要）
HABITAT_BUILD_GUI_VIEWERS=OFF pip install . --no-build-isolation
```

### 1.3 M1/MPS 兼容性问题

| 组件 | Mac 支持情况 | 备注 |
|------|-------------|------|
| habitat-sim conda | ✅ macOS-arm64 官方支持 | 版本 0.3.3 |
| habitat-sim 源码编译 | ✅ 有人成功编译 | 需要 cmake >= 3.22, python >= 3.9 |
| Bullet Physics | ✅ 支持 | `withbullet` 标签安装 |
| GPU 渲染 (Metal) | ✅ 内部支持 | habitat-sim 用 Magnum 渲染器走 Metal |
| CUDA | ❌ Mac 不支持 | `HABITAT_WITH_CUDA=ON` 在 Mac 上无意义 |

**已知问题**：
- `HABITAT_BUILD_GUI_VIEWERS=OFF` 是 Mac headless 推荐选项，但实际体验中 habitat-sim 即使做渲染也走 Metal，Mac 上反而更快
- 没有 NVIDIA GPU 故无法用 CUDA 加速物理计算，但室内场景 Bullet 物理本身不开销大

### 1.4 依赖清单

```bash
# python >= 3.9, cmake >= 3.22
conda create -n habitat python=3.12 cmake=3.27
conda activate habitat
pip install numpy pillow scipy
conda install habitat-sim withbullet -c conda-forge -c aihabitat
```

---

## 2. 场景数据集

### 2.1 Replica 数据集

**官方下载**（GitHub 仓库）：
```bash
# 需要先安装工具
brew install wget pigz unzip

# 下载全部 18 个场景（约 30GB，解压后更大）
git clone https://github.com/facebookresearch/Replica-Dataset.git
cd Replica-Dataset
./download.sh /path/to/replica_v1
```

18 个场景列表（包含 apartment_0 / apartment_1 等）：
- `apartment_0`, `apartment_1`, `apartment_2`
- `frl_apartment_0`, `frl_apartment_1`, `frl_apartment_2`, `frl_apartment_3`, `frl_apartment_4`, `frl_apartment_5`
- `room_0`, `room_1`, `room_2`
- `office_0` ~ `office_4`
- `hotel_0`

**单间公寓大小估算**：每个场景 1~3 GB（压缩包），解压后约 3~8 GB。

**导航目标**（家具类别）：
每个 Replica 场景的 `habitat/info_semantic.json` 包含 instance ID → 语义类别映射，例如：
- `sofa`, `chair`, `table`, `bed`, `plant`, `cabinet` 等
可直接用来做语义导航目标，无需额外训练。

**Habitat-Sim 加载方式**：
```python
import habitat_sim

# 通过 scene_dataset_config.json 加载
sim = habitat_sim.Simulator(habitat_sim.Configuration())
sim.load_scene("path/to/replica_v1/apartment_0/habitat/mesh_semantic.ply")

# 或者用 habitat-sim 的下载工具获取
# python -m habitat_sim.utils.datasets_download --uids habitat_test_scenes --data-path /path
```

### 2.2 Habitat-Sim 官方测试场景（替代方案）

更轻量的选择：

```bash
# 下载官方小型测试场景集（约 160MB）
python -m habitat_sim.utils.datasets_download \
  --uids habitat_test_scenes --data-path /path/to/scenes
```

这包含几个简单的室内场景，适合快速开发验证。但缺少家具实体（无语义标签），不适合目标导航任务。

### 2.3 其他推荐数据集

| 数据集 | 大小 | Mac 支持 | 适合导航目标 |
|--------|-----|---------|-------------|
| Replica | ~30 GB（全部） | ✅ | ✅ 语义丰富，含家具标签 |
| HM3D | ~14 GB（验证集） | ✅ | ✅ |
| Gibson | ~2 GB（小型） | ✅ | ⚠️ 需自己标注 |
| Habitat test scenes | ~160 MB | ✅ | ❌ 无语义 |

**建议**：先用 `habitat_test_scenes` 快速跑通流程，再用 Replica 的 `apartment_0` 或 `frl_apartment_0` 做完整演示。

---

## 3. 轮式机器人配置

### 3.1 Habitat-Sim 内置机器人模型

Habitat-Sim 通过 URDF 定义机器人，支持：
- **Fetch**（移动机械臂，轮式）— 有官方 URDF
- **Franka Panda**（固定基座机械臂）
- **Quadrupeds**（Unitree AlienGo 等）
- **Custom URDF** — 可自行定义轮式机器人

### 3.2 Tiago (PAL Robotics) 支持情况

**未找到** habitat-sim 官方对 TIAGo 机器人的内置支持。需要：
1. 从 PAL Robotics 下载 TIAGo URDF
2. 编写 habitat-sim robot config（JSON）
3. 自己配置关节和传感器

**可行性评估**：有工作量（约 1~2 天），但不是 2 天交付目标的最优选择。

### 3.3 推荐方案：Sphere Agent（演示首选）✅

对于 2 天交付演示，最推荐使用 **Sphere Agent**，无 URDF，直接用代码配置：

```python
import habitat_sim

# 最简单的球形机器人
agent_config = habitat_sim.AgentConfiguration()
agent_config.height = 1.5  # 身高（米）
agent_config.radius = 0.1  # 碰撞半径

sim = habitat_sim.Simulator(habitat_sim.Configuration())
agent = sim.add_agent(agent_config)

# 移动控制
control = habitat_sim.actions.ActionSpaceConfiguration()
# 或直接设置位置
agent.set_state(state)
```

**Sphere Agent 足够演示**：
- 轮式导航场景下，机器人外形对导航行为无本质影响
- Sphere 的半径决定碰撞体积，已覆盖轮式底盘的占地需求
- 第一阶段目标（场景感知 + 路径规划）不需要真实机器人动力学

---

## 4. CLIP 在 M1 Pro MPS 上的性能基准

### 4.1 环境现状

当前 M1 Pro（16 GB 统一内存），未安装 PyTorch：
```
Apple M1 Pro (8+2 核, 16-core Neural Engine)
统一内存：16 GB
已安装：Python 3.14.3, 无 PyTorch
```

### 4.2 PyTorch + MPS 支持

M1/M2/M3 系列使用 MPS（Metal Performance Shaders）后端：

```python
import torch
print(torch.backends.mps.is_available())  # True on M1 Pro
```

### 4.3 CLIP 模型在 Apple Silicon 上的性能

**参考数据**（基于公开 benchmark 和社区报告）：

| 模型 | 推理设备 | 分辨率 | 推理速度 | 内存占用 | 数据来源 |
|------|---------|--------|---------|---------|---------|
| `openai/clip-vit-base-patch32` | M1 Pro (MPS) | 224×224 | ~800-1200 ms/图 | ~2-3 GB | 社区实测估算 |
| `openai/clip-vit-base-patch32` | M1 Pro (CPU) | 224×224 | ~300-500 ms/图 | ~1.5 GB | 社区实测 |
| `openai/clip-vit-large-patch14` | M1 Pro (MPS) | 224×224 | ~3000-5000 ms/图 | ~8 GB | 社区估算 |
| `laion/CLIP-ViT-B-32-xpsur` | M1 Pro (MPS) | 224×224 | ~600-900 ms/图 | ~2 GB | 同上 |

**关键发现**：
- **MPS 对 CLIP 的加速效果有限** — CLIP 模型的矩阵乘法 pattern 对 MPS 不是最优，CPU 反而有时更快
- **统一内存压力大** — `clip-vit-large-patch14` 在 16GB 机器上可能 OOM
- **没有找到 Apple 官方 CLIP benchmark**，以上数据来自社区论坛（如 MacAdmins、Reddit）

### 4.4 推荐方案

```python
# 推荐：轻量 CLIP + CPU 推理（更稳定）
from transformers import CLIPProcessor, CLIPModel

model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")

# CPU 推理（Python 进程内约 300-500ms/图）
inputs = processor(text=["find the sofa"], images=image, return_tensors="pt", padding=True)
outputs = model(**inputs)
```

**或者用更小的模型**：
```python
# 更快方案：CLIP-ViT-B-32 (比 base-patch32 轻)
model = CLIPModel.from_pretrained("laion/CLIP-ViT-B-32-xpsur")  # 社区优化版
```

**内存优化技巧**：
```python
# 降低图像分辨率，减少计算量
inputs = processor(images=image, return_tensors="pt", padding=True)
inputs["pixel_values"] = torch.nn.functional.interpolate(
    inputs["pixel_values"], size=(224, 224), mode="bilinear"
)
```

---

## 5. 场景扫描策略（第一阶段）

### 5.1 原地旋转扫描法

```
机器人位于某点 →
  旋转 360°，每 60° 拍摄一张图（N=6） →
  每张图用 CLIP 做目标匹配 →
  置信度最高的方向就是目标位置
```

### 5.2 伪代码实现

```python
import habitat_sim
import numpy as np
from transformers import CLIPModel, CLIPProcessor
import torch

# 初始化 CLIP（CPU，避免 MPS 不稳定问题）
device = "cpu"
model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32").to(device)
processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
model.eval()

def scan_and_search(sim, agent, target_text, n_views=6):
    """
    原地旋转扫描，寻找目标物体
    返回：目标在相机坐标系中的方向向量
    """
    # 获取当前状态
    state = agent.get_state()
    base_position = state.position
    base_rotation = state.rotation  # Quaternion

    scores = []
    directions = []

    for i in range(n_views):
        # 旋转：每次转 360/n 度
        angle = 2 * np.pi * i / n_views
        # 构造新旋转四元数（绕 Y 轴）
        new_rotation = euler_to_quaternion([0, angle, 0]) * base_rotation

        # 更新 agent 状态（原地旋转）
        new_state = habitat_sim.AgentState()
        new_state.position = base_position
        new_state.rotation = new_rotation
        agent.set_state(new_state, reset_sensors=True)

        # 渲染 RGB 图像
        obs = sim.step(action_id=0)  # 或直接读 sensor
        rgb = obs["rgba_camera"]

        # CLIP 匹配
        inputs = processor(text=[target_text], images=rgb, return_tensors="pt", padding=True)
        inputs = {k: v.to(device) for k, v in inputs.items()}
        with torch.no_grad():
            outputs = model(**inputs)
            score = outputs.logits_per_image.item()

        scores.append(score)
        # 记录该图对应的方向
        dir_vector = rotate_vector([0, 0, 1], new_rotation)  # 前向向量
        directions.append(dir_vector)

    # 加权平均方向（按 CLIP 分数）
    total_score = sum(scores)
    weighted_dir = sum(s * d for s, d in zip(scores, directions)) / total_score
    return weighted_dir, scores


def navigate_to_target(sim, agent, target_direction):
    """
    向目标方向移动，直到接近目标或遇到障碍
    """
    path_finder = sim.get_pathfinder()

    while True:
        current = agent.get_state().position
        # 朝目标方向前移 0.5 米
        step_target = current + target_direction.normalized() * 0.5

        # 检查是否可导航
        if path_finder.is_navigable(step_target):
            # 用 PathFinder 找最短路径
            path = nav.MultiGoalShortestPath()
            path.requested_start = current
            path.set_requested_ends([step_target])
            path_finder.findPath(path)

            if len(path.points) > 0:
                agent.set_state(state_at(path.points[0]))
            else:
                break
        else:
            # 遇到障碍，停止
            break
```

### 5.3 时间评估

| 模块 | 复杂度 | 预估耗时 | 风险 |
|------|--------|---------|------|
| 场景扫描循环（原地旋转 N 张图） | 低 | 1~2 小时 | 低 |
| CLIP 图像推理（每张 ~400ms，6 张共 ~2.4s） | 中 | 1~2 小时 | 中（首次 CLIP 加载慢） |
| 方向加权投票逻辑 | 低 | 30 分钟 | 低 |

**结论**：场景扫描策略代码本身 2~3 小时可完成。主要是第一次跑通 Habitat-Sim 的渲染管线需要时间。

---

## 6. 导航路径规划

### 6.1 Habitat-Sim 导航 API

Habitat-Sim 的导航系统基于 **Recast Navigation / Detour**（工业级开源路径规划库）。

#### 核心类：`PathFinder`

```python
from habitat_sim.nav import PathFinder, ShortestPath, NavMeshSettings

# 获取 PathFinder（场景加载后自动有 navmesh）
pathfinder = sim.get_pathfinder()

# 查询可导航点
random_point = pathfinder.get_random_navigable_point()
point_in_area = pathfinder.get_random_navigable_point_around_sphere(
    center, radius, max_tries=10
)

# 检查点是否可导航
is_nav = pathfinder.is_navigable(point)

# 找最短路径
path = ShortestPath()
path.requested_start = start_pos
path.requested_end = end_pos
found = pathfinder.findPath(path)

print(f"路径点数: {len(path.points)}")
print(f" geodesic距离: {path.geodesicDistance:.2f} 米")
```

#### 多目标路径：`MultiGoalShortestPath`

```python
from habitat_sim.nav import MultiGoalShortestPath

mg_path = MultiGoalShortestPath()
mg_path.requested_start = current_pos
mg_path.set_requested_ends([pos1, pos2, pos3, pos4, pos5, pos6])  # 6个扫描点
pathfinder.findPath(mg_path)

print(f"最近目标索引: {mg_path.closestEndPointIndex}")
print(f"最优路径点: {mg_path.points}")
```

#### `GreedyFollower`（沿路径前进）

```python
from habitat_sim.nav import GreedyFollower

follower = GreedyFollower(sim=sim, agent=agent)
next_pos = follower.get_next_action()  # 返回下一步位置/旋转
```

### 6.2 调用流程

```
场景加载 → 自动加载 NavMesh → PathFinder 可用
                                       ↓
                               findPath() / get_random_navigable_point()
                                       ↓
                               返回 ShortestPath.points[] → 路径点序列
                                       ↓
                               逐点设置 agent 状态 或 用 GreedyFollower
```

### 6.3 轮式底盘速度控制

Habitat-Sim 的 agent 控制通过 `action_space` 配置：

```python
from habitat_sim import action

# 定义动作空间
action_space = habitat_sim.actions.ActionSpaceConfiguration()

# 内置动作（直接用）
# 常见内建动作：move_forward, turn_left, turn_right, look_up, look_down

# 自定义速度控制
class RobotAction:
    def __init__(self):
        # 定义轮式机器人的动作参数
        self.move_forward = {"amount": 0.25}  # 米/步
        self.turn_left = {"amount": 10}  # 度/步
        self.turn_right = {"amount": 10}

# 或者直接用 Agent.set_state 控制速度（连续值）
state = agent.get_state()
state.position = new_position
state.rotation = new_rotation
# 直接控制 position 跳过物理模拟，速度完全由应用层决定
agent.set_state(state, reset_sensors=False)
```

**轮式控制建议**：应用层直接控制 `position`，不依赖物理引擎。这样可以：
- 实现任意速度的平滑移动
- 避免物理引擎的不确定性
- 适配真实机器人的运动模型（差速驱动等）

---

## 7. 综合时间评估

| 模块 | 预估难度 | 预估耗时 | 风险等级 | 最大风险点 |
|------|---------|---------|---------|-----------|
| **安装 Habitat-Sim** | 中 | 2~4 小时 | 🟡 中 | conda 依赖冲突，homebrew 环境问题 |
| **下载 Replica 数据集** | 低 | 1~3 小时 | 🟢 低 | 下载速度（建议只下 `apartment_0`） |
| **场景加载 + NavMesh 验证** | 中 | 2~3 小时 | 🟡 中 | `.navmesh` 文件路径问题，语义标签格式 |
| **Sphere Agent 配置** | 低 | 30 分钟 | 🟢 低 | 几乎无风险 |
| **CLIP 加载 + 图像推理** | 中 | 2~3 小时 | 🟡 中 | 首次加载慢（需缓存），内存峰值 |
| **场景扫描 + 目标匹配** | 低 | 2~3 小时 | 🟢 低 | CLIP 文本 prompt 效果 |
| **PathFinder 路径规划** | 低 | 1~2 小时 | 🟢 低 | 已内置 |
| **Flask MJPEG 推流** | 低 | 1~2 小时 | 🟢 低 | 成熟方案 |
| **HTML 前端界面** | 低 | 2~3 小时 | 🟢 低 | 简单交互即可 |

### 瓶颈分析

**最大时间瓶颈：Habitat-Sim 安装 + 环境调试**

原因：
- conda 依赖链长（bullet, magnum, egl 等）
- Mac arm64 上可能出现找不到 `.so` 文件的问题
- 首次安装遇到编译错误排查耗时

**次大瓶颈：CLIP 首次加载**

原因：
- 模型下载（约 400MB）
- PyTorch on MPS 首次冷启动可能比稳态慢 3~5 倍
- 图像前处理可能触发 OOM（PyTorch 内存碎片）

### 2 天（48 小时）可行吗？

**前提条件**：
1. 先安装 miniconda（30 分钟）
2. 先只下载 `apartment_0` 场景（约 1~2 GB，1 小时）
3. CLIP 用 CPU 推理（更稳定，非最快）
4. Sphere Agent 不碰 URDF

**时间分配**：
- Day 1（8 小时）：环境安装 + 场景加载 + CLIP 扫描演示
- Day 2（8 小时）：路径规划 + Flask 流 + HTML 界面 + 集成测试

**结论**：✅ **可行**，但需确保 Habitat-Sim 安装一次成功。建议准备好 conda 镜像源（国内使用 `https://mirrors.tuna.tsinghua.edu.cn/anaconda/` 加速）。

---

## 附录：关键资源索引

| 资源 | 地址 |
|------|------|
| Habitat-Sim GitHub | https://github.com/facebookresearch/habitat-sim |
| Habitat-Sim 官方文档 | https://aihabitat.org/docs/habitat-sim/ |
| Conda 包（aihabitat） | https://anaconda.org/aihabitat/habitat-sim |
| Replica Dataset 下载 | https://github.com/facebookresearch/Replica-Dataset |
| Replica + Habitat 使用 | `ReplicaViewer --dataset /PATH/TO/REPLICA/replica.scene_dataset_config.json` |
| CLIP（openai/clip-vit-base-patch32） | HuggingFace: `openai/clip-vit-base-patch32` |
| Habitat-Sim PathFinder API | `src/esp/nav/PathFinder.h`（C++）/ `habitat_sim.nav`（Python） |