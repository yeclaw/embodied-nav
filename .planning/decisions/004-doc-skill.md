# ADR-004: 文档型 Skill 而非 Tool Plugin

**日期**: 2026-05-23
**状态**: accepted

## 问题
将导航能力注册为 OpenClaw 原生 Tool 需要 TypeScript Plugin 开发。

## 决策
使用文档型 Skill（SKILL.md + exec → Python 脚本 → Flask HTTP）。

## 理由
- 无需 Plugin 开发脚手架
- 直接复用 exec 工具调用 Python 脚本
- 通过 `requests.post` 与 Flask 后端通信
- 快速交付，2天内容易完成

## 风险
Tool 调用不如原生 Tool 流畅 → Phase 2 可升级为 Tool Plugin