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

检查 `deploy/monitoring/alerting/chaos-testing-alerts.yaml` 中以下告警规则是否存在且在 Prometheus 中状态为 `ok`：

| 类别 | 关键场景 | 实际告警名称 | 严重级别 |
|------|---------|------------|---------|
| Pod 状态 | Pod 崩溃/终止 | ChaosPodDown | Critical |
| Pod 状态 | Pod 未就绪 | ChaosPodNotReady | Critical |
| Pod 状态 | Pod 重启次数过多 | ChaosPodRestart | Warning |
| Pod 状态 | Pod CrashLoopBackOff | ChaosPodCrashLoopBackOff | Critical |
| Pod 状态 | Pod OOM 终止 | ChaosOOMKilled | Critical |
| 服务可用性 | 服务无就绪 Pod | ChaosServiceDown | Critical |
| 性能指标 | 高延迟（P95 > 2s） | ChaosHighLatency | Warning |
| 性能指标 | 高错误率（> 10%） | ChaosHighErrorRate | Critical |
| 资源使用 | CPU 节流严重（> 50%） | ChaosCPUThrottling | Warning |
| 资源使用 | CPU 使用过高（> 0.5 core） | ChaosHighCPUUsage | Warning |
| 资源使用 | 内存使用过高（> 400MiB） | ChaosHighMemoryUsage | Warning |
| 熔断器 | 熔断器打开 | N/A（Online Boutique 未实现熔断器） | - |

**检查方式**：
```bash
kubectl exec -n monitoring $(kubectl get pod -n monitoring -l app=prometheus -o jsonpath='{.items[0].metadata.name}') \
  -- wget -qO- 'http://localhost:9090/api/v1/rules?type=alert' | \
  python3 -c "
import sys, json
data = json.load(sys.stdin)
chaos_alerts = {r['name']: r['health'] for g in data['data']['groups'] for r in g['rules'] if r['name'].startswith('Chaos')}
required = ['ChaosPodDown','ChaosPodNotReady','ChaosPodRestart','ChaosPodCrashLoopBackOff',
            'ChaosOOMKilled','ChaosServiceDown','ChaosHighLatency','ChaosHighErrorRate',
            'ChaosCPUThrottling','ChaosHighCPUUsage','ChaosHighMemoryUsage']
covered = [a for a in required if chaos_alerts.get(a) == 'ok']
missing = [a for a in required if a not in covered]
print(f'覆盖: {len(covered)}/{len(required)} ({len(covered)/len(required)*100:.0f}%)')
for a in covered: print(f'  ✅ {a}')
for a in missing: print(f'  ❌ {a} (缺失)')
print('允许执行实验' if len(covered)/len(required) >= 0.8 else '阻塞: 告警覆盖率不足 80%')
"
```

## 覆盖率阈值

- **总体覆盖率**: ≥ 80%（11 个 required 中至少 9 个 ok）
- **Critical 场景**: ChaosPodDown、ChaosPodNotReady、ChaosPodCrashLoopBackOff、ChaosOOMKilled、ChaosServiceDown、ChaosHighErrorRate 必须全部覆盖

## 输出示例

```
告警覆盖度检查报告
====================
检查时间: 2026-03-02 10:00:00

覆盖: 11/11 (100%)
  ✅ ChaosPodDown
  ✅ ChaosPodNotReady
  ✅ ChaosPodRestart
  ✅ ChaosPodCrashLoopBackOff
  ✅ ChaosOOMKilled
  ✅ ChaosServiceDown
  ✅ ChaosHighLatency
  ✅ ChaosHighErrorRate
  ✅ ChaosCPUThrottling
  ✅ ChaosHighCPUUsage
  ✅ ChaosHighMemoryUsage
允许执行实验
```

## 验收标准

- [x] 能正确扫描当前告警规则
- [x] 能准确对比关键场景清单
- [x] 能计算正确的覆盖率
- [x] 能生成可读的检查报告
- [x] 能正确判断是否允许执行实验

## 相关文档

- [告警覆盖度检查指南](../../docs/chaos/alert-coverage-check-guide.md)
- [混沌实验运行手册](../../docs/chaos/runbook.md)
