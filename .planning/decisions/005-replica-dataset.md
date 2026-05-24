# ADR-005: Replica 数据集而非 HM3D/Gibson

**日期**: 2026-05-23
**状态**: accepted

## 问题
需要语义丰富的室内场景数据集。

## 决策
优先使用 Replica `apartment_0`，包含完整语义标签（sofa/bed/desk/dining_table/exit）。

## 理由
- 语义标签完整，sofa/bed 等目标物体均有标注
- 单间公寓 ~2GB，大小可接受
- habitat-sim 官方支持
- 自带 `info_semantic.json` 可直接查询物体坐标

## 风险
- 下载 ~2GB 耗时 → 可先用 habitat_test_scenes（160MB）快速验证
- 安装 conda 环境耗时 → 准备了 mock_simulator.py 作为 fallback