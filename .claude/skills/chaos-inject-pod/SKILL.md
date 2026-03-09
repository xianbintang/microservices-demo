---
name: chaos-inject-pod
description: 向指定服务注入 Pod 故障（PodKill），触发 Pod 重建，验证告警覆盖度后执行。用法：/chaos-inject-pod [service] [duration]
license: MIT
compatibility:
  claude_code: ">=1.0"
metadata:
  author: xianb
  version: 1.0.0
  generatedBy: claude-sonnet-4-6
---

# Pod 故障注入

终止指定服务的 Pod，验证 Kubernetes 自我恢复和告警触发。

## 用法

```
/chaos-inject-pod [service] [duration]
```

### 参数

- `service`: 可选，目标服务（如 `frontend`、`adservice`）。不指定则随机选择
- `duration`: 可选，实验时长（默认：2m），格式：数字+s/m/h

## 执行步骤

### 步骤 1：检查 Chaos Mesh 安装

```bash
kubectl get crd podchaos.chaos-mesh.org 2>/dev/null \
  && echo "✅ Chaos Mesh 已安装" \
  || { echo "❌ Chaos Mesh 未安装。安装命令："; \
       echo "helm repo add chaos-mesh https://charts.chaos-mesh.org"; \
       echo "helm install chaos-mesh chaos-mesh/chaos-mesh -n chaos-mesh --create-namespace --set chaosDaemon.runtime=containerd --set chaosDaemon.socketPath=/run/containerd/containerd.sock"; \
       exit 1; }
```

### 步骤 2：运行告警覆盖度检查

执行 `/chaos-check-alerts` 确认覆盖率 ≥ 80%，Critical 告警全部 ok。覆盖率不足时中止实验。

### 步骤 3：确定目标 Pod

```bash
SERVICE="<service>"  # 或从参数获取，未指定则随机选
kubectl get pods -n online-boutique -l app=$SERVICE \
  --no-headers -o custom-columns="NAME:.metadata.name,STATUS:.status.phase,READY:.status.containerStatuses[0].ready" 2>/dev/null
```

### 步骤 4：记录基准指标

```bash
kubectl exec -n monitoring prometheus-kube-prometheus-stack-prometheus-0 -- \
  wget -qO- "http://localhost:9090/api/v1/query?query=sum+by+(service_name)(rate(traces_spanmetrics_calls_total%7Bstatus_code%3D%22STATUS_CODE_ERROR%22%7D%5B2m%5D))+%2F+sum+by+(service_name)(rate(traces_spanmetrics_calls_total%5B2m%5D))+*+100" | \
  python3 -c "import json,sys; r=json.load(sys.stdin)['data']['result']; [print(f'  基准错误率 {x[\"metric\"].get(\"service_name\",\"?\")}:', float(x['value'][1] or 0), '%') for x in r if x['metric'].get('service_name') == '<service>']" 2>/dev/null
```

### 步骤 5：注入故障

生成实验 ID（格式：`pod-failure-<service>-YYYYMMDD-HHMMSS`），然后执行：

```bash
kubectl apply -f - <<EOF
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata:
  name: pod-failure-<service>-<timestamp>
  namespace: chaos-mesh
spec:
  action: pod-kill
  mode: one
  selector:
    namespaces: [online-boutique]
    labelSelectors:
      app: <service>
  duration: "<duration>"
EOF
```

### 步骤 6：确认注入状态

```bash
kubectl get podchaos -n chaos-mesh pod-failure-<service>-<timestamp> \
  -o custom-columns="NAME:.metadata.name,PHASE:.status.experiment.desiredPhase,STATUS:.status.conditions[0].type"
```

期望状态：`Injected`。

### 步骤 7：输出实验信息

```
Pod 故障注入实验
================
实验 ID: pod-failure-<service>-<timestamp>
目标服务: <service>
故障类型: PodKill
实验时长: <duration>
预期告警: ChaosPodNotReady

执行完成:
1. 基准指标已记录 ✅
2. PodChaos 已创建 ✅  (状态: Injected)
3. Pod 正在重建...

下一步:
- /chaos-monitor        — 监控实验状态
- /chaos-validate-alerts — 验证告警触发
- /chaos-validate-self-heal — 验证恢复
- /chaos-abort           — 中止实验
```

## 核心原则

**告警规则必须代码固化** — 所有 Chaos 告警规则存储于 `deploy/monitoring/alerting/chaos-testing-alerts.yaml`。

## kind 环境说明

- PodChaos `pod-kill` 在 kind 已验证可正常注入（Pod 在 6s 内被重建）
- NetworkChaos 源 Pod 延迟注入在 kind 受 ipset 限制，请使用 `/chaos-inject-network`

## 验收标准

- [x] Chaos Mesh 未安装时明确提示安装命令
- [x] 执行告警覆盖度检查（门控）
- [x] 记录基准错误率
- [x] 创建 PodChaos CRD 并确认 Injected 状态
- [x] 提供下一步操作指引
