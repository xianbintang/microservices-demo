# 告警覆盖度检查指南

## 核心原则

**告警规则必须代码固化** - 所有告警规则必须存储在代码仓库中（`deploy/monitoring/alerting/`），禁止使用临时 `kubectl apply` 命令创建告警规则。

任何告警规则的变更必须遵循以下流程：
1. 修改 `deploy/monitoring/alerting/` 目录下的 YAML 文件
2. 提交代码并通过代码审查
3. 部署到目标环境
4. 验证告警规则生效

## 为什么需要告警覆盖度检查

混沌实验前检查告警覆盖度的重要性：

1. **及时发现能力不足**: 如果关键场景没有告警覆盖，混沌实验引发故障时无法及时发现，可能导致问题扩大
2. **确保实验安全**: 告警覆盖不足的实验存在风险，应该在补充告警后再执行
3. **提高实验价值**: 良好的告警覆盖使混沌实验的验证结果更有意义

## 关键告警场景清单

针对 Online Boutique 微服务，定义关键告警场景：

| 类别 | 关键场景 | 必需告警 | 严重级别 |
|------|---------|---------|---------|
| Pod 状态 | Pod 崩溃/终止 | PodDown/PodNotReady | Critical |
| Pod 状态 | Pod 重启次数过多 | PodRestartTooMany | Warning |
| Pod 状态 | Pod CrashLoopBackOff | PodCrashLoopBackOff | Critical |
| 服务可用性 | 服务完全不可用 | ServiceDown | Critical |
| 服务可用性 | 服务部分不可用 | ServiceUnavailable | Warning |
| 性能指标 | 高延迟（P95） | HighLatency | Warning |
| 性能指标 | 高错误率 | HighErrorRate | Warning |
| 性能指标 | 高 5xx 率 | High5xxRate | Critical |
| 资源使用 | CPU 使用率过高 | HighCPUUsage | Warning |
| 资源使用 | 内存使用率过高 | HighMemoryUsage | Warning |
| 资源使用 | Pod OOM | PodOOMKilled | Critical |
| 资源使用 | CPU 节流严重 | CPUThrottlingHigh | Warning |
| 依赖服务 | 上游错误率高 | DependencyErrorRateHigh | Warning |
| 依赖服务 | 依赖服务超时 | DependencyTimeout | Warning |
| 熔断器 | 熔断器打开 | CircuitBreakerOpen | Warning |

## 告警覆盖度检查流程

### 1. 执行前检查

```bash
# 使用 Claude Code skill
/chaos-check-alerts online-boutique

# 或手动检查
kubectl get prometheusrules -A
```

### 2. 覆盖度评估

扫描当前告警规则，对比关键告警场景清单，计算覆盖率。

### 3. 阻塞判断

- 覆盖率 ≥ 80% 且关键场景全覆盖 → 允许执行实验
- 覆盖率 < 80% 或关键场景缺失 → 阻止实验，提示补充告警

### 4. 告警补充

根据缺失场景生成告警规则模板，添加告警规则到部署。

## 告警覆盖度检查报告模板

```markdown
# 告警覆盖度检查报告

## 检查时间
2024-01-01 10:00:00

## 覆盖度统计
- 关键场景总数: 15
- 已覆盖场景数: 12
- 缺失场景数: 3
- 告警覆盖率: 80%

## 已覆盖的告警 ✅
| 场景 | 告警名称 | 严重级别 | 状态 |
|------|---------|---------|------|
| Pod 崩溃/终止 | PodNotReady | Critical | ✅ |
| 服务完全不可用 | ServiceDown | Critical | ✅ |
| 高延迟 | HighLatency | Warning | ✅ |

## 缺失的告警 ❌
| 场景 | 重要性 | 建议告警名称 | 建议严重级别 |
|------|--------|-------------|-------------|
| Pod CrashLoopBackOff | **关键** | PodCrashLoopBackOff | Critical |
| Pod OOM | **关键** | PodOOMKilled | Critical |
| 熔断器打开 | 重要 | CircuitBreakerOpen | Warning |

## 评估结果
- 覆盖率: 80% ⚠️
- 关键缺失: 2 个 ❌
- 建议: 补充关键缺失的告警规则后再执行混沌实验

## 操作建议
1. 添加 PodCrashLoopBackOff 告警规则（Critical）
2. 添加 PodOOMKilled 告警规则（Critical）
3. 添加 CircuitBreakerOpen 告警规则（Warning）
4. 重新执行告警覆盖度检查
5. 通过后执行混沌实验

## 阻塞状态
❌ 实验执行被阻塞，请补充缺失的告警规则
```

## 告警覆盖率阈值定义

