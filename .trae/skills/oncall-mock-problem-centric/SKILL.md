---
name: "oncall-mock-problem-centric"
description: "Run the OnCall Problem-Centric future-mode mock demo on Feishu/Lark. Simulates the next-generation workflow where individual alert cards are no longer sent to the chat. Instead, the Agent autonomously aggregates alerts and sends a single Problem card. All subsequent progress (RCA, action approval, mitigation execution, recovery verification) is communicated as thread replies under the Problem card until the Problem is resolved. Invoke when user wants to see the future Problem-centric on-call workflow."
---

# OnCall Mock Demo - Problem-Centric 未来模式

模拟 Agent 足够强大之后的理想值守模式：**飞书群里只发 Problem 卡片，所有处理进展在话题下回复**。

## 与其他 Mock Demo 的区别

| 对比维度 | oncall-mock-demo（理想版） | oncall-mock-realistic（真实版） | oncall-mock-storm（风暴版） | oncall-mock-problem-centric（未来版） |
|----------|--------------------------|-------------------------------|----------------------------|--------------------------------------|
| 群消息 | 每条告警一张卡片 | 每条告警一张卡片 | 每条告警一张卡片 + 风暴摘要 | **只有 Problem 卡片，无告警卡片** |
| Agent 角色 | 接收告警 → 分析 | 会犯错、需纠偏 | 检测风暴 → 关联分析 | **自主聚合 → 直接输出 Problem** |
| 分析方式 | 逐个分析后创建 Problem | 逐个分析（会出错） | 风暴检测 → 关联分析 | **后台静默聚合，直接给结论** |
| 审批方式 | 群级别审批卡片 | 群级别审批卡片 | 群级别确认 | **话题内审批** |
| 进展更新 | 分散在各告警话题下 | 分散在各告警话题下 | 群级别 + 告警话题 | **全部集中在 Problem 话题下** |
| 信噪比 | 中 | 中 | 中高 | **极高（群只有 Problem 卡片）** |

## 核心理念

> 未来 Agent 足够强大后，值班人不需要看到每条原始告警。
> Agent 在后台自动聚合、分析、归因，然后**只向群里输出一张有明确结论的 Problem 卡片**。
> 所有后续操作（审批、执行、验证、消除）都在这个 Problem 的话题下完成。

## 四幕场景

1. 🧠 **智能聚合 + Problem 创建**
   - Agent 后台收到 4 条告警，自动聚合分析
   - 群里只出现一张 Problem 卡片（P-3001），包含关联告警列表、根因初判、影响范围
   - 话题下回复关联告警明细（折叠展示）

2. 🔍 **话题内 RCA 深入分析**
   - 在 Problem 话题下发送分析过程卡片（Thinking → Done）
   - 分析完成后，更新 Problem 卡片标题（加入根因摘要）

3. 🔧 **话题内止损审批 + 执行**
   - 在 Problem 话题下发送审批卡片（不在群级别）
   - 审批通过 → 话题内发送执行进度 → 执行完成

4. ✅ **恢复验证 + Problem 消除**
   - 话题内发送恢复验证结果
   - 全部恢复 → 更新 Problem 卡片为「已消除」
   - 话题内发送最终总结

## 使用方式

```bash
SKILL_PATH=".trae/skills/oncall-mock-problem-centric/mock_demo_problem_centric.py"

python3 $SKILL_PATH                   # 标准模式（约 3-4 分钟）
python3 $SKILL_PATH --duration 300    # 指定 5 分钟
python3 $SKILL_PATH --fast            # 快速模式（约 40s）
python3 $SKILL_PATH --step            # 单步模式
```

## 前置条件

同 oncall-mock-demo：需要 .env 配置和飞书 App Bot。

## 目录结构

```
.trae/skills/oncall-mock-problem-centric/
├── SKILL.md                          # 本文件：Skill 描述与使用指南
└── mock_demo_problem_centric.py      # 核心引擎：Mock 演示脚本
```
