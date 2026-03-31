---
name: "oncall-mock-realistic"
description: "Run the OnCall realistic mock demo on Feishu/Lark. Unlike the 'oncall-mock-demo' (happy-path), this demo simulates real-world imperfect scenarios: Agent gives wrong RCA → human corrects, Agent suggests bad mitigation → human modifies, Agent gets stuck → asks for help, recovery fails → human takes over. Invoke when user wants to see realistic human-agent collaboration."
---

# OnCall Mock Demo - 真实场景版

模拟真实值守中 Agent 犯错、人类纠偏、协作处理的完整流程。

## 与 oncall-mock-demo 的区别

| 对比维度 | oncall-mock-demo（理想版） | oncall-mock-realistic（真实版） |
|----------|--------------------------|-------------------------------|
| Agent 表现 | 端到端完美处理 | 会犯错、会卡住 |
| 人机协作 | 人只审批 | 人纠偏RCA、修改方案、提供线索、接管问题 |
| RCA 结果 | 一次分析准确 | 第一次分析错误，值班人给新方向后修正 |
| 止损方案 | 方案合理 | 方案有风险，值班人修改后重新审批 |
| 未知问题 | 无 | Agent 分析卡住，主动求助 |
| 恢复验证 | 完美恢复 | 恢复不彻底，值班人接管 |

## 四幕场景

1. 🔴 **RCA 分析错误 → 值班人纠偏**：Agent 判断为 TLS 证书过期，值班人指出方向错误，引导查 DNS
2. 🔧 **止损方案不合适 → 值班人修改**：Agent 建议删 CoreDNS Pod，值班人认为风险太大，改为扩容
3. ❓ **Agent 卡住 → 主动求助**：新告警到达，Agent 分析无果主动询问，值班人告知是已知 bug，静默
4. 👤 **恢复不彻底 → 值班人接管**：止损后指标好转但未完全恢复，值班人决定人工排查

## 使用方式

```bash
SKILL_PATH=".trae/skills/oncall-mock-realistic/mock_demo_realistic.py"

python3 $SKILL_PATH                   # 标准模式（约 3-4 分钟）
python3 $SKILL_PATH --duration 300    # 指定 5 分钟
python3 $SKILL_PATH --fast            # 快速模式（约 40s）
python3 $SKILL_PATH --step            # 单步模式
```

## 前置条件

同 oncall-mock-demo：需要 .env 配置和飞书 App Bot。
