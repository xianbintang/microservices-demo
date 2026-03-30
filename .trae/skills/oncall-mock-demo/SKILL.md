---
name: "oncall-mock-demo"
description: "Run the OnCall virtual employee mock demo on Feishu/Lark. Simulates the complete on-call workflow: alert arrival → RCA analysis → Problem creation → approval → mitigation → recovery verification → correction. Invoke when user wants to run the mock demo, test the on-call flow, or preview the virtual employee interaction in Feishu."
---

# OnCall Mock Demo Skill

在飞书群中模拟完整的值班虚拟员工交互流程，用于验证人机交互效果。

## 演示流程

按照技术方案中的 mermaid 时序图，模拟以下完整流程：

1. 🚨 **告警A到达** → Agent 收到 → 分析过程可见 → RCA 完成 → 创建 P-1001
2. 🚨 **告警B到达**（A还在分析中）→ Agent 归并到 P-1001
3. 🔧 **生成止损方案** → 发审批卡片 → 加急通知
4. 🚨 **告警C到达**（审批等待中）→ Agent 初判归并
5. ✅ **审批通过** → 执行止损 → 恢复观察
6. 📉 **恢复验证** → A/B 恢复，C 未恢复
7. ⚡ **纠偏** → C 拆分为 P-1002
8. 💬 **@Agent 对话** → Agent 回答

告警交错到达，模拟真实值班场景的节奏。

## 使用方式

### 方式一：命令行调用

```bash
SKILL_PATH=".trae/skills/oncall-mock-demo/mock_demo.py"

# 标准模式（约 3-4 分钟，模拟真实值班节奏）
python3 $SKILL_PATH

# 指定总时长（单位：秒），如 5 分钟
python3 $SKILL_PATH --duration 300

# 快速模式（约 40 秒，用于快速验证）
python3 $SKILL_PATH --fast

# 单步模式（每步按回车继续，适合截图/录屏/演示）
python3 $SKILL_PATH --step
```

### 参数说明

| 参数 | 说明 | 示例 |
|------|------|------|
| `--duration <秒>` | 指定演示总时长（秒），自动计算等待倍率 | `--duration 300`（5分钟） |
| `--fast` | 快速模式，等待缩到最短（约 40s） | `--fast` |
| `--step` | 单步模式，每步按回车继续 | `--step` |
| 无参数 | 标准模式，约 3-4 分钟 | |

> `--duration` 和 `--fast` 互斥，同时指定时 `--duration` 优先。

### 方式二：让 AI 执行

直接对 Trae AI 说：

- "运行 Mock 演示"
- "用快速模式跑一下 Mock"
- "跑 5 分钟的 Mock 演示"
- "用单步模式运行 Mock 演示"

## 前置条件

1. `.env` 中配置了 `app_id` / `app_secret` / `feishu_chat_id`
2. 飞书 App Bot 已加入目标群聊
3. 依赖 `feishu-messenger` Skill（同目录下）

## 目录结构

```
.trae/skills/oncall-mock-demo/
├── SKILL.md          # 本文件：Skill 描述与使用指南
└── mock_demo.py      # 核心引擎：Mock 演示脚本
```
