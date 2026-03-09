---
description: 向目标服务注入网络故障（partition 隔离），kind 环境下使用目标 Pod 模式绕过 ipset 限制。用法：/chaos-inject-network [service] [latency] [duration]
---

# 网络故障注入

通过 NetworkChaos 注入网络隔离或延迟。kind 环境下源 Pod 延迟注入受 ipset 限制，自动使用 `partition` 模式隔离目标 Pod。

## 用法

```
/chaos-inject-network [service] [latency] [duration]
```

### 参数

- `service`: 目标服务（如 `recommendationservice`），或 `redis-cart` 测试依赖隔离
- `latency`: 可选，延迟量（默认：500ms）——**kind 环境下无效，自动转为 partition 模式**
- `duration`: 可选，实验时长（默认：3m）

## kind 环境已知限制

| 模式 | 效果 |
|------|------|
| 源 Pod delay（`action: delay`）| ❌ 失败：chaos-daemon 报 `unable to flush ip sets` |
| 目标 Pod partition（`action: partition`）| ✅ 成功：已验证 redis-cart 隔离可触发 cartservice 错误率上升 |

在 kind 以外的生产 Kubernetes 集群上，`action: delay` 可正常注入。

## 执行步骤

### 步骤 1：检查 Chaos Mesh 安装

```bash
kubectl get crd networkchaos.chaos-mesh.org 2>/dev/null \
  && echo "✅ Chaos Mesh 已安装" \
  || { echo "❌ Chaos Mesh 未安装。安装命令："; \
       echo "helm repo add chaos-mesh https://charts.chaos-mesh.org"; \
       echo "helm install chaos-mesh chaos-mesh/chaos-mesh -n chaos-mesh --create-namespace --set chaosDaemon.runtime=containerd --set chaosDaemon.socketPath=/run/containerd/containerd.sock"; \
       exit 1; }
```

### 步骤 2：运行告警覆盖度检查

执行 `/chaos-check-alerts`，覆盖率 ≥ 80% 才继续。

### 步骤 3：检测 kind 环境

```bash
kubectl get node -o jsonpath='{.items[0].metadata.name}' | grep -q "kind" \
  && echo "⚠️  kind 环境: 自动切换为 partition 模式（目标 Pod 隔离）" \
  || echo "✅ 非 kind 环境: 可使用 delay 模式"
```

### 步骤 4：记录基准指标

```bash
kubectl exec -n monitoring prometheus-kube-prometheus-stack-prometheus-0 -- \
  wget -qO- "http://localhost:9090/api/v1/query?query=histogram_quantile(0.95%2Csum+by+(service_name%2Cle)(rate(traces_spanmetrics_duration_milliseconds_bucket%5B2m%5D)))" | \
  python3 -c "import json,sys; r=json.load(sys.stdin)['data']['result']; print('基准 P95 延迟:'); [print(f'  {x[\"metric\"].get(\"service_name\",\"?\")}: {float(x[\"value\"][1]):.0f} ms') for x in sorted(r,key=lambda x:float(x['value'][1]),reverse=True)[:5]]" 2>/dev/null
```

### 步骤 5：注入故障

**kind 环境（partition 模式）：**

```bash
kubectl apply -f - <<EOF
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: network-partition-<service>-<timestamp>
  namespace: chaos-mesh
spec:
  action: partition
  mode: one
  selector:
    namespaces: [online-boutique]
    labelSelectors:
      app: <service>
  direction: both
  duration: "<duration>"
EOF
```

**非 kind 环境（delay 模式）：**

```bash
kubectl apply -f - <<EOF
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: network-delay-<service>-<timestamp>
  namespace: chaos-mesh
spec:
  action: delay
  mode: one
  selector:
    namespaces: [online-boutique]
    labelSelectors:
      app: <service>
  delay:
    latency: "<latency>"
    correlation: "100"
    jitter: "0ms"
  duration: "<duration>"
EOF
```

### 步骤 6：确认注入状态

```bash
kubectl get networkchaos -n chaos-mesh \
  -o custom-columns="NAME:.metadata.name,PHASE:.status.experiment.desiredPhase"
```

期望状态：`Injected`（partition 模式）。

## 核心原则

**告警规则必须代码固化** — 所有告警规则存储于 `deploy/monitoring/alerting/chaos-testing-alerts.yaml`。

## 验收标准

- [x] Chaos Mesh 未安装时明确提示安装命令
- [x] kind 环境自动检测并切换 partition 模式
- [x] 注入前记录基准 P95 延迟
- [x] 创建 NetworkChaos CRD 并确认 Injected 状态