### 阈值设置

| 指标 | 阈值 | 说明 |
|------|------|------|
| 总体覆盖率 | ≥ 80% | 最低覆盖率要求 |
| 关键场景覆盖率 | 100% | 所有 Critical 级别场景必须有告警 |
| Warning 场景覆盖率 | ≥ 70% | Warning 场景覆盖要求 |

### 场景分类

**Critical 场景**（必须有告警覆盖）
- Pod 崩溃/终止
- Pod CrashLoopBackOff
- Pod OOM
- 服务完全不可用
- 高 5xx 率
- 级联故障检测

**Warning 场景**（推荐有告警覆盖）
- Pod 重启次数过多
- 服务部分不可用
- 高延迟
- 高错误率
- CPU/内存使用率过高
- 上游错误率/超时
- 熔断器打开

## 如何补充缺失的告警规则

### 1. 查看当前告警规则

```bash
# 查看所有 PrometheusRule
kubectl get prometheusrules -A

# 查看特定命名空间的告警规则
kubectl get prometheusrules -n monitoring

# 查看 PrometheusRule 详情
kubectl describe promethearule <name> -n monitoring
```

### 2. 生成告警规则模板

根据缺失的场景，生成相应的告警规则。以下是常见告警规则模板：

#### Pod 崩溃/终止

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: pod-down-alerts
  namespace: monitoring
spec:
  groups:
    - name: pod.rules
      rules:
        - alert: PodNotReady
          expr: |
            kube_pod_status_phase{namespace="online-boutique", phase="Running"} == 0
          for: 1m
          labels:
            severity: critical
            namespace: online-boutique
          annotations:
            summary: "Pod {{ $labels.pod }} is not ready"
            description: "Pod {{ $labels.pod }} in namespace {{ $labels.namespace }} has been in NotReady state for more than 1 minute."
```

#### 高 5xx 率

```yaml
- alert: High5xxRate
  expr: |
    sum(rate(traces_spanmetrics_calls_total{namespace="online-boutique",http_response_status_code=~"5.."}[5m])) by (service_name)
    /
    sum(rate(traces_spanmetrics_calls_total{namespace="online-boutique"}[5m])) by (service_name)
    > 0.05
  for: 2m
  labels:
    severity: critical
    namespace: online-boutique
  annotations:
    summary: "High 5xx rate on {{ $labels.service_name }}"
    description: "Service {{ $labels.service_name }} has 5xx error rate above 5% for more than 2 minutes."
```

#### 高延迟

```yaml
- alert: HighLatency
  expr: |
    histogram_quantile(0.95, sum(rate(traces_spanmetrics_duration_milliseconds_bucket{namespace="online-boutique"}[5m])) by (le, service_name)) > 1000
  for: 5m
  labels:
    severity: warning
    namespace: online-boutique
  annotations:
    summary: "High P95 latency on {{ $labels.service_name }}"
    description: "Service {{ $labels.service_name }} has P95 latency above 1s for more than 5 minutes."
```

#### Pod OOM

```yaml
- alert: PodOOMKilled
  expr: |
    kube_pod_container_status_terminated_reason{namespace="online-boutique", reason="OOMKilled"} > 0
  for: 0m
  labels:
    severity: critical
    namespace: online-boutique
  annotations:
    summary: "Pod {{ $labels.pod }} was OOM killed"
    description: "Container {{ $labels.container }} in pod {{ $labels.pod }} was terminated due to OOM."
```

### 3. 应用告警规则

```bash
# 应用 PrometheusRule
kubectl apply -f <prometheus-rule-file>.yaml

# 验证告警规则已加载
kubectl get prometheusrules -n monitoring
```

### 4. 验证告警触发

```bash
# 查询 Prometheus 中的告警规则
kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090:9090

# 在 Prometheus UI 中查询告警规则
# http://localhost:9090/rules
```

## 告警覆盖度检查自动化

为了提高效率，可以自动化告警覆盖度检查：

### 1. 自动扫描

定期或实验前自动扫描告警规则。

### 2. 自动评估

自动计算覆盖率和识别缺失。

### 3. 自动报告

自动生成检查报告。

### 4. 自动阻塞

自动阻塞告警不足的实验。

## 最佳实践

1. **定期检查告警覆盖度**，特别是在系统变更后
2. **优先补充 Critical 场景的告警规则**
3. **根据实验结果持续优化告警阈值**
4. **定期演练告警响应流程**
5. **记录告警缺失和误报，持续改进**

## 相关文档

- [混沌实验运行手册](./runbook.md)
- [告警验证指南](./alert-validation-guide.md)
- [故障排除指南](./troubleshooting.md)
