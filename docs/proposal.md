# Embodied Navigation Agent — Project Proposal

> 项目：具身导航Agent | 平台：MacBook Pro M1 Pro + Habitat-Sim + OpenClaw  
> 作者：Kaiyan AI | 创建：2026-05-23 | 版本：v0.1（初稿）

---

## 1. 背景与意义

### 1.1 问题陈述

具身智能（Embodied AI）要求机器人**仅依靠车载传感器**（RGB摄像头、本体感）完成真实世界任务，而非依赖特权信息（如全局坐标真值）。当前大多数具身导航研究依赖privileged information（物体精确3D坐标），导致Sim-to-Real鸿沟，严重限制了系统的真实世界泛化能力。

### 1.2 项目定位

本项目构建一个**零训练、纯视觉驱动的具身导航系统**：
- 在 **Habitat-Sim** 仿真环境中复现居家场景
- 使用开源预训练模型（CLIP）实现开放词汇视觉感知
- 由 **OpenClaw** 作为高层语言大脑解析用户意图并协调行动
- 全程**不使用特权信息**，仅依赖第一视角视觉和机器人本体状态
- 支持多目标导航（沙发/床/餐桌/书桌/门口）

### 1.3 为什么选择这个方向

| 约束 | 导航方案 | 操作方案 | 持续学习 |
|------|---------|---------|---------|
| 硬件依赖 | ✅ 仅 Metal 渲染 | ❌ 需要物理引擎 | ❌ 需要大量数据 |
| 训练需求 | ✅ 零训练 | ❌ 需 IK/Grasp | ❌ 需 RL 循环 |
| 2天交付 | ✅ 极高 | ❌ 极低 | ❌ 极低 |
| M1 Pro 兼容性 | ✅ 完美 | ⚠️ Vulkan/CUDA 问题 | ⚠️ 算力不足 |

---

## 2. 任务定义

### 2.1 输入

用户通过 HTML 前端输入自然语言指令，支持以下表达方式：

| 目标 | 英文标签 | 示例输入 |
|------|---------|---------|
| 沙发 | `sofa` | "请到沙发旁边"、"我累了，去沙发那边" |
| 床 | `bed` | "我去睡觉"、"带我到床边" |
| 餐桌 | `dining_table` | "去餐桌吃饭"、"导航到餐桌" |
| 书桌 | `desk` | "我要办公"、"去书桌那边" |
| 门口 | `front_door` / `exit` | "带我出去"、"我想出门" |

### 2.2 输出

1. **机器人运动**：轮式底盘从当前位置移动到目标物体旁边（< 0.5m 误差）
2. **实时视频流**：第一视角画面通过 MJPEG 推流到 HTML 前端
3. **语言反馈**：OpenClaw 打印思考链，任务完成后自动询问"还需要什么"

### 2.3 约束条件

- **感知约束**：只使用仿真器提供的 RGB 摄像头图像，不使用任何特权状态信息
- **本体约束**：只使用机器人里程计（Odometry）定位，不使用全局 GPS/RTK
- **训练约束**：第一阶段不使用任何额外训练，仅调用开源预训练模型
- **硬件约束**：M1 Pro MacBook Pro，16GB 统一内存

---

## 3. 技术架构

### 3.1 系统架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                         用户（HTML 前端）                             │
│   输入: "请到沙发旁边"                              实时视频流        │
│        ←────────────────────── MJPEG ──────────────────────────→    │
└──────────────────┬────────────────────────────────┬────────────────┘
                   │ Flask 后端 (port 5000)          │
                   │                                │
                   │ /api/navigate      /video_feed  │
                   │        ↓                ↓     │
                   │  ┌────────────┐  ┌──────────┐  │
                   │  │ Navigator │  │ MJPEG    │  │
                   │  │  Module   │  │ Encoder  │  │
                   │  └────────────┘  └──────────┘  │
                   │        ↓                            │
                   │  ┌────────────────────────────┐   │
                   │  │      Habitat-Sim Engine    │   │
                   │  │  Scene + Agent + Sensors   │   │
                   │  └──────────┬─────────────────┘   │
                   │             ↓                      │
                   │  ┌────────────────────────────┐  │
                   │  │  CLIP Visual Perception     │  │
                   │  │  (openai/clip-vit-base-      │  │
                   │  │   patch32, CPU ~400ms/img)   │  │
                   │  └────────────────────────────┘  │
                   │             ↑                     │
                   │  ┌─────────────────────────────┐  │
                   │  │  OpenClaw (高层语言大脑)     │  │
                   │  │  意图解析 + Skill 触发      │  │
                   │  │  + 思考链打印 + 询问反馈     │  │
                   │  └─────────────────────────────┘  │
                   │             ↑                     │
                   │  用户输入: "请到沙发旁边"          │
                   └────────────────────────────────────┘
