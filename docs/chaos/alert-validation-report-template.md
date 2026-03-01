# 告警验证报告模板

## 实验信息
- 实验类型: [Pod故障 / 网络延迟 / 依赖故障 / 资源耗尽 / 级联故障]
- 目标服务: [service-name]
- 开始时间: [timestamp]
- 结束时间: [timestamp]
- 持续时长: [duration]

## 预期告警
| 告警名称 | 严重级别 | 预期触发条件 |
|---------|---------|-------------|
| PodNotReady | Critical | Pod 进入 NotReady 状态 |
| HighLatency | Warning | P95 延迟 > 1s |
| High5xxRate | Critical | 5xx 错误率 > 5% |
| ServiceUnavailable | Critical | 服务完全不可用 |
| DependencyErrorRateHigh | Warning | 上游调用失败率高 |
| CircuitBreakerOpen | Warning | 熔断器打开 |
| HighCPUUsage | Warning | CPU 使用率 > 80% |
| HighMemoryUsage | Warning | 内存使用率 > 80% |
| PodOOMKilled | Critical | Pod 因内存耗尽被终止 |
| CPUThrottlingHigh | Warning | CPU 节流严重 |
| CascadeFailureDetected | Critical | 检测到级联故障 |
| SystemDegraded | Warning | 系统整体降级 |

## 实际触发的告警
| 告警名称 | 触发时间 | 恢复时间 | 持续时长 | 响应时间 | 严重级别 |
|---------|---------|---------|---------|---------|---------|
| [AlertName] | [timestamp] | [timestamp] | [duration] | [duration] | [severity] |

## 告警验证结果

### 成功触发的告警 ✅
- [告警名称]: [响应时间] 内触发，符合预期（≤[阈值]）

### 未触发的告警 ❌
- [告警名称]: [原因说明]

### 未预期触发的告警 ⚠️
- [告警名称]: [原因说明]

## 告警响应时间分析
| 告警名称 | 预期响应时间 | 实际响应时间 | 评价 |
|---------|-------------|-------------|------|
| PodNotReady | ≤30s | 5s | ✅ 优秀 |
| HighLatency | ≤2min | 1.5min | ✅ 良好 |

## 告警覆盖率
- 预期告警数: [N]
- 实际触发数: [N]
- 覆盖率: [XX]%

## 问题识别
### 告警缺失
- [告警名称]: 未触发，可能是:
  - 告警规则缺失
  - 告警阈值不合理
  - 触发条件未满足

### 告警误报
- [告警名称]: 未预期但触发了，可能是:
  - 告警阈值过低
  - 触发条件过于宽松
  - 环境噪音干扰

### 响应时间过长
- [告警名称]: 响应时间 [XX]s，超过预期 [XX]s

## 改进建议
1. [具体建议]
2. [具体建议]
3. [具体建议]

## 总结
- 告警覆盖率: [XX]% ([评价])
- 告警响应及时性: [评价]
- 整体评价: [通过 / 部分 / 失败]

## 附件
- Grafana 大盘截图: [path]
- 告警日志导出: [path]
- Prometheus 查询结果: [path]
