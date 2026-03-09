---
name: chaos-check-alerts
description: 检查 Chaos 告警覆盖度，验证 11 条关键 Chaos* 告警规则在 Prometheus 中均已加载且状态 ok。混沌实验前置门控。用法：/chaos-check-alerts
license: MIT
compatibility:
  claude_code: ">=1.0"
metadata:
  author: xianb
  version: 1.0.0
  generatedBy: claude-sonnet-4-6
---

# 告警覆盖度检查

执行混沌实验前置门控：确认 11 条 Chaos 告警规则已加载且状态为 `ok`，覆盖率 ≥ 80% 才允许执行实验。

## 用法

```
/chaos-check-alerts
```

## 执行步骤

### 步骤 1：确认 PrometheusRule 已应用

```bash
kubectl get prometheusrule chaos-testing-alerts -n monitoring 2>/dev/null \
  && echo "PrometheusRule 已存在" \
  || kubectl apply -f deploy/monitoring/alerting/chaos-testing-alerts.yaml
```

### 步骤 2：查询 Prometheus 告警规则状态

```bash
kubectl exec -n monitoring prometheus-kube-prometheus-stack-prometheus-0 -- \
  wget -qO- 'http://localhost:9090/api/v1/rules?type=alert' | \
  python3 -c "
import sys, json
data = json.load(sys.stdin)
chaos_alerts = {r['name']: r['health']
                for g in data['data']['groups']
                for r in g['rules']
                if r['name'].startswith('Chaos')}
required = ['ChaosPodDown','ChaosPodNotReady','ChaosPodRestart','ChaosPodCrashLoopBackOff',
            'ChaosOOMKilled','ChaosServiceDown','ChaosHighLatency','ChaosHighErrorRate',
            'ChaosCPUThrottling','ChaosHighCPUUsage','ChaosHighMemoryUsage']
critical = ['ChaosPodDown','ChaosPodNotReady','ChaosPodCrashLoopBackOff',
            'ChaosOOMKilled','ChaosServiceDown','ChaosHighErrorRate']
covered  = [a for a in required if chaos_alerts.get(a) == 'ok']
missing  = [a for a in required if a not in covered]
crit_missing = [a for a in critical if a not in covered]
rate = len(covered)/len(required)
print('告警覆盖度检查报告')
print('='*40)
print(f'覆盖: {len(covered)}/{len(required)} ({rate*100:.0f}%)')
for a in covered:  print(f'  ✅ {a}')
for a in missing:  print(f'  ❌ {a} (缺失)')
print()
if crit_missing:
    print(f'🔴 阻塞: Critical 告警缺失 {crit_missing}')
elif rate < 0.8:
    print(f'🔴 阻塞: 覆盖率 {rate*100:.0f}% < 80%，禁止执行实验')
else:
    print('✅ 允许执行混沌实验')
"
```

### 步骤 3：输出覆盖率结论

- 覆盖率 ≥ 80% 且所有 Critical 告警 ok → **允许执行实验**
- 否则 → **阻塞**，需先修复告警规则（`deploy/monitoring/alerting/chaos-testing-alerts.yaml`）

## 关键告警清单

| 告警名称 | 严重级别 | 说明 |
|---------|---------|------|
| ChaosPodDown | Critical | Pod 崩溃/终止 |
| ChaosPodNotReady | Critical | Pod 未就绪 |
| ChaosPodRestart | Warning | Pod 重启过多 |
| ChaosPodCrashLoopBackOff | Critical | CrashLoopBackOff |
| ChaosOOMKilled | Critical | OOM 终止 |
| ChaosServiceDown | Critical | 服务无就绪 Pod |
| ChaosHighLatency | Warning | P95 > 2s |
| ChaosHighErrorRate | Critical | 错误率 > 10% |
| ChaosCPUThrottling | Warning | CPU 节流 > 50% |
| ChaosHighCPUUsage | Warning | CPU > 0.5 cores |
| ChaosHighMemoryUsage | Warning | 内存 > 400MiB |

## 核心原则

**告警规则必须代码固化** — 所有 Chaos 告警规则存储于 `deploy/monitoring/alerting/chaos-testing-alerts.yaml`，禁止使用临时 `kubectl apply` 直接创建告警规则绕过版本控制。

## 验收标准

- [x] 自动检查并补充应用 PrometheusRule（幂等）
- [x] 正确查询 Prometheus 中所有 Chaos* 告警规则状态
- [x] 计算覆盖率并给出允许/阻塞结论
- [x] Critical 告警缺失时明确阻塞