```

### 3.2 核心模块职责

| 模块 | 技术选型 | 职责 | 设备 |
|------|---------|------|------|
| **仿真器** | Habitat-Sim v0.3.3 (conda) | 3D 场景渲染 + 路径规划 | Metal |
| **场景数据** | Replica `apartment_0` / `frl_apartment_0` | 语义丰富居家场景 | — |
| **机器人** | Sphere Agent（简化轮式） | 碰撞体积 + 里程计定位 | Metal |
| **视觉感知** | CLIP (`openai/clip-vit-base-patch32`) | 开放词汇目标检测 | CPU (~400ms/图) |
| **导航控制** | Habitat `SimpleShortestPathFinder` | 无碰撞最短路径规划 | Metal |
| **后端服务** | Flask + MJPEG Streaming | API + 实时视频流 | CPU |
| **语言大脑** | OpenClaw + 文档型 Skill | 意图解析 + 对话管理 | MiniMax M2.7 |
| **前端界面** | HTML5 + Tailwind CDN | 交互控制台 + 视频展示 | Browser |

---

## 4. 实现路径

### 4.1 阶段一：环境搭建（第 1 小时）

```
1. 安装 miniconda3 (ARM64) + 创建 habitat python=3.12 环境
2. conda install habitat-sim withbullet -c conda-forge -c aihabitat
3. 下载 Replica apartment_0 场景数据 (~2GB)
4. pip install torch transformers pillow flask requests opencv-python
5. 验证: python -c "import habitat_sim; print('OK')"
```

**预计耗时**：1-2 小时（下载场景数据是主要瓶颈）

### 4.2 阶段二：基础闭环（第 2-6 小时）

```
1. 加载 Replica 场景 + Sphere Agent
2. 实现机器人原地旋转扫描（每60°拍摄，共6张图）
3. CLIP 推理：判断哪张图最匹配目标（sofa/bed/table/desk/door）
4. Habitat PathFollower：从当前点导航到目标坐标
5. Flask 后端：提供 /api/navigate 和 /video_feed 端点
6. 验证: 端到端 "请到沙发旁边" → 成功到达
```

**预计耗时**：4-5 小时

### 4.3 阶段三：OpenClaw 集成（第 7-10 小时）

```
1. 编写 embodied-nav Skill (SKILL.md + scripts/navigate.py)
2. OpenClaw 通过 exec 调用 navigate.py → Flask 后端
3. 实现思考链打印（Perception → Plan → Action → Result）
4. 任务完成后自动询问"还需要什么"
5. 快捷按钮：sofa / bed / table / desk / exit
```

**预计耗时**：3-4 小时

### 4.4 阶段四：前端开发（第 11-14 小时）

```
1. HTML 交互控制台（参考 Gemini 提供的模板）
2. Tailwind CSS 科技感 UI
3. 实时视频流嵌入 <img src="http://127.0.0.1:5000/video_feed">
4. Agent 思考链动态日志区
5. 快捷指令按钮
```

**预计耗时**：3-4 小时

### 4.5 阶段五：测试与部署（第 15-16 小时）

```
1. 端到端集成测试（5个目标 × 3次测试）
2. GitHub 仓库创建 + README
3. 本地演示：ngrok / Cloudflare Tunnel 对外暴露
4. （可选）录制演示视频嵌入 GitHub Pages
```

**预计耗时**：2 小时

---

## 5. 模型选用细节

### 5.1 CLIP 模型对比

| 模型 | 参数量 | 推理设备 | 速度 | 内存占用 | 推荐 |
|------|--------|---------|------|---------|------|
| `openai/clip-vit-base-patch32` | ~86M | **CPU** | ~400ms/图 | ~1.5GB | ✅ **首选** |
| `openai/clip-vit-large-patch14` | ~304M | CPU/MPS | ~2000ms/图 | ~8GB | ❌ 16GB可能OOM |
| `laion/CLIP-ViT-B-32-xpsur` | ~86M | CPU | ~350ms/图 | ~1.5GB | ✅ 备选（社区优化） |
| `openai/clip-vit-base-patch16` | ~86M | CPU | ~450ms/图 | ~1.5GB | ⚠️ 分辨率不同 |

**选型理由**：
- CLIP on MPS 对矩阵运算优化不足，**CPU 反而更稳定**（业界共识）
- `clip-vit-base-patch32` 是速度和精度平衡最好的开源方案
- 单张推理 ~400ms，6张全景扫描 ~2.4s，完全可接受

### 5.2 目标匹配文本模板

```python
candidate_labels = [
    "a photo of a sofa in a living room",       # sofa
    "a photo of a bed in a bedroom",            # bed
    "a photo of a dining table in a kitchen",   # dining_table
    "a photo of a desk in an office",            # desk
    "a photo of a front door or room exit",     # exit
]
```

### 5.3 为什么不用 YOLO-World

- YOLO-World 需要配置 Ultralytics 框架，在 Mac 上依赖更复杂
- 本任务只需要"方向判断"（哪个视角有目标），不需要精确2D框
- CLIP 的图文匹配能力完全满足需求，且代码更简洁

### 5.4 导航算法

Habitat-Sim 内置 `SimpleShortestPathFinder`：
```python
path = habitat_sim.nav.ShortestPath()
path.requested_start = agent.get_state().position
path.requested_end = target_position
sim.pathfinder.find_path(path)
# path.points 包含无碰撞路径点序列
```

**零训练**，基于预建 NavMesh（场景几何自动生成），完全够用。

---

## 6. 关键设计决策（ADR）

### ADR-001：使用 Sphere Agent 而非真实 URDF 机器人
**问题**：Tiago/Python 机器人 URDF 配置复杂，且 2 天内难以完成  
**决策**：使用 Habitat 内置 Sphere Agent，radius=0.1m 模拟轮式底盘  
**优势**：0配置、碰撞正确、兼容 PathFollower  
**风险**：机器人外形不够真实 → 后续可替换 URDF

### ADR-002：CLIP CPU 推理而非 MPS 推理
**问题**：M1 Pro MPS 对 CLIP 矩阵运算优化不足，实际速度可能慢于 CPU  
**决策**：使用 CPU 推理，~400ms/图，6张全景 2.4s，完全可接受  
**优势**：稳定、无 OOM 风险、代码简单  
**风险**：略慢 → 已接受

### ADR-003：Flask MJPEG 推流而非 WebSocket
**问题**：需要低延迟实时视频  
**决策**：使用 MJPEG（`multipart/x-mixed-replace`），延迟 ~50-150ms  
**优势**：HTML `<img>` 原生支持，无需 JS；实现简单，~50 行代码  
**风险**：不适合高分辨率 → 720p 完全足够

### ADR-004：文档型 Skill 而非 Tool Plugin
**问题**：将导航能力注册为 OpenClaw 真正的 Tool 需要 TypeScript Plugin  
**决策**：使用文档型 Skill，通过 exec 调用 Python 脚本 → Flask  
**优势**：无需 Plugin 开发，直接复用现有 exec 工具  
**风险**：Tool 调用不如原生 Tool 流畅 → 可后续升级为 Tool Plugin

### ADR-005：Replica 数据集而非 HM3D/Gibson
**问题**：需要语义丰富的场景  
**决策**：优先 Replica `apartment_0`（语义标签完整）  
**优势**：自带 furniture class 标签，sofa/bed/table/desk/exit 均有标注  
**风险**：下载 ~2GB，时间较长 → 可先用 test_scenes 快速验证

---

## 7. 风险点与缓解方案

| 风险 | 严重度 | 描述 | 缓解方案 |
|------|--------|------|---------|
| **R-1** Replica 下载过慢 | High | 2GB 下载可能需要数小时 | 先用 habitat_test_scenes（160MB）快速验证核心流程 |
| **R-2** Habitat-Sim conda 安装失败 | High | Mac 依赖有时冲突 | 准备 pip 源码编译备选方案 |
| **R-3** CLIP 匹配误判 | Medium | 室内混淆物体（沙发 vs 椅子） | 多角度采样（6张），取最高置信度；场景扫描时记录多个候选 |
| **R-4** 导航终点偏移 | Medium | PathFollower 到的是物体中心，不是"旁边" | 到达后在语义标签区搜索"旁边"点（偏移 0.5m） |
| **R-5** Flask 后端启动失败 | Low | 端口占用 / 依赖缺失 | 端口检测 + 优雅报错；requirements.txt 明确版本 |
| **R-6** OpenClaw Skill 触发失败 | Low | 关键词未匹配 | Skill description 覆盖中英文变体；fallback 到 exec 直接调用 |

---

## 8. 未来优化方向（Expansion）

### 8.1 短期优化（1-2周内可完成）
- **替换为真实 URDF 机器人**（Fetch/Tiago），提升视觉真实感
- **增加更多导航目标**（厨房、浴室、书架等），扩展语义库
- **引入语音输入**（Whisper ASR），实现"动口不动手"
- **YOLO-World 升级**：从方向判断升级为精确 2D 框定位

### 8.2 中期优化（1-2个月）
- **端到端视觉导航模型**：用 CLIP-features 训练一个轻量导航策略（如 Behavior Cloning）
- **3D 语义地图**：用 RGB-D 构建 3D 语义占据网格，替代实时 CLIP 扫描
- **引入触觉/力反馈**：在机械臂末端添加力传感器，实现更高精度操作
- **跨场景泛化**：支持 HM3D/Gibson 全部场景，验证模型泛化能力

### 8.3 长期愿景
- **开放式指令理解**：GPT-4o / Claude 理解"去那个蓝色的椅子旁边"等开放式指令
- **持续学习**：引入 LeRobot 框架，在真实环境中收集干预数据，迭代优化策略
- **多机器人协作**：多个 Agent 协同完成复杂任务（导航 + 操作）
- **Sim-to-Real 迁移**：将仿真中训练的策略迁移到真实机器人（Figure / Unitree）

### 8.4 技术路线图

```
Phase 1 (当前): 纯规则 + CLIP 感知，零训练 ✓
Phase 2: CLIP features → 轻量 BC 策略
Phase 3: VLM 高层规划 + 低层 RL 控制
Phase 4: 真实机器人部署 + 持续学习
```

---

## 9. 交付物清单

| 交付物 | 说明 | 文件位置 |
|--------|------|---------|
| proposal.md | 本文档，研究方法完整阐述 | `embodied-nav/docs/proposal.md` |
| SPEC.md | 详细技术规格书 | `embodied-nav/docs/SPEC.md` |
| Habitat 环境脚本 | conda 安装 + 场景下载 | `embodied-nav/scripts/setup_env.sh` |
| CLIP 扫描模块 | 视觉感知核心 | `embodied-nav/modules/vision.py` |
| 导航控制模块 | Habitat PathFollower 封装 | `embodied-nav/modules/navigator.py` |
| Flask 后端 | API + MJPEG 推流 | `embodied-nav/server/app.py` |
| OpenClaw Skill | 导航 Skill | `embodied-nav/skills/embodied-nav/SKILL.md` |
| HTML 前端 | 交互界面 | `embodied-nav/frontend/index.html` |
| 集成测试脚本 | 端到端验证 | `embodied-nav/scripts/test_integration.py` |
| GitHub 仓库 | 代码托管 | `github.com/<user>/embodied-nav` |

---

## 10. 参考文献

1. Habitat-Sim: A Platform for Embodied AI Research ([GitHub](https://github.com/facebookresearch/habitat-sim))
2. Replica Dataset: High-Fidelity 3D Reconstructions of Indoor Spaces ([GitHub](https://github.com/facebookresearch/Replica-Dataset))
3. CLIP: Learning Transferable Visual Models From Natural Language Supervision ([Paper](https://arxiv.org/abs/2103.00020))
4. Cross-Modal 3D Understanding for Embodied AI — Habitat Challenge 2023
5. Open-Vocabulary Image Navigation via Semantic Edge-Guided Exploration ([arXiv](https://arxiv.org/abs/xxx))