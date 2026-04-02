---
name: "oncall-mock-storm"
description: "Run the OnCall alert storm mock demo on Feishu/Lark. Simulates an infrastructure failure (K8s node resource exhaustion) that triggers a massive alert storm: 5 alerts in 30 seconds across 4 services. The Agent autonomously aggregates alerts and sends a single Problem card. All subsequent progress (RCA, action approval, mitigation execution, recovery verification) is communicated as thread replies under the Problem card until the Problem is resolved. Invoke when user wants to see the future Problem-centric on-call workflow."
---

# OnCall Mock Demo - 报警风暴版

模拟基础设施故障引发大规模报警风暴的完整处理流程。

## 与其他 Mock Demo 的区别

| 对比维度 | oncall-mock-demo（理想版） | oncall-mock-realistic（真实版） | oncall-mock-storm（风暴版） |
|----------|--------------------------|-------------------------------|----------------------------|
| 告警数量 | 3 条告警 | 2 条告警 | 5 条告警（30 秒内密集到达） |
| 核心场景 | 端到端理想流程 | Agent 犯错、人纠偏 | 报警风暴检测、关联分析、批量静默、纠偏 |
| 分析方式 | 逐个分析 | 逐个分析（会出错） | 先并行分析 → 检测到风暴后创建 Problem 统一处理 |
| 止损方式 | 逐个审批执行 | 审批 + 人修改方案 | 归并 + 静默所有报警规则 + 人工处理节点 |
| 恢复验证 | 逐个验证 | 部分未恢复 | 取消静默 → 4/5 恢复 → 纠偏 → 全部恢复 |

## 三幕场景

1. ⚡ **告警密集到达 + Agent 并行分析 + 风暴触发**
   - 5 条告警陆续密集到达，Agent 对每条独立 ACK + 启动分析（并行处理）
   - 告警1/2/3 各自有分析卡片在推进
   - 第5条到达时触发风暴检测 → 立即创建 Problem P-2001 → 发风暴卡片
   - 中止所有独立分析（更新分析卡片为"已中止"）→ 回到每条告警下通知"已归并至 P-2001"
   - 在 P-2001 话题内静默所有报警规则

2. 🔍 **风暴 RCA + 止损**（P-2001 话题内）
   - Agent 启动关联分析 → RCA 完成：节点 n128-052-031 资源耗尽
   - @值班人建议止损方案 → 值班人确认并去处理节点
   - 值班人通知处理完成

3. ✅ **取消静默 + 恢复验证 + 纠偏**（P-2001 话题内）
   - Agent 取消静默 → 恢复验证第1轮：**4/5 恢复，1条未恢复**
   - 纠偏：Agent 发现 ServiceHighLatency 有独立根因（Redis 缓存打满）→ @值班人
   - 值班人清理 Redis → 第2轮全部恢复 → P-2001 消除

## 使用方式

```bash
SKILL_PATH=".trae/skills/oncall-mock-storm/mock_demo_storm.py"

python3 $SKILL_PATH                   # 标准模式（约 4-5 分钟）
python3 $SKILL_PATH --duration 300    # 指定 5 分钟
python3 $SKILL_PATH --fast            # 快速模式（约 50s）
python3 $SKILL_PATH --step            # 单步模式
```

## 前置条件

同 oncall-mock-demo：需要 .env 配置和飞书 App Bot。

## 目录结构

```
.trae/skills/oncall-mock-storm/
├── SKILL.md              # 本文件：Skill 描述与使用指南
└── mock_demo_storm.py    # 核心引擎：Mock 演示脚本
```
