---
description: 检查告警覆盖度，确保混沌实验前关键场景都有告警覆盖
---

# 告警覆盖度检查

## 功能

检查当前告警规则的覆盖度，识别缺失的告警规则，评估是否允许执行混沌实验。

## 用法

```
/chaos-check-alerts [namespace]
```

## 参数

- `namespace`: 可选，指定要检查的命名空间（默认：online-boutique）

## 执行步骤

1. **扫描告警规则**
   - 查询 Prometheus 告警规则
   - 查询 AlertManager 告警配置

2. **对比关键场景清单**
   - 从 `docs/chaos/critical-alert-scenarios.md` 读取必需告警
   - 对比已配置的告警规则

3. **计算覆盖率**
   - 计算覆盖百分比
   - 识别缺失的告警规则

4. **生成报告**
   - 显示已覆盖告警
   - 显示缺失告警
   - 显示覆盖率统计

5. **评估是否允许实验**
   - 覆盖率 ≥ 80% 且关键场景全覆盖 → 允许执行
   - 否则 → 阻塞执行，建议补充告警

## 关键告警场景

- Pod 状态: PodDown, PodNotReady, PodCrashLoopBackOff
- 服务可用性: ServiceDown, ServiceUnavailable
- 性能指标: HighLatency, HighErrorRate, High5xxRate
- 资源使用: HighCPUUsage, HighMemoryUsage, PodOOMKilled
- 依赖服务: DependencyErrorRateHigh, DependencyTimeout
- 熔断器: CircuitBreakerOpen

## 输出示例

```
告警覆盖度检查报告
====================
检查时间: 2024-01-01 10:00:00

覆盖度统计:
- 关键场景总数: 15
- 已覆盖场景数: 13
- 缺失场景数: 2
- 告警覆盖率: 86.7% ✅

已覆盖的告警:
✅ PodDown
✅ PodNotReady
✅ ServiceDown
✅ HighLatency
✅ HighErrorRate
✅ High5xxRate
✅ HighCPUUsage
✅ HighMemoryUsage
...

缺失的告警:
❌ PodOOMKilled (关键)
❌ CircuitBreakerOpen (重要)

评估结果:
- 覆盖率: 86.7% ✅
- 关键缺失: 1 个 ⚠️
- 建议: 补充 PodOOMKilled 告警规则后再执行资源实验

阻塞状态: ⚠️ 允许执行非资源实验，资源实验需要补充告警
```

## 实现说明

本 skill 使用脚本 `scripts/chaos/check-alert-coverage.sh` 执行检查。

调用方式：
```bash
bash scripts/chaos/check-alert-coverage.sh online-boutique
```