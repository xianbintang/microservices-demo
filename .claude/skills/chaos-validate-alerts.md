---
description: 验证混沌实验期间告警是否正确触发，生成告警验证报告
---

# 告警验证

## 用法

```
/chaos-validate-alerts [namespace] [expected-alerts-file]
```

## 参数

- `namespace`: 可选，指定目标命名空间（默认：online-boutique）
- `expected-alerts-file`: 可选，预期告警列表文件（默认：自动检测混沌工程专用告警）

## 验证内容

1. 查询 Prometheus 中实际触发的告警
2. 对比预期告警和实际告警
3. 计算告警覆盖率
4. 生成验证报告

## 验证逻辑

### 混沌工程专用告警

告警规则 duration 已优化为 30 秒 - 1 分钟：

| 告警名称 | Duration | 触发条件 |
|---------|----------|---------|
| ChaosPodNotRunning | 30s | Pod 状态不是 Running |
| ChaosPodRestartCount | 1m | Pod 在 5 分钟内有重启 |

### 验证流程

1. **查询实际告警**
   - 查询 Prometheus `ALERTS{chaos_test="true",alertstate="firing"}`
   - 查询所有 `ALERTS{alertstate="firing"}`

2. **对比预期告警**
   - 如果提供预期告警文件，对比文件中的告警列表
   - 否则，自动检测混沌工程专用告警

3. **生成报告**
   - 显示匹配的告警
   - 显示缺失的告警
   - 计算告警覆盖率

## 报告输出

### 通过示例

```
==================================
告警验证
==================================
验证时间: 2024-01-01 10:00:00
目标命名空间: online-boutique

==================================
查询实际告警
==================================
混沌工程专用告警: 2 个
所有活跃告警: 2 个

==================================
对比预期告警
==================================
预期告警: 2 个

✓ ChaosPodNotRunning
✓ ChaosPodRestartCount

==================================
验证统计
==================================
匹配告警: 2/2
告警覆盖率: 100%

==================================
验证结论
==================================
覆盖率: 100% ✅
缺失告警: 0 个 ✅

整体评价: 通过 ✅
```

### 不通过示例

```
==================================
告警验证
==================================
验证时间: 2024-01-01 10:00:00
目标命名空间: online-boutique

==================================
查询实际告警
==================================
混沌工程专用告警: 0 个
所有活跃告警: 1 个

⚠ 未检测到混沌工程告警

可能原因:
1. 实验时长过短（< 1 分钟）
2. 故障已恢复，告警已清除
3. 告警规则 duration 未满足

所有活跃告警:
  - Watchdog: namespace=monitoring, pod=N/A, severity=none

==================================
验证结论
==================================
覆盖率: 0% ❌
缺失告警: 2 个 ❌

整体评价: 不通过 ❌

建议:
1. 延长实验时长以满足告警规则 duration
2. 检查故障是否已恢复导致告警清除
3. 验证告警规则表达式是否正确
```

## 实现说明

本 skill 使用脚本 `scripts/chaos/validate-alerts.sh` 执行验证。

调用方式：
```bash
bash scripts/chaos/validate-alerts.sh online-boutique
```

## 关键配置

### 混沌工程告警规则

告警规则定义在 `deploy/monitoring/alerting/chaos-testing-alerts.yaml`:

```yaml
# Pod NotRunning - 30 秒触发
- alert: ChaosPodNotRunning
  expr: kube_pod_status_phase{namespace=~"online-boutique", phase!="Running"} == 1
  for: 30s
  labels:
    severity: warning
    chaos_test: "true"

# Pod Restart Count - 1 分钟触发
- alert: ChaosPodRestartCount
  expr: increase(kube_pod_container_status_restarts_total{namespace=~"online-boutique"}[5m]) > 0
  for: 1m
  labels:
    severity: warning
    chaos_test: "true"
```

### 注意事项

1. **告警规则 duration**: 混沌工程告警已优化为 30 秒 - 1 分钟，比生产环境告警（10-15 分钟）短得多
2. **告警清除**: 故障恢复后告警会自动清除，需在故障持续期间验证
3. **Prometheus 访问**: 脚本需要能访问 Prometheus API（通过 `kubectl exec`）
