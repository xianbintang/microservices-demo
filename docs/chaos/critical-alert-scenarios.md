# 关键告警场景清单

本文档定义了混沌工程实验所需的关键告警场景，用于告警覆盖度检查。

## 告警场景分类

### 1. Pod 状态相关告警

| 场景名称 | 告警名称 | 严重级别 | 必需 | 说明 |
|---------|---------|---------|------|------|
| Pod 崩溃/终止 | PodDown | Critical | 是 | Pod 处于 Down 状态 |
| Pod 就绪状态 | PodNotReady | Critical | 是 | Pod 未处于 Ready 状态 |
| Pod 重启次数过多 | PodRestartTooMany | Warning | 否 | Pod 重启次数超过阈值 |
| Pod 崩溃循环 | PodCrashLoopBackOff | Critical | 是 | Pod 处于 CrashLoopBackOff 状态 |

### 2. 服务可用性相关告警

| 场景名称 | 告警名称 | 严重级别 | 必需 | 说明 |
|---------|---------|---------|------|------|
| 服务完全不可用 | ServiceDown | Critical | 是 | 服务所有 Pod 都不可用 |
| 服务部分不可用 | ServiceUnavailable | Warning | 否 | 服务部分 Pod 不可用 |

### 3. 性能指标相关告警

| 场景名称 | 告警名称 | 严重级别 | 必需 | 说明 |
|---------|---------|---------|------|------|
| 高延迟 | HighLatency | Warning | 是 | P95 延迟超过阈值（如 1s） |
| 高错误率 | HighErrorRate | Warning | 是 | 错误率超过阈值（如 5%） |
| 高 5xx 率 | High5xxRate | Critical | 是 | 5xx 状态码率超过阈值（如 1%） |

### 4. 资源使用相关告警

| 场景名称 | 告警名称 | 严重级别 | 必需 | 说明 |
|---------|---------|---------|------|------|
| CPU 使用率过高 | HighCPUUsage | Warning | 是 | CPU 使用率超过阈值（如 80%） |
| 内存使用率过高 | HighMemoryUsage | Warning | 是 | 内存使用率超过阈值（如 80%） |
| Pod OOM | PodOOMKilled | Critical | 是 | Pod 因内存不足被终止 |
| CPU 节流严重 | CPUThrottlingHigh | Warning | 否 | CPU 节流超过阈值 |

### 5. 依赖服务相关告警

| 场景名称 | 告警名称 | 严重级别 | 必需 | 说明 |
|---------|---------|---------|------|------|
| 上游错误率高 | DependencyErrorRateHigh | Warning | 是 | 调用上游服务错误率超过阈值 |
| 依赖服务超时 | DependencyTimeout | Warning | 是 | 调用上游服务超时率超过阈值 |

### 6. 熔断器相关告警

| 场景名称 | 告警名称 | 严重级别 | 必需 | 说明 |
|---------|---------|---------|------|------|
| 熔断器打开 | CircuitBreakerOpen | Warning | 是 | 熔断器打开状态 |

## 告警覆盖度统计

- **关键场景总数**: 15
- **必需告警数**: 13
- **可选告警数**: 2

## 告警覆盖率阈值

- **最低覆盖率**: 80%（12/15 场景）
- **关键场景要求**: 所有必需告警（13 个）必须覆盖
- **严重级别要求**: 关键场景必须为 Critical 级别

## 告警规则查询

### Prometheus 告警规则查询示例

```bash
# 查询所有告警规则
kubectl get prometheusrules -A

# 查询特定告警规则
kubectl get prometheusrules -A -o json | jq '.items[].spec.groups[].rules[] | select(.alert != null) | .alert'
```

### AlertManager 告警规则查询示例

```bash
# 查询 AlertManager 配置
kubectl get secret alertmanager-alertmanager -n monitoring -o json | jq '.data.alertmanager.yaml' | base64 -d
```

## 使用场景

本清单用于：

1. **混沌实验前置检查**: 在执行混沌实验前检查告警覆盖度
2. **告警补充**: 根据缺失场景补充告警规则
3. **告警验证**: 验证混沌实验期间告警是否正确触发
4. **系统评估**: 评估系统的告警完整性