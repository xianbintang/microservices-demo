---
name: chaos-monitor
description: 监控正在运行的混沌实验，显示实验状态、Pod 健康、实时错误率和告警。用法：/chaos-monitor [experiment-name]
license: MIT
compatibility:
  claude_code: ">=1.0"
metadata:
  author: xianb
  version: 1.0.0
  generatedBy: claude-sonnet-4-6
---

# 混沌实验监控

实时显示运行中实验的状态、目标服务 Pod 健康、Prometheus 错误率/延迟、已触发告警。

## 用法

```
/chaos-monitor [experiment-name]
```

### 参数

- `experiment-name`: 可选，指定实验名称过滤（默认：显示所有运行中实验）

## 执行步骤

### 步骤 1：检查 Chaos Mesh 安装状态

```bash
kubectl get crd podchaos.chaos-mesh.org 2>/dev/null \
  && echo "Chaos Mesh 已安装" \
  || echo "Chaos Mesh 未安装 — 无运行中实验"
```

若 Chaos Mesh 未安装，直接输出"无运行中实验"后结束。

### 步骤 2：查询运行中的实验

```bash
kubectl get podchaos,networkchaos,stresschaos --all-namespaces 2>/dev/null \
  || echo "No chaos experiments running"
```

### 步骤 3：查询目标服务 Pod 状态

根据步骤 2 中实验的 `selector.labelSelectors.app` 确定目标服务，执行：

```bash
kubectl get pods -n online-boutique -l app=<target-service> \
  --no-headers | awk '{print $1, $2, $3, $5}'
```

### 步骤 4：查询实时指标（Prometheus）

```bash
kubectl exec -n monitoring prometheus-kube-prometheus-stack-prometheus-0 -- \
  wget -qO- "http://localhost:9090/api/v1/query?query=$(python3 -c "import urllib.parse; print(urllib.parse.quote('sum by (service_name) (rate(traces_spanmetrics_calls_total{status_code=\"STATUS_CODE_ERROR\"}[1m])) / sum by (service_name) (rate(traces_spanmetrics_calls_total[1m])) * 100'))")" | \
  python3 -c "
import json,sys
data=json.load(sys.stdin)['data']['result']
print('错误率 (1m):')
for r in sorted(data, key=lambda x: float(x['value'][1] or 0), reverse=True)[:5]:
    svc=r['metric'].get('service_name','?')
    val=float(r['value'][1] or 0)
    flag='⚠️' if val>1 else ''
    print(f'  {svc}: {val:.2f}% {flag}')
" 2>/dev/null || echo "  (Prometheus 未就绪)"
```

### 步骤 5：查询已触发的 Chaos 告警

```bash
kubectl exec -n monitoring alertmanager-kube-prometheus-stack-alertmanager-0 -- \
  wget -qO- 'http://localhost:9093/api/v2/alerts?filter=chaos_test%3D%22true%22' | \
  python3 -c "
import json,sys
alerts=json.load(sys.stdin)
if not alerts:
    print('  告警: 无 Chaos 告警触发')
else:
    print(f'  告警: {len(alerts)} 条 Chaos 告警')
    for a in alerts:
        name=a['labels'].get('alertname','?')
        state=a['status']['state']
        sev=a['labels'].get('severity','?')
        print(f'    [{sev.upper()}] {name} [{state}]')
" 2>/dev/null
```

### 步骤 6：输出汇总

整合以上数据，格式：

```
混沌实验监控
============
Chaos Mesh: 已安装 / 未安装

运行中实验: N 个
  <实验名> (类型 / 目标 / 状态)

Pod 状态:
  <service>: N/N Ready

实时指标 (1m):
  错误率: X%
  告警: X 条

访问地址:
  Grafana: http://localhost:3000
```

## 核心原则

**告警规则必须代码固化** — 所有告警规则必须存储在 `deploy/monitoring/alerting/`。

## 验收标准

- [x] Chaos Mesh 未安装时优雅输出"无运行中实验"，不报错
- [x] 正确查询所有类型实验（PodChaos/NetworkChaos/StressChaos）
- [x] 显示目标 Pod 实时状态
- [x] 显示 Prometheus 错误率（使用 spanmetrics）
- [x] 显示 Alertmanager 中 Chaos 告警
