# ADR-002: CLIP CPU 推理而非 MPS 推理

**日期**: 2026-05-23
**状态**: accepted

## 问题
M1 Pro 的 MPS 后端对 CLIP 模型矩阵运算优化不足，实际速度可能慢于 CPU。

## 决策
使用 CPU 推理（`openai/clip-vit-base-patch32`），~400ms/图，6张全景扫描 ~2.4s。

## 理由
- CPU 对 CLIP 更稳定，无 OOM 风险
- ~400ms/图完全可以接受
- 代码更简单，无需处理 MPS 兼容性问题

## 风险
略慢于最优 MPS 配置 → 已接受（差距不大）