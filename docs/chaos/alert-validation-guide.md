# 告警验证指南

## 核心原则

**告警规则必须代码固化** - 所有告警规则必须存储在代码仓库中（`deploy/monitoring/alerting/`），禁止使用临时 `kubectl apply` 命令创建告警规则。

告警验证过程中发现的缺失告警或误报，必须通过修改代码来修复，而不是临时添加告警规则。

## 告警验证的目的和重要性

告警验证是混沌工程中确保告警系统有效性的关键步骤。通过混沌实验主动注入故障，可以：

1. **验证告警是否在正确时间触发**
2. **识别告警缺失的场景**
3. **识别告警误报的场景**
4. **评估告警响应时间**
5. **发现告警规则的问题**

## 告警验证流程

### 1. 准备阶段

- 定义实验应触发的告警列表
- 记录当前告警状态（作为基线）

### 2. 执行阶段

- 执行混沌实验
- 观察告警触发情况
- 记录告警触发时间和持续时间

### 3. 分析阶段

- 对比预期告警和实际告警
- 计算告警响应时间
- 识别告警缺失和误报
- 生成告警验证报告

## 如何识别告警缺失

### 常见告警缺失场景

1. **Pod 故障后未触发告警**
   - 检查: 是否有 PodNotReady/PodDown 告警规则
   - 原因: 告警规则缺失或阈值不合理

2. **高延迟未触发告警**
   - 检查: 是否有 HighLatency 告警规则
   - 原因: 阈值设置过高或查询表达式错误

3. **高错误率未触发告警**
   - 检查: 是否有 HighErrorRate/High5xxRate 告警规则
   - 原因: 错误率计算错误或阈值不合理

4. **服务不可用未触发告警**
   - 检查: 是否有 ServiceUnavailable 告警规则
   - 原因: 可用性检测逻辑错误

### 识别方法

```bash
# 查看实验期间触发的告警
kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090:9090

# 在 Prometheus 中查询告警状态
ALERTS{alertstate="firing", namespace="online-boutique"}

# 对比预期告警和实际告警
# 预期告警: PodNotReady, ServiceUnavailable
# 实际告警: PodNotReady
# 缺失告警: ServiceUnavailable
```

## 如何识别告警误报

### 常见告警误报场景

1. **告警过于敏感**
   - 表现: 告警频繁触发，但无实际问题
   - 原因: 阈值设置过低或 `for` 时间过短

2. **告警范围过大**
   - 表现: 不相关的服务也触发告警
   - 原因: 标签选择器过于宽松

3. **环境噪音干扰**
   - 表现: 环境问题触发告警，非应用问题
   - 原因: 未排除环境因素

### 识别方法

```bash
# 查看告警触发的详细信息
ALERTS{alertstate="firing", alertname="HighLatency"}

# 检查告警标签是否正确
# namespace, service, pod 等标签是否准确

# 分析告警触发的时间模式
# 是否在特定时间段频繁触发
```

## 如何评估告警响应时间

### 告警响应时间定义

告警响应时间 = 告警触发时间 - 故障发生时间

### 评估标准

| 告警类型 | 预期响应时间 | 优秀 | 良好 | 需要改进 |
|---------|-------------|------|------|---------|
| Critical | ≤ 30s | < 10s | 10-30s | > 30s |
| Warning | ≤ 2min | < 1min | 1-2min | > 2min |

### 计算方法

```bash
# 获取告警触发时间
ALERTS{alertstate="firing", alertname="PodNotReady"}

# 获取故障发生时间
# 从实验日志中获取

# 计算告警响应时间
# 响应时间 = 告警触发时间 - 故障发生时间

# 示例:
# 故障时间: 10:00:00
# 告警触发时间: 10:00:05
# 响应时间: 5s (优秀)
```

## 如何改进告警规则

### 告警规则常见问题

1. **告警缺失**
   - 添加缺失的告警规则
   - 参考 [告警覆盖度检查指南](./alert-coverage-check-guide.md)

2. **告警误报**
   - 调整告警阈值
   - 增加 `for` 时间
   - 优化标签选择器
   - 添加更多过滤条件

3. **响应时间过长**
   - 检查 Prometheus 抓取间隔
   - 检查告警规则评估间隔
   - 优化告警表达式

4. **告警信息不清晰**
   - 完善 `summary` 和 `description`
   - 添加更多上下文信息
   - 使用合理的标签

### 改进示例

#### 调整阈值

```yaml
# 原始规则（过于敏感）
- alert: HighLatency
  expr: histogram_quantile(0.95, ...) > 500
  for: 1m

# 改进后（合理阈值）
- alert: HighLatency
  expr: histogram_quantile(0.95, ...) > 1000
  for: 5m
```

#### 优化标签

```yaml
# 原始规则（标签不够详细）
- alert: HighLatency
  expr: ...
  labels:
    severity: warning

# 改进后（添加更多上下文）
- alert: HighLatency
  expr: ...
  labels:
    severity: warning
    namespace: online-boutique
    service: "{{ $labels.service_name }}"
  annotations:
    summary: "High P95 latency on {{ $labels.service_name }}"
    description: "Service {{ $labels.service_name }} has P95 latency of {{ $value }}ms"
```

## 告警验证报告模板

详见 [告警验证报告模板](./alert-validation-report-template.md)

## 最佳实践

1. **每次混沌实验后进行告警验证**
2. **记录告警验证结果**
3. **根据验证结果持续改进告警规则**
4. **定期演练告警响应流程**
5. **建立告警规则评审机制**

## 相关文档

- [混沌实验运行手册](./runbook.md)
- [告警覆盖度检查指南](./alert-coverage-check-guide.md)
- [自我恢复能力验证指南](./self-healing-validation-guide.md)
- [告警验证报告模板](./alert-validation-report-template.md)
