---
name: chaos-inject-resource
description: 向目标服务注入 CPU 或内存资源压力（StressChaos），触发资源告警。用法：/chaos-inject-resource [service] [type] [value] [duration]
license: MIT
compatibility:
  claude_code: ">=1.0"
metadata:
  author: xianb
  version: 1.0.0
  generatedBy: claude-sonnet-4-6
---

# 资源耗尽注入

通过 StressChaos 对目标 Pod 施加 CPU 或内存压力，验证资源相关告警（ChaosHighCPUUsage、ChaosHighMemoryUsage、ChaosOOMKilled）。

## 用法

```
/chaos-inject-resource [service] [type] [value] [duration]
```

### 参数

- `service`: 目标服务（如 `checkoutservice`）
- `type`: `cpu` 或 `memory`
- `value`: 压力值（CPU：load 百分比如 `80`；内存：MiB 如 `512`）
- `duration`: 可选，实验时长（默认：5m）

## 前置要求

StressChaos 需要 chaos-controller-manager 启用 `SECURITY_MODE=true`（mTLS 证书正确配置）。若遇到 `error reading server preface: EOF`，检查：

```bash
kubectl get deployment chaos-controller-manager -n chaos-mesh \
  -o jsonpath='{.spec.template.spec.containers[0].env}' | grep -o SECURITY_MODE
```

## 执行步骤

### 步骤 1：检查 Chaos Mesh 安装

```bash
kubectl get crd stresschaos.chaos-mesh.org 2>/dev/null \
  && echo "✅ Chaos Mesh 已安装" \
  || { echo "❌ Chaos Mesh 未安装。安装命令："; \
       echo "helm repo add chaos-mesh https://charts.chaos-mesh.org"; \
       echo "helm install chaos-mesh chaos-mesh/chaos-mesh -n chaos-mesh --create-namespace --set chaosDaemon.runtime=containerd --set chaosDaemon.socketPath=/run/containerd/containerd.sock"; \
       exit 1; }
```

### 步骤 2：运行告警覆盖度检查

执行 `/chaos-check-alerts`，覆盖率 ≥ 80% 才继续。

### 步骤 3：记录基准资源使用

```bash
kubectl exec -n monitoring prometheus-kube-prometheus-stack-prometheus-0 -- \
  wget -qO- "http://localhost:9090/api/v1/query?query=sum+by+(pod)(rate(container_cpu_usage_seconds_total%7Bnamespace%3D%22online-boutique%22%2Ccontainer%3D%22<service>%22%7D%5B2m%5D))*1000" | \
  python3 -c "import json,sys; r=json.load(sys.stdin)['data']['result']; [print(f'  基准 CPU: {x[\"metric\"].get(\"pod\",\"?\")}: {float(x[\"value\"][1]):.1f} mCPU') for x in r]" 2>/dev/null

kubectl exec -n monitoring prometheus-kube-prometheus-stack-prometheus-0 -- \
  wget -qO- "http://localhost:9090/api/v1/query?query=sum+by+(pod)(container_memory_working_set_bytes%7Bnamespace%3D%22online-boutique%22%2Ccontainer%3D%22<service>%22%7D)%2F1024%2F1024" | \
  python3 -c "import json,sys; r=json.load(sys.stdin)['data']['result']; [print(f'  基准内存: {x[\"metric\"].get(\"pod\",\"?\")}: {float(x[\"value\"][1]):.0f} MiB') for x in r]" 2>/dev/null
```

### 步骤 4：注入故障

**CPU 压力：**

```bash
kubectl apply -f - <<EOF
apiVersion: chaos-mesh.org/v1alpha1
kind: StressChaos
metadata:
  name: stress-cpu-<service>-<timestamp>
  namespace: chaos-mesh
spec:
  mode: one
  selector:
    namespaces: [online-boutique]
    labelSelectors:
      app: <service>
  stressors:
    cpu:
      workers: 2
      load: <value>
  duration: "<duration>"
EOF
```

**内存压力：**

```bash
kubectl apply -f - <<EOF
apiVersion: chaos-mesh.org/v1alpha1
kind: StressChaos
metadata:
  name: stress-memory-<service>-<timestamp>
  namespace: chaos-mesh
spec:
  mode: one
  selector:
    namespaces: [online-boutique]
    labelSelectors:
      app: <service>
  stressors:
    memory:
      workers: 1
      size: "<value>MiB"
  duration: "<duration>"
EOF
```

### 步骤 5：确认注入状态

```bash
kubectl get stresschaos -n chaos-mesh \
  -o custom-columns="NAME:.metadata.name,PHASE:.status.experiment.desiredPhase"
```

期望状态：`Injected`。

## 预期告警

| 故障类型 | 预期告警 | 触发阈值 |
|---------|---------|---------|
| CPU | ChaosHighCPUUsage | > 0.5 cores 持续 1m |
| CPU | ChaosCPUThrottling | 节流 > 50% 持续 1m |
| 内存 | ChaosHighMemoryUsage | > 400MiB 持续 1m |
| 内存超限 | ChaosOOMKilled | 容器被 OOM 终止 |

## 核心原则

**告警规则必须代码固化** — 告警规则存储于 `deploy/monitoring/alerting/chaos-testing-alerts.yaml`。

## 验收标准

- [x] Chaos Mesh 未安装时明确提示安装命令
- [x] 记录基准 CPU/内存使用量
- [x] 根据 type 参数生成正确的 StressChaos YAML
- [x] 确认 Injected 状态
