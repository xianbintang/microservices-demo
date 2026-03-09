---
name: chaos-abort
description: 中止正在运行的混沌实验，立即删除所有 Chaos CRD 并验证资源清理完成。用法：/chaos-abort [experiment-id]
license: MIT
compatibility:
  claude_code: ">=1.0"
metadata:
  author: xianb
  version: 1.0.0
  generatedBy: claude-sonnet-4-6
---

# 中止混沌实验

立即中止指定或所有运行中的混沌实验，删除 Chaos Mesh CRD，验证故障已移除。

## 用法

```
/chaos-abort [experiment-id]
```

### 参数

- `experiment-id`: 可选，指定实验名称（如 `pod-failure-frontend-20260301-100000`）。不指定则中止所有运行中实验。

## 执行步骤

### 步骤 1：检查 Chaos Mesh 安装

```bash
kubectl get crd podchaos.chaos-mesh.org 2>/dev/null \
  && echo "Chaos Mesh 已安装" \
  || { echo "Chaos Mesh 未安装，无实验可中止"; exit 0; }
```

### 步骤 2：查询运行中的实验

```bash
kubectl get podchaos,networkchaos,stresschaos --all-namespaces 2>/dev/null
```

若无运行中实验，输出提示后结束。

### 步骤 3：执行中止

**指定实验 ID：**

```bash
# 根据实验类型选择对应 CRD 类型（podchaos / networkchaos / stresschaos）
EXPERIMENT_ID="<experiment-id>"
NAMESPACE="chaos-mesh"

# 尝试各类型
kubectl delete podchaos    "$EXPERIMENT_ID" -n "$NAMESPACE" 2>/dev/null && echo "✅ PodChaos 已删除"
kubectl delete networkchaos "$EXPERIMENT_ID" -n "$NAMESPACE" 2>/dev/null && echo "✅ NetworkChaos 已删除"
kubectl delete stresschaos  "$EXPERIMENT_ID" -n "$NAMESPACE" 2>/dev/null && echo "✅ StressChaos 已删除"
```

**中止所有实验：**

```bash
kubectl delete podchaos    --all -n chaos-mesh 2>/dev/null; echo "PodChaos 已清理"
kubectl delete networkchaos --all -n chaos-mesh 2>/dev/null; echo "NetworkChaos 已清理"
kubectl delete stresschaos  --all -n chaos-mesh 2>/dev/null; echo "StressChaos 已清理"
```

### 步骤 4：验证清理完成

```bash
kubectl get podchaos,networkchaos,stresschaos --all-namespaces 2>/dev/null \
  | grep -v "^No resources" \
  && echo "⚠️  仍有残留实验资源" \
  || echo "✅ 所有实验资源已清理"
```

### 步骤 5：确认目标 Pod 恢复正常

```bash
kubectl get pods -n online-boutique --no-headers \
  | awk '$3 != "Running" && $3 != "Completed" {print "⚠️ 异常 Pod:", $1, $3}'
kubectl get pods -n online-boutique --no-headers \
  | awk 'BEGIN{ok=0;total=0} {total++; if($3=="Running") ok++} END{print "Pod 状态:", ok"/"total, "Running"}'
```

## 核心原则

**告警规则必须代码固化** — 中止实验不影响告警规则，告警规则始终保留在 `deploy/monitoring/alerting/chaos-testing-alerts.yaml`。

## 验收标准

- [x] Chaos Mesh 未安装时优雅退出，不报错
- [x] 支持指定实验 ID 或中止全部
- [x] 中止后验证无残留 CRD 资源
- [x] 验证目标 Pod 恢复 Running 状态
