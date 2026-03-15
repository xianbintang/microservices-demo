---
name: mitigation-delete-target-pod
description: 执行止损动作：删除单个目标 Pod（默认 service=redis-cart、namespace=online-boutique）。支持显式 pod 或按 service 自动解析。用法：/mitigation-delete-target-pod [pod=<pod-name>] [service=redis-cart] [namespace=online-boutique] [incident_id=<id>] [fault_id=<id>]
license: MIT
compatibility:
  claude_code: ">=1.0"
metadata:
  author: zxx
  version: 1.0.0
  generatedBy: claude-sonnet-4-6
---

# 删除目标 Pod 止损 Skill（原子动作）

用于高 CPU 等实例级异常场景下，执行**单个 Pod 删除**。

> Shell 兼容要求：执行命令时必须使用 POSIX 兼容写法，避免 `mapfile/readarray/process substitution`（macOS 默认 bash 3.2 不支持），并在读到 Pod/Deployment 名称后先去除首尾空白再使用。

> 建议：优先用 `while IFS= read -r line` + `jsonpath` 换行输出解析列表，避免 `set -- $(...)` 带来的空白字符污染。

> 出错处理：
> - 解析阶段失败（无法唯一定位）→ 立即失败并给出下一步提示；
> - 执行阶段失败（delete/rollout）→ 输出明确错误，不做隐式重试；
> - 禁止因为兼容性问题反复尝试多轮不同脚本。

> 执行器建议：优先在 `bash -lc` 中执行一段完整脚本，避免外层 shell（zsh）行为差异。

示例（仅说明兼容写法，不是完整流程）：

```bash
PODS="$(kubectl -n "$NAMESPACE" get pod -l "$DEPLOY_SELECTOR" -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}')"
CANDIDATE=""
COUNT=0
while IFS= read -r p; do
  [ -z "$p" ] && continue
  p="$(printf '%s' "$p" | tr -d '[:space:]')"
  [ -z "$p" ] && continue
  COUNT=$((COUNT+1))
  CANDIDATE="$p"
done <<EOF
$PODS
EOF
```

如果 `COUNT != 1`，直接失败并要求用户显式传 `pod=<pod-name>`。

---

## 强约束

## 强约束

- **本 Skill 只做一件事：删除 1 个 Pod。**
- 默认命名空间 `online-boutique`，默认服务 `redis-cart`。
- 必须保证“单目标”原则：无法唯一确定目标 Pod 时直接失败，要求用户显式传 `pod`。
- 删除后需做基础验证（新 Pod 拉起 / rollout 状态）。

---

## 用法

```bash
/delete-target-pod [pod=<pod-name>] [service=redis-cart] [namespace=online-boutique] [incident_id=<id>] [fault_id=<id>]
```

### 参数

- `pod`：可选。显式指定要删除的 Pod 名称（最高优先级）。
- `service`：可选，默认 `redis-cart`。
- `namespace`：可选，默认 `online-boutique`。
- `incident_id`：可选。仅用于关联事件上下文；缺失时也必须写 `mitigation_done` annotation。
- `fault_id`：可选。用于串联注入与止损时间线；缺失时也不影响 annotation 写入。

参数优先级：
1. 若提供 `pod`，以 `pod` 为准；
2. 否则按 `service + namespace` 自动解析；
3. 若自动解析结果非唯一，直接失败。

---

## 执行步骤

### 步骤 0：解析参数并打印执行横幅

从 `$ARGUMENTS` 解析上述参数并应用默认值。

输出示例：

```text
╔══════════════════════════════════════════════╗
║      Delete Target Pod 止损器 已启动        ║
╠══════════════════════════════════════════════╣
║  namespace: online-boutique                 ║
║  service:   redis-cart                      ║
║  pod:       <auto-resolve or explicit>      ║
║  action:    delete single pod               ║
╚══════════════════════════════════════════════╝
```

---

### 步骤 1：解析目标 Deployment（当未显式给 pod）

当 `pod` 未提供时，按以下顺序定位 `TARGET_DEPLOYMENT`：

1. 先按 Service 名 `service` 读取 selector；
2. 若 Service 存在，优先 `kubectl get deploy -l <selector>`，单命中直接使用；
3. 若 0 命中，走 `selector -> Pod -> RS -> Deployment` 反查；
4. 若 Service 不存在，按 Deployment 名 `service` 直接查；
5. 若仍不存在，做 Deployment 名包含匹配（仅单命中可用）；
6. 任一步骤出现多命中，直接失败。

