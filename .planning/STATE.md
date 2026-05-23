# STATE.md — Embodied Navigation Agent

> Path: workspace/embodied-nav/.planning/STATE.md

## Project

project_name: embodied-nav
project_path: workspace/embodied-nav
created: 2026-05-23T11:20:00+08:00
last_updated: 2026-05-23T11:25:00+08:00

## Task

task_id: embodied-nav-001
task_name: 具身导航Agent（M1 Pro + Habitat-Sim + OpenClaw）
goal: |
  在 MacBook Pro M1 Pro 上搭建一个具身导航 Agent，支持自然语言指令
  导航到沙发、床等地点，纯视觉感知，无特权信息，2天可交付演示版本。

## Phase

current_phase: plan
current_step: proposal v0.1 complete, SPEC.md pending
current_wave: 2

## Discuss

discuss_summary: |
  用户计划做一个具身导航项目，要求：Habitat-Sim 仿真环境、M1 Pro 本地运行、
  OpenClaw 作为高层大脑（语言理解和规划）、CLIP 做视觉感知（无额外训练）、
  HTML 可视化界面、实时视频推流。目标是2天内交付可演示版本。
  第一阶段不做任何额外训练，只使用开源预训练模型。
  支持5个导航目标：sofa, bed, dining_table, desk, front_door/exit。

## Progress

completed_steps:
  - discuss: 初始化项目，确立方向（导航 vs 操作 vs 持续学习）@ 2026-05-23
  - research_env: habitat-sim 安装 / Replica 数据集 / CLIP 性能 / 导航 API @ 2026-05-23
  - research_openclaw: OpenClaw Skill 规范 / Flask MJPEG 推流 / 对话闭环 @ 2026-05-23
  - research_feasibility: 9模块可行性打分 + 风险评估 + 推荐架构 @ 2026-05-23
  - plan_v1: proposal.md v0.1 完成（10章节：背景/目标/架构/路径/模型/ADR/风险/优化/交付物/参考文献）@ 2026-05-23

## Waves

wave_1:
  - [x] 调研：habitat-sim / Replica / CLIP / 导航 API → 3份调研报告
  - [x] 调研：OpenClaw Skill / Flask MJPEG / 对话闭环
  - [x] 调研：2天可行性评估（9模块打分）

wave_2:
  - [x] 编写：proposal.md v0.1 @ 2026-05-23
  - [ ] 编写：SPEC.md（接口定义 / 数据流 / 目录结构 / 验收标准）
  - [ ] 编写：ADR 决策记录（5个架构决策）

wave_3:
  - [ ] 搭建：Habitat-Sim 环境 + miniconda + Replica apartment_0
  - [ ] 开发：CLIP 视觉感知模块（CPU, openai/clip-vit-base-patch32）
  - [ ] 开发：导航控制模块（Habitat SimpleShortestPathFinder）
  - [ ] 开发：Flask 后端（/api/navigate + /video_feed MJPEG）
  - [ ] 开发：OpenClaw Skill（embodied-nav SKILL.md + scripts/navigate.py）
  - [ ] 开发：HTML 前端（科技感控制台 + 实时视频 + 思考链）

wave_4:
  - [ ] 集成测试：5目标 × 3次端到端验证
  - [ ] 部署：GitHub 仓库 + README + 演示视频

## Blockers

blockers:
  - [B-001] Replica apartment_0 下载（~2GB，可能较慢）→ 先用 habitat_test_scenes 验证 @ 2026-05-23

## Decisions

decisions:
  - ADR-001: 使用 Sphere Agent（简化轮式底盘）而非真实 URDF @ 2026-05-23
  - ADR-002: CLIP CPU 推理而非 MPS（更稳定，无 OOM 风险）@ 2026-05-23
  - ADR-003: Flask MJPEG 推流而非 WebSocket（实现简单，HTML 原生支持）@ 2026-05-23
  - ADR-004: 文档型 Skill 而非 Tool Plugin（直接用 exec 调用脚本）@ 2026-05-23
  - ADR-005: Replica 数据集（语义丰富）而非 HM3D/Gibson @ 2026-05-23

## ADR Index

adr_index:
  - id: 001
    slug: sphere-agent
    title: 使用 Sphere Agent 而非真实 URDF 机器人
    status: accepted
    file: decisions/001-sphere-agent.md
  - id: 002
    slug: clip-cpu
    title: CLIP CPU 推理而非 MPS 推理
    status: accepted
    file: decisions/002-clip-cpu.md
  - id: 003
    slug: mjpeg-stream
    title: Flask MJPEG 推流而非 WebSocket
    status: accepted
    file: decisions/003-mjpeg-stream.md
  - id: 004
    slug: doc-skill
    title: 文档型 Skill 而非 Tool Plugin
    status: accepted
    file: decisions/004-doc-skill.md
  - id: 005
    slug: replica-dataset
    title: Replica 数据集而非 HM3D/Gibson
    status: accepted
    file: decisions/005-replica-dataset.md

## Ephemeral Findings

ephemeral_findings: []

## Session History

sessions:
  - 2026-05-23: 项目立项，明确导航方向
  - 2026-05-23: 3个调研子Agent完成，proposal v0.1 完成