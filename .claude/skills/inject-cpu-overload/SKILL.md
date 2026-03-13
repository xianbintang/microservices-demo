---
name: inject-cpu-overload
description: 注入任意服务容器内的持续 CPU 过载故障（仅注入不恢复）。默认 service=redis-cart、namespace=online-boutique。用法：/inject-cpu-overload [service=redis-cart] [namespace=online-boutique]
license: MIT
compatibility:
  claude_code: ">=1.0"
metadata:
  author: xianb
  version: 1.2.0
  generatedBy: claude-sonnet-4-6
---

# CPU 过载故障注入 Skill（通用）

用于在 Kubernetes 中对**任意目标服务**执行容器内进程级 CPU 注入，让该服务实例出现 CPU 过载，进而影响其上游/下游链路。

## 强约束

- **本 Skill 仅负责注入，不提供 stop/recover 动作。**
- 注入目标是业务容器内部（非 sidecar）。
- Pod 应保持 Running（不主动打挂 Pod）。
- 恢复通过标准止损动作完成（优先 delete pod，或按 runbook 执行 rollback/redeploy）。

## 用法

```bash
/inject-cpu-overload [service=redis-cart] [namespace=online-boutique]
```

### 参数（极简）

- `service`：可选，默认 `redis-cart`
- `namespace`：可选，默认 `online-boutique`

解析规则：
1. 用户显式传入 `service` -> 使用用户值。
2. 用户未传 -> `service=redis-cart`。
3. 用户显式传入 `namespace` -> 使用用户值。
4. 用户未传 -> `namespace=online-boutique`。

---

## 执行步骤

### 步骤 0：解析参数并打印注入横幅

从 `$ARGUMENTS` 解析 `service` 与 `namespace`，并应用默认值。

输出示例：

```text
╔══════════════════════════════════════════════╗
║      CPU Overload 注入器 已启动             ║
╠══════════════════════════════════════════════╣
║  service:   redis-cart                      ║
║  namespace: online-boutique                 ║
║  mode:      inject-only (no recover)        ║
║  target:    in-container process            ║
╚══════════════════════════════════════════════╝
```

---

### 步骤 1：解析目标 Deployment（严格单目标）

按以下顺序解析目标 Deployment：

1. 先按 Service 名 `service` 查找并读取 selector。
2. 若 Service 不存在，按 Deployment 名 `service` 直接查。
3. 若仍不存在，对 Deployment 名做包含匹配（仅单命中可用，多命中直接失败）。

最终必须得到且只得到一个 `TARGET_DEPLOYMENT`。

---

### 步骤 2：定位目标 Pod 与业务容器

获取目标 Deployment 对应 Pod：

```bash
APP_LABEL=$(kubectl -n "$NAMESPACE" get deploy "$TARGET_DEPLOYMENT" -o jsonpath='{.spec.selector.matchLabels.app}')
TARGET_POD=$(kubectl -n "$NAMESPACE" get pod -l "app=$APP_LABEL" -o jsonpath='{.items[0].metadata.name}')
```

容器选择规则（尽量避开代理容器）：

1. 如果存在 `server` / `app` / `main` / `redis`，优先选这些业务容器名。
2. 否则选择第一个容器。
3. 若命中 `chaos-cpu-hog` / `istio-proxy` / `linkerd-proxy` 等非业务容器，继续选下一个。

最终得到 `TARGET_CONTAINER`。

---

### 步骤 3：幂等检查（已注入则直接返回）

检查 PID 文件对应进程是否仍存活：

```bash
kubectl -n "$NAMESPACE" exec "$TARGET_POD" -c "$TARGET_CONTAINER" -- sh -c '
  if [ -f /dev/shm/chaos_cpu_overload.pid ] && kill -0 "$(cat /dev/shm/chaos_cpu_overload.pid)" 2>/dev/null; then
    echo injected
  else
    echo not_injected
  fi
'
```

若为 `injected`，直接返回“已注入”，不重复启动。

