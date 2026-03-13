# 高 CPU 故障排查与止损 Runbook（通用）

## 1. 适用场景与症状

适用于 `online-boutique` 命名空间内**任意服务**出现高 CPU 问题，且满足以下条件时：

- 异常主要集中在单个或少数 Pod/容器实例；
- 工作负载由 Deployment/ReplicaSet 管理，删除 Pod 后可自动重建；
- 服务为无状态或可接受单实例重建带来的短暂抖动。

常见症状（以指标与现象为主）：

- 资源指标异常：
  - 目标容器 CPU 使用率持续接近/触顶 limit；
  - `container_cpu_cfs_throttled_periods_total / container_cpu_cfs_periods_total` 持续升高。
- 业务指标劣化：
  - 相关接口延迟升高（如 P95/P99）；
  - 错误率升高（如 timeout / 5xx）。
- 实例级不均衡：
  - 同一服务下仅少数 Pod 明显异常（CPU/节流显著高于同组实例）。

---

## 2. 快速确认（告警 / CPU / 延迟）

### 2.1 确认异常信号（告警或指标）

```bash
# 若系统已配置告警，可先查当前 firing
# 或直接在 Prometheus/Grafana 以指标异常为准
kubectl get --raw "/apis" >/dev/null
```

建议记录：

- 异常开始时间（或告警 activeAt）
- 受影响的 `pod` / `container` / `service`
- 当时的 CPU、throttling、延迟、错误率数值

### 2.2 快速看目标服务实例状态

```bash
kubectl get pod -n online-boutique -o wide
kubectl top pod -n online-boutique
```

### 2.3 快速看受影响业务链路

在 Prometheus/Grafana 观察近 5~15 分钟：

- 涉及服务的 P99
- 涉及服务的错误率
- 目标容器 CPU 与 throttling

---

## 3. 根因排查路径

### 3.1 查告警时间附近的变更线索（Deployment）

```bash
kubectl -n <namespace> get deploy/<deployment-name> -o jsonpath='{.metadata.annotations.kubernetes\.io/change-cause}{"\n"}'
kubectl -n <namespace> rollout history deployment/<deployment-name>
```

重点判断：

- 异常前后是否发生发布、配置变更、镜像变更；
- 是否可明确定位到某次 revision 后开始恶化。

### 3.2 查 Pod/容器实例级异常

```bash
kubectl -n <namespace> get pod -l app=<app-label> -o wide
kubectl -n <namespace> top pod
```

重点看：

- 是否只有 1~2 个 Pod 明显异常（CPU/节流偏高）；
- 是否存在重启、NotReady、探针失败等伴随问题。

### 3.3 查容器内热点进程与日志

```bash
kubectl -n <namespace> exec <pod-name> -c <container-name> -- sh -c 'ps'
kubectl -n <namespace> logs <pod-name> -c <container-name> --tail=100
```

若需要排除/确认人为注入因素，可额外核对：

```bash
kubectl -n <namespace> get pod/<pod-name> -o jsonpath='{.metadata.annotations.chaos\.alarmkeeper\.io/fault-id}{"\n"}{.metadata.annotations.chaos\.alarmkeeper\.io/fault-type}{"\n"}{.metadata.annotations.chaos\.alarmkeeper\.io/recovery-hint}{"\n"}'
kubectl -n <namespace> exec <pod-name> -c <container-name> -- sh -c 'tail -n 20 /dev/shm/chaos_cpu_overload.log'
```

---

## 4. 止损动作（按优先级）

> 目标：优先恢复业务，再做复盘。

### 4.1 首选：删除目标 Pod（推荐）

适用于以下可快速替换实例场景：

- 异常集中在单个/少数 Pod；
- 工作负载由 Deployment/ReplicaSet 管理；
- 删除 Pod 后可自动拉起新实例；
- 服务无状态或可接受短暂实例重建。

> 若注解中出现 `recovery-hint=delete-pod`，可直接按本步骤执行。

```bash
kubectl -n <namespace> delete pod <pod-name>
kubectl -n <namespace> rollout status deployment/<deployment-name> --timeout=180s
```

说明：

- 删除异常 Pod 可快速完成实例级切换；
- Deployment 会自动拉起新 Pod；
- 对实例级异常（进程跑飞、局部资源争用、异常状态残留）通常是最小影响且最快的止损方式。

### 4.2 备选：rollout undo（仅当模板被改动时）

```bash
kubectl rollout undo deployment/<deployment-name> -n <namespace>
kubectl rollout status deployment/<deployment-name> -n <namespace> --timeout=180s
```

### 4.3 备选：重发干净版本

```bash
# 任选其一
kubectl apply -f <clean-manifest.yaml>
# 或
helm upgrade --install <release> <chart> -n <namespace> -f <values>
```

### 4.4 临时缓解：扩容（仅缓解，不是根因修复）

```bash
kubectl scale deployment/<deployment-name> -n <namespace> --replicas=<N>
```

---

## 5. 恢复验证（必须执行）

### 5.1 新 Pod 就绪

```bash
kubectl -n <namespace> get pod -l app=<app-label> -o wide
```

### 5.2 异常负载是否已清除

```bash
# 新 Pod 内确认无异常高 CPU 进程（按实际进程名替换）
kubectl -n <namespace> exec <new-pod-name> -c <container-name> -- sh -c 'ps'
```

若需确认注入进程是否已清除，可额外核对：

```bash
kubectl -n <namespace> exec <new-pod-name> -c <container-name> -- sh -c 'ps | grep -E "yes|redis-benchmark" | grep -v grep | wc -l'
kubectl -n <namespace> exec <new-pod-name> -c <container-name> -- sh -c 'if [ -f /dev/shm/chaos_cpu_overload.pid ]; then cat /dev/shm/chaos_cpu_overload.pid; else echo pid_missing; fi'
```

### 5.3 指标回落

验证以下指标在 5~10 分钟内回落：

- 目标容器 CPU 使用率回落
- 目标容器 throttling ratio 回落
- 受影响业务链路延迟/错误率回落

### 5.4 告警恢复

确认相关 CPU/性能告警由 firing 转为 resolved。

---

## 6. 复盘记录模板

```text
【事件基本信息】
- 事件标题：
- 发生时间：
- 恢复时间：
- 影响范围（服务/用户）：

【检测与告警】
- 首条告警：
- 告警开始时间：
- 关键指标（目标容器CPU/节流、链路P99、错误率）：

【根因结论】
- 根因类型：代码/配置/容量/依赖/运行时（可多选）
- 关键证据：
  1) 变更线索（change-cause / rollout history）
  2) 实例线索（异常 Pod/容器、重启、探针、资源水位）
  3) 日志与进程线索（热点进程、关键错误）
  4) （如适用）注入线索（fault-id/fault-type/recovery-hint, CHAOS_CPU_OVERLOAD_ACTIVE）

【止损过程】
- 采取动作：delete pod / rollout undo / 重发版
- 执行命令：
- 执行结果：

【恢复验证】
- 新 Pod Ready：
- 注入进程清除：
- 目标容器 CPU/节流回落：
- 受影响链路指标回落：
- 告警 resolved：

【改进项】
- 预防措施：
- 监控优化：
- Runbook 更新项：
```
