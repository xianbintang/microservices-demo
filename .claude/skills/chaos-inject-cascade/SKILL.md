---
name: chaos-inject-cascade
description: 同时注入多个故障（PodKill + NetworkPartition + StressChaos），验证级联故障场景下的告警和恢复能力。用法：/chaos-inject-cascade [config]
license: MIT
compatibility:
  claude_code: ">=1.0"
metadata:
  author: xianb
  version: 1.0.0
  generatedBy: claude-sonnet-4-6
---

# 级联故障注入

同时触发多个故障，模拟真实生产级联失效场景，验证系统在复合故障下的告警覆盖和自我恢复能力。

## 用法

```
/chaos-inject-cascade [config]
```

### 参数

- `config`: 配置名（默认：`default`），对应 `.claude/skills/chaos-inject-cascade/cascade-failure.yaml`

## 默认配置（`default`）

`.claude/skills/chaos-inject-cascade/cascade-failure.yaml` 包含 3 个同时触发的故障：

| # | 服务 | 故障类型 | 时长 | kind 支持 |
|---|------|---------|------|----------|
| 1 | adservice | PodChaos pod-kill | 2m | ✅ |
| 2 | recommendationservice | NetworkChaos partition | 3m | ✅ |
| 3 | checkoutservice | StressChaos memory 512MiB | 4m | ✅ |

## 执行步骤

### 步骤 1：检查 Chaos Mesh 安装

```bash
kubectl get crd podchaos.chaos-mesh.org networkchaos.chaos-mesh.org stresschaos.chaos-mesh.org 2>/dev/null \
  && echo "✅ Chaos Mesh 全部 CRD 已安装" \
  || { echo "❌ Chaos Mesh 未安装。安装命令："; \
       echo "helm repo add chaos-mesh https://charts.chaos-mesh.org"; \
       echo "helm install chaos-mesh chaos-mesh/chaos-mesh -n chaos-mesh --create-namespace --set chaosDaemon.runtime=containerd --set chaosDaemon.socketPath=/run/containerd/containerd.sock"; \
       exit 1; }
```

### 步骤 2：运行告警覆盖度检查

执行 `/chaos-check-alerts`，覆盖率 ≥ 80% 才继续。

### 步骤 3：记录基准指标

```bash
kubectl get pods -n online-boutique --no-headers | awk '{print $1, $2, $3}'
echo "---"
kubectl exec -n monitoring prometheus-kube-prometheus-stack-prometheus-0 -- \
  wget -qO- "http://localhost:9090/api/v1/query?query=sum+by+(service_name)(rate(traces_spanmetrics_calls_total%5B2m%5D))" | \
  python3 -c "import json,sys; r=json.load(sys.stdin)['data']['result']; print('基准 RPS:'); [print(f'  {x[\"metric\"].get(\"service_name\",\"?\")}: {float(x[\"value\"][1]):.3f}') for x in r]" 2>/dev/null
```

### 步骤 4：应用级联故障配置

```bash
kubectl apply -f .claude/skills/chaos-inject-cascade/cascade-failure.yaml
```

### 步骤 5：确认各故障注入状态

```bash
echo "=== PodChaos ===" && kubectl get podchaos -n chaos-mesh \
  -o custom-columns="NAME:.metadata.name,PHASE:.status.experiment.desiredPhase" 2>/dev/null || echo "  (无)"
echo "=== NetworkChaos ===" && kubectl get networkchaos -n chaos-mesh \
  -o custom-columns="NAME:.metadata.name,PHASE:.status.experiment.desiredPhase" 2>/dev/null || echo "  (无)"
echo "=== StressChaos ===" && kubectl get stresschaos -n chaos-mesh \
  -o custom-columns="NAME:.metadata.name,PHASE:.status.experiment.desiredPhase" 2>/dev/null || echo "  (无)"
```

期望：PodChaos `Injected`，NetworkChaos `Injected`，StressChaos `Injected`。

### 步骤 6：输出实验信息

```
级联故障注入实验
================
实验 ID: cascade-default-<timestamp>
配置: default (.claude/skills/chaos-inject-cascade/cascade-failure.yaml)
故障数量: 3
最长时长: 4m

各故障状态:
  cascade-pod-failure-adservice:          Injected ✅
  cascade-network-partition-recommend:    Injected ✅
  cascade-memory-stress-checkout:         Injected ✅

预期告警:
  ChaosPodNotReady (adservice)
  ChaosHighMemoryUsage (checkoutservice)

下一步:
  /chaos-monitor         — 监控实验状态
  /chaos-validate-alerts  — 验证告警触发
  /chaos-abort            — 中止全部实验
```

## 核心原则

**告警规则必须代码固化** — 级联实验的告警规则存储于 `deploy/monitoring/alerting/chaos-testing-alerts.yaml`。

## 验收标准

- [x] Chaos Mesh 未安装时明确提示安装命令
- [x] 应用 `.claude/skills/chaos-inject-cascade/cascade-failure.yaml` 配置文件
- [x] 分类显示各 CRD 注入状态
- [x] 提供下一步操作指引