最终必须得到且只得到一个 `TARGET_DEPLOYMENT`。

---

### 步骤 2：解析唯一目标 Pod

#### 情况 A：用户显式传入 `pod`

- 校验 Pod 在目标 namespace 存在；
- 如同时已解析出 deployment，则校验该 Pod 属于该 deployment（避免误删）。

#### 情况 B：未传 `pod`（自动选择）

1. 根据 Deployment 的 `spec.selector.matchLabels` 列出 Pod；
2. 仅保留 Running/Pending/NotReady（排除 Succeeded/Failed/Terminating）；
3. 选择规则：
   - 若仅 1 个 Pod，直接选它；
   - 若多个 Pod，优先找带 `chaos.alarmkeeper.io/recovery-hint=delete-pod` 的 Pod；
   - 若仍非唯一，直接失败并要求用户显式传 `pod=<pod-name>`。

最终得到且只得到一个 `TARGET_POD`。

---

### 步骤 3：执行删除（原子止损动作）

```bash
kubectl -n "$NAMESPACE" delete pod "$TARGET_POD"
```

记录删除前后的时间戳，用于后续复盘。

---

### 步骤 4：删除后验证（必须执行）

若已解析到 `TARGET_DEPLOYMENT`，执行：

```bash
kubectl -n "$NAMESPACE" rollout status deployment/"$TARGET_DEPLOYMENT" --timeout=180s
```

并输出当前 Pod 列表用于确认新实例是否已拉起：

```bash
kubectl -n "$NAMESPACE" get pod -l "$DEPLOY_SELECTOR" -o wide
```

如果没有 deployment 上下文（仅按 pod 删除），至少执行：

```bash
kubectl -n "$NAMESPACE" get pod "$TARGET_POD" || true
kubectl -n "$NAMESPACE" get pod -o wide
```

期望：
- 被删除 Pod 不再存在；
- 对应工作负载能拉起新 Pod 并趋于 Ready。

---

### 步骤 5：写 Grafana annotation（止损成功必写）

**规则**：
- 删除成功 + rollout 验证通过 → **必须写** `mitigation_done` annotation
- 删除失败或验证失败 → **不写** annotation
- `incident_id` / `fault_id` 均为可选，缺失时不传，**但不得因此跳过 annotation**
- annotation 写入失败不阻断主流程（best-effort）

实现：

```bash
# 成功时写 mitigation_done（不依赖 incident_id/fault_id，缺失时照常写）
INCIDENT_ARG=""
FAULT_ARG=""
[ -n "$INCIDENT_ID" ] && INCIDENT_ARG="--incident-id $INCIDENT_ID"
[ -n "$FAULT_ID" ] && FAULT_ARG="--fault-id $FAULT_ID"

./deploy/docker/emit-grafana-annotation.sh \
  --event mitigation_done \
  --action-id "delete_single_pod" \
  --service "$SERVICE" \
  --namespace "$NAMESPACE" \
  $INCIDENT_ARG \
  $FAULT_ARG \
  --pod "$TARGET_POD" \
  --deployment "$TARGET_DEPLOYMENT" \
  --source delete-target-pod \
  --dashboard-uid "${GRAFANA_DASHBOARD_UID:-fffrl21oam2gwa}" \
  || echo "WARN: grafana annotation failed (mitigation_done)"
```

> 失败场景：直接跳过 annotation 写入，无需执行 `mitigation_failed`

---

## 输出模板

成功：

```text
✅ 止损动作完成：已删除目标 Pod
- namespace: <namespace>
- service: <service>
- target deployment: <deployment-or-N/A>
- deleted pod: <pod>
- verification: rollout_status=ok / replacement_pod_ready=observed
- grafana_annotation: mitigation_done (best-effort, incident_id/fault_id optional, always attempt)
```

失败：

```text
❌ 止损动作失败：未执行或未完成单 Pod 删除
- namespace: <namespace>
- service: <service>
- target deployment: <deployment-or-N/A>
- target pod: <pod-or-N/A>
- reason: <error>
- next step: 显式传入 pod=<pod-name> 后重试，或按 runbook 执行其它止损动作
```

## 安全规则

- 任何“多匹配”都必须拒绝执行。
- 禁止批量删除 Pod（禁止 label 直接 delete 多 Pod）。
- 禁止删除非目标 namespace 资源。
- 若目标无法唯一解析，宁可失败，不可猜测。
