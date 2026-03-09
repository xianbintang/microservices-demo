---
name: chaos-validate-alerts
description: 验证混沌实验期间 Chaos 告警是否正确触发，通过 Alertmanager API 查询实际触发告警并与预期对比。用法：/chaos-validate-alerts [experiment-id]
license: MIT
compatibility:
  claude_code: ">=1.0"
metadata:
  author: xianb
  version: 1.0.0
  generatedBy: claude-sonnet-4-6
---

# 告警验证

查询 Alertmanager 中 `chaos_test="true"` 标签的告警，对比实验预期告警清单，生成告警验证报告。

## 用法

```
/chaos-validate-alerts [experiment-id]
```

### 参数

- `experiment-id`: 可选，用于报告标题（默认：显示最近实验）

## 执行步骤

### 步骤 1：查询当前触发的 Chaos 告警

```bash
kubectl exec -n monitoring alertmanager-kube-prometheus-stack-alertmanager-0 -- \
  wget -qO- 'http://localhost:9093/api/v2/alerts?filter=chaos_test%3D%22true%22' | \
  python3 -c "
import json, sys
alerts = json.load(sys.stdin)
print(f'Chaos 告警数量: {len(alerts)}')
for a in alerts:
    name     = a['labels'].get('alertname', '?')
    state    = a['status']['state']
    sev      = a['labels'].get('severity', '?').upper()
    ns       = a['labels'].get('namespace', a['labels'].get('pod', '?'))
    started  = a.get('startsAt', '?')[:19]
    print(f'  [{sev}] {name} [{state}] — {ns} (since {started})')
"
```

### 步骤 2：查询 Prometheus 中 Chaos 告警历史

```bash
kubectl exec -n monitoring prometheus-kube-prometheus-stack-prometheus-0 -- \
  wget -qO- 'http://localhost:9090/api/v1/alerts' | \
  python3 -c "
import json, sys
data = json.load(sys.stdin)['data']['alerts']
chaos = [a for a in data if a['labels'].get('alertname','').startswith('Chaos')]
print(f'Prometheus 中 Chaos 告警: {len(chaos)} 条')
for a in chaos:
    name  = a['labels']['alertname']
    state = a['state']
    sev   = a['labels'].get('severity','?')
    print(f'  [{sev}] {name} [{state}]')
"
```

### 步骤 3：对比预期告警

根据实验类型，预期告警如下（从注入 skill 的输出中获取）：

| 实验类型 | 预期告警 |
|---------|---------|
| Pod 故障 | ChaosPodNotReady, (ChaosPodDown 多副本时) |
| 网络隔离 | ChaosHighErrorRate, ChaosPodRestart |
| 资源耗尽 CPU | ChaosHighCPUUsage, ChaosCPUThrottling |
| 资源耗尽内存 | ChaosHighMemoryUsage, (ChaosOOMKilled 超限时) |
| 级联故障 | ChaosPodNotReady + ChaosHighMemoryUsage 组合 |

### 步骤 4：生成验证报告

输出格式：
```
告警验证报告
============
实验 ID: <id>

触发的 Chaos 告警:
  [CRITICAL] ChaosPodNotReady [firing] — online-boutique/frontend-xxx (since 2026-03-09T...)

验证结果:
  ✅ ChaosPodNotReady: 已触发
  ❌ ChaosServiceDown: 未触发（单副本重建速度快，未满足"无就绪 Pod"条件）

覆盖率: 1/2 (50%) ⚠️

改进建议:
  - 单副本 Pod Kill 实验移除 ChaosServiceDown 预期（需多副本同时不可用）
  - 或将 Deployment replicas 设为 2 以验证 ServiceDown 场景
  代码路径: helm-chart/templates/ 或 deploy/kind/values-kind.yaml
```

## 核心原则

**告警规则必须代码固化** — 改进建议必须指向具体文件：`deploy/monitoring/alerting/chaos-testing-alerts.yaml`。

## 验收标准

- [x] 使用 Alertmanager API 查询 `chaos_test="true"` 标签的告警（不依赖 Chaos Mesh）
- [x] 使用 Prometheus API 补充查询告警历史
- [x] 对比预期告警清单，给出 ✅/❌ 结论
- [x] 计算覆盖率并给出改进建议（指向代码路径）
