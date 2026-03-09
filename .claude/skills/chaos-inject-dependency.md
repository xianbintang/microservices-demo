---
description: 模拟服务依赖不可用，通过 NetworkChaos partition 隔离依赖服务（如 redis-cart），触发上游服务错误率上升。用法：/chaos-inject-dependency [service] [dependency] [duration]
---

# 依赖故障注入

通过 NetworkChaos `partition` 隔离依赖服务，使上游服务无法访问依赖，验证错误处理和告警。

## 用法

```
/chaos-inject-dependency [service] [dependency] [duration]
```

### 参数

- `service`: 上游服务（如 `cartservice`）
- `dependency`: 依赖服务（如 `redis-cart`、`productcatalogservice`）
- `duration`: 可选，实验时长（默认：3m）

## 实现说明

- Online Boutique **未实现熔断器**（Circuit Breaker），依赖不可用直接导致请求错误
- Redis (`redis-cart`) 在 `online-boutique` namespace，selector `app: redis-cart`
- 通过隔离**依赖方**（而非上游服务），使上游无法访问依赖

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

### 步骤 3：确认依赖服务存在

```bash
DEPENDENCY="<dependency>"  # 如 redis-cart
kubectl get pod -n online-boutique -l app=$DEPENDENCY \
  --no-headers | awk '{print "  依赖 Pod:", $1, $3}'
```

### 步骤 4：记录基准指标

```bash
kubectl exec -n monitoring prometheus-kube-prometheus-stack-prometheus-0 -- \
  wget -qO- "http://localhost:9090/api/v1/query?query=sum+by+(service_name)(rate(traces_spanmetrics_calls_total%7Bstatus_code%3D%22STATUS_CODE_ERROR%22%2Cservice_name%3D%22<service>%22%7D%5B2m%5D))+%2F+sum+by+(service_name)(rate(traces_spanmetrics_calls_total%7Bservice_name%3D%22<service>%22%7D%5B2m%5D))+*+100" | \
  python3 -c "import json,sys; r=json.load(sys.stdin)['data']['result']; print('基准错误率:', float(r[0]['value'][1]) if r else 0, '%')" 2>/dev/null
```

### 步骤 5：注入故障（partition 模式隔离依赖）

```bash
kubectl apply -f - <<EOF
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: dependency-<service>-<dependency>-<timestamp>
  namespace: chaos-mesh
spec:
  action: partition
  mode: one
  selector:
    namespaces: [online-boutique]
    labelSelectors:
      app: <dependency>
  direction: both
  duration: "<duration>"
EOF
```

### 步骤 6：确认注入状态

```bash
kubectl get networkchaos -n chaos-mesh \
  -o custom-columns="NAME:.metadata.name,PHASE:.status.experiment.desiredPhase"
```

## 预期告警

- `ChaosHighErrorRate` (Critical) — 上游服务错误率 > 10%
- `ChaosPodRestart` (Warning) — 依赖不可用可能导致 Pod 崩溃重启

## 核心原则

**告警规则必须代码固化** — 告警规则存储于 `deploy/monitoring/alerting/chaos-testing-alerts.yaml`。

## 验收标准

- [x] Chaos Mesh 未安装时明确提示安装命令
- [x] 确认依赖服务 Pod 存在
- [x] 记录上游服务基准错误率
- [x] 通过 partition 模式隔离依赖（绕过 kind ipset 限制）
- [x] 确认 Injected 状态
