# 删除 Pod 操作手册

> 原子操作：安全删除 Pod，触发 Kubernetes 自动重建。
> 适用场景：Pod 无响应、OOMKill 循环、CPU 节流无法自愈时。

---

## 使用场景

| 场景 | 触发条件 | 操作 |
|------|---------|------|
| Pod 无响应 | Pod 状态 Running 但服务不可达，重启次数未增加 | 删除 Pod |
| OOMKill 循环 | `kube_pod_container_status_last_terminated_reason{reason="OOMKilled"}` 持续增加 | 删除 Pod（同时评估调整 memory limit） |
| CPU 节流无法自愈 | CPU 节流率 > 80% 持续 > 10 分钟，P99 延迟持续高位 | 删除 Pod |
| Pod Pending | Pod 卡在 Pending 状态超过 5 分钟 | 先 `kubectl describe pod` 排查原因 |

**不适用场景**：
- StatefulSet 有状态服务（需额外评估数据一致性风险）
- 副本数为 1 的单点服务（删除期间会短暂中断）

---

## 前置检查

### 1. 确认 Pod 状态

```bash
kubectl get pod -n <namespace> -o wide
# 查看 STATUS、RESTARTS、AGE
```

### 2. 确认控制器管理

```bash
# 确认 Pod 由 Deployment 或 ReplicaSet 管理（删除后会自动重建）
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.metadata.ownerReferences}'
```

输出中应包含 `"kind":"ReplicaSet"` 或 `"kind":"StatefulSet"`。

> 如果 Pod 是裸 Pod（无控制器），删除后不会自动重建，**需谨慎操作**。

### 3. 确认副本数

```bash
kubectl get deployment <deployment-name> -n <namespace>
# 确认 DESIRED >= 2（有冗余副本）
```

---

## 操作步骤

### Step 1：记录当前状态

```bash
# 记录删除前的 Pod 名称和重启次数（用于后续对比）
kubectl get pod -n <namespace> | grep <service-name>
```

### Step 2：删除 Pod

```bash
kubectl delete pod <pod-name> -n <namespace>
```

> 默认 grace period 为 30 秒，Pod 会先收到 SIGTERM，30s 后强制终止。
> 若需立即终止（Pod 无响应）：`kubectl delete pod <pod-name> -n <namespace> --grace-period=0 --force`

### Step 3：观察新 Pod 启动

```bash
# Watch 模式，观察新 Pod 从 Pending → ContainerCreating → Running
kubectl get pod -n <namespace> -w
```

预期状态流转：
1. 旧 Pod: `Terminating`
2. 新 Pod: `Pending` → `ContainerCreating` → `Running`
3. 新 Pod: `1/1 Running`（Ready 探针通过后）

### Step 4：验证服务恢复

```bash
# 确认新 Pod Ready
kubectl get pod -n <namespace> | grep <service-name>
```

通过 mcp-grafana 或 Grafana 验证指标恢复：
```promql
# 确认 P99 延迟回落（应 < 100ms 基线）
histogram_quantile(0.99,
  sum(rate(traces_spanmetrics_duration_milliseconds_bucket[2m])) by (service_name, le)
)

# 确认错误率回落到 0
sum(rate(traces_spanmetrics_calls_total{status_code="STATUS_CODE_ERROR", service_name="<service>"}[2m]))
```

---

## 注意事项

### StatefulSet Pod

```bash
# StatefulSet Pod 删除后按顺序重建，Pod 名称不变（如 redis-cart-0）
kubectl delete pod redis-cart-0 -n online-boutique
```

- 数据持久化依赖 PVC，删除 Pod 不会删除数据
- 但删除期间该副本不可用，如只有 1 个副本会短暂中断

### 多副本滚动删除

如需逐一删除多个 Pod（避免同时不可用）：

```bash
# 每次删除一个，等待新 Pod Ready 后再删除下一个
for pod in $(kubectl get pod -n <namespace> -l app=<service> -o name); do
  kubectl delete $pod -n <namespace>
  kubectl rollout status deployment/<service> -n <namespace>
done
```

---

## 回滚方案

若删除 Pod 不生效（新 Pod 启动后仍异常）：

```bash
# 触发 Deployment 滚动重启（重建所有 Pod）
kubectl rollout restart deployment/<deployment-name> -n <namespace>

# 查看滚动更新状态
kubectl rollout status deployment/<deployment-name> -n <namespace>
```

若问题依旧，升级处理：
1. 调整 `resources.limits.cpu` / `resources.limits.memory`（`kubectl edit deployment`）
2. 考虑 HPA 扩容减少单 Pod 负载
3. 参考 [CPU 高负载 Runbook](../business/high-cpu-runbook.md)

---

## 相关文档

- [通用告警处理 SOP](../alert-runbook/general-alert-handling.md)
- [CPU 高负载 Runbook](../business/high-cpu-runbook.md)
- [RCA 报告指南](../rca/rca-guide.md)
