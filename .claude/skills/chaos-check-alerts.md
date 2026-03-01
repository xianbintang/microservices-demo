# 告警覆盖度检查 skill

执行告警覆盖度检查，确保关键场景都有告警覆盖。

## 核心原则

**告警规则必须代码固化** - 所有告警规则必须存储在代码仓库中（`deploy/monitoring/alerting/`），禁止使用临时 `kubectl apply` 命令创建告警规则。任何告警规则的变更必须通过代码审查和版本控制。

## 用法

```
/chaos-check-alerts [namespace]
```

### 参数

- `namespace`: 可选，指定要检查的命名空间（默认：online-boutique）

## 执行流程

1. 扫描 Prometheus 中的告警规则
2. 对比关键告警场景清单
3. 计算告警覆盖率
4. 生成覆盖度报告
5. 评估是否允许执行混沌实验

## 关键告警场景清单

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

## 覆盖率阈值

- **总体覆盖率**: ≥ 80%
- **关键场景覆盖率**: 100% (所有 Critical 级别场景必须有告警覆盖)

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

## 验收标准

- [ ] 能正确扫描当前告警规则
- [ ] 能准确对比关键场景清单
- [ ] 能计算正确的覆盖率
- [ ] 能生成可读的检查报告
- [ ] 能正确判断是否允许执行实验

## 相关文档

- [告警覆盖度检查指南](../../docs/chaos/alert-coverage-check-guide.md)
- [混沌实验运行手册](../../docs/chaos/runbook.md)
