# ADR-003: Flask MJPEG 推流而非 WebSocket

**日期**: 2026-05-23
**状态**: accepted

## 问题
需要低延迟实时视频流。

## 决策
使用 MJPEG（`multipart/x-mixed-replace`），HTML `<img src="...">` 原生支持，无需 JS。

## 理由
- 实现极简（~50行代码）
- 延迟 ~50-150ms，完全满足演示需求
- 前端无需 WebSocket JS 代码
- 720p @ quality 85 完全够用

## 风险
高分辨率场景 → 720p 完全足够