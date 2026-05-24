# ADR-001: 使用 Sphere Agent 而非真实 URDF 机器人

**日期**: 2026-05-23
**状态**: accepted

## 问题
2天交付时间内，配置 Tiago/Fetch 等真实 URDF 机器人需要大量时间，且容易遇到兼容性问题。

## 决策
使用 Habitat-Sim 内置 Sphere Agent（radius=0.1m），模拟轮式底盘。

## 理由
- 零配置，直接可用
- 碰撞体积正确（radius 覆盖轮式占地需求）
- 兼容 PathFollower 导航 API
- 完全满足第一阶段演示需求

## 风险
- 机器人外形不够真实 → Phase 2 可替换 URDF

## 后果
后续如需更真实的机器人外形，需重写 `server/app.py` 的 agent 配置部分。