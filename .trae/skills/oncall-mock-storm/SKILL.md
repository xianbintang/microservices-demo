---
name: "oncall-mock-storm"
description: "Run the OnCall alert storm mock demo on Feishu/Lark. Simulates an infrastructure failure (K8s node resource exhaustion) that triggers a massive alert storm: 5 alerts in 30 seconds across 4 services. The Agent detects the storm, switches to correlation analysis mode, identifies the root cause, batch-silences all alerts, and guides recovery verification. Invoke when user wants to see alert storm handling workflow."
---

# OnCall Mock Demo - 报警风暴版

模拟基础设施故障引发大规模报警风暴的完整处理流程。

## 与其他 Mock Demo 的区别

| 对比维度 | oncall-mock-demo（理想版） | oncall-mock-realistic（真实版） | oncall-mock-storm（风暴版） |
|----------|--------------------------|-------------------------------|----------------------------|
| 告警数量 | 3 条告警 | 2 条告警 | 5 条告警（30 秒内密集到达） |
| 核心场景 | 端到端理想流程 | Agent 犯错、人纠偏 | 报警风暴检测、关联分析、批量静默 |
| 分析方式 | 逐个分析 | 逐个分析（会出错） | 检测到风暴后切换为关联分析 |
| 止损方式 | 逐个审批执行 | 审批 + 人修改方案 | 一键批量静默 |
| 恢复验证 | 逐个验证 | 部分未恢复 | 取消静默后统一验证全部恢复 |

## 三幕场景

1. ⚡ **报警风暴识别**：30 秒内 5 条告警密集到达（NodeHighCPU / PodCrashLoopBackOff / ServiceHighErrorRate / PodOOMKilled / ServiceHighLatency），Agent 检测到风暴模式，暂停逐个分析，切换关联分析
2. 🔍 **关联分析 + 风暴归因**：Agent 发现 5 条告警均来自同一 K8s 节点，定位根因为节点资源耗尽（CPU + 内存），建议一键批量静默 → 值班人确认 → 执行批量静默
3. ✅ **故障恢复 + 取消静默**：值班人修复节点后请求提前取消静默 → Agent 取消静默 → 恢复验证全部通过 → 问题消除

## 使用方式

```bash
SKILL_PATH=".trae/skills/oncall-mock-storm/mock_demo_storm.py"

python3 $SKILL_PATH                   # 标准模式（约 3-4 分钟）
python3 $SKILL_PATH --duration 300    # 指定 5 分钟
python3 $SKILL_PATH --fast            # 快速模式（约 40s）
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