---

### 步骤 4：容器内 CPU 过载注入（持续）

生成标识：

```bash
FAULT_ID="cpu-$(date -u +%Y%m%dT%H%M%SZ)"
INJECTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
```

在目标容器后台启动 CPU burn 进程（使用 `/dev/shm`，兼容只读根文件系统）：

```bash
kubectl -n "$NAMESPACE" exec "$TARGET_POD" -c "$TARGET_CONTAINER" -- sh -c "
  nohup sh -c '
    echo CHAOS_CPU_OVERLOAD_ACTIVE fault_id=$FAULT_ID service=$SERVICE namespace=$NAMESPACE container=$TARGET_CONTAINER;
    yes >/dev/null & yes >/dev/null & yes >/dev/null & yes >/dev/null & wait
  ' >/dev/shm/chaos_cpu_overload.log 2>&1 &
  CHAOS_PID=\$!
  echo \$CHAOS_PID >/dev/shm/chaos_cpu_overload.pid
"
```

---

### 步骤 5：写入 breadcrumbs（用于 oncall 回溯）

对目标 Pod 写注解：

```bash
kubectl -n "$NAMESPACE" annotate pod "$TARGET_POD" \
  chaos.alarmkeeper.io/fault-id="$FAULT_ID" \
  chaos.alarmkeeper.io/fault-type="cpu-overload" \
  chaos.alarmkeeper.io/injected-by="inject-cpu-overload" \
  chaos.alarmkeeper.io/injected-at="$INJECTED_AT" \
  chaos.alarmkeeper.io/recovery-hint="delete-pod" \
  --overwrite
```

对 Deployment 写变更线索（不改模板，不触发 rollout）：

```bash
kubectl -n "$NAMESPACE" annotate deploy "$TARGET_DEPLOYMENT" \
  kubernetes.io/change-cause="chaos inject-cpu-overload fault_id=$FAULT_ID service=$SERVICE mode=process" \
  --overwrite
```

---

### 步骤 6：注入后校验

```bash
# 1) PID 存活
kubectl -n "$NAMESPACE" exec "$TARGET_POD" -c "$TARGET_CONTAINER" -- sh -c 'cat /dev/shm/chaos_cpu_overload.pid && kill -0 "$(cat /dev/shm/chaos_cpu_overload.pid)"'

# 2) 注入日志标记
kubectl -n "$NAMESPACE" exec "$TARGET_POD" -c "$TARGET_CONTAINER" -- sh -c 'tail -n 20 /dev/shm/chaos_cpu_overload.log'

# 3) 注解线索
kubectl -n "$NAMESPACE" get pod "$TARGET_POD" -o jsonpath='{.metadata.annotations.chaos\.alarmkeeper\.io/fault-id}{"\n"}{.metadata.annotations.chaos\.alarmkeeper\.io/fault-type}{"\n"}{.metadata.annotations.chaos\.alarmkeeper\.io/recovery-hint}{"\n"}'
```

期望日志包含：

```text
CHAOS_CPU_OVERLOAD_ACTIVE fault_id=<id> service=<svc> namespace=<ns> container=<container>
```

---

## 输出模板

```text
✅ 容器内 CPU 过载故障注入完成
- target deployment: <deployment>
- target pod: <pod>
- target container: <container>
- namespace: <namespace>
- fault_id: <fault_id>
- evidence: pid=/dev/shm/chaos_cpu_overload.pid, pod annotations=chaos.alarmkeeper.io/*, log_prefix=CHAOS_CPU_OVERLOAD_ACTIVE

⚠️ 本 Skill 不提供恢复动作。
建议止损：kubectl delete pod <target-pod> -n <namespace>
```

## 安全规则

- 仅允许对**一个** Deployment / Pod 操作。
- 多匹配时必须拒绝执行。
- 已注入状态下必须幂等返回，禁止重复注入多个后台进程。
- 不执行任何回滚/恢复命令。
