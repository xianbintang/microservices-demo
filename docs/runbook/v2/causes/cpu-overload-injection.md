# Cause Runbook: cpu_overload_injection

## 1. 根因定义

`cpu_overload_injection` 指通过 `/inject-cpu-overload` 或等效手段，在 Deployment Pod Template 中注入 `chaos-cpu-hog` sidecar，导致持续 CPU 占用和节流。

---

## 2. 识别证据（满足越多置信度越高）

1. Deployment 注解存在：
   - `chaos.alarmkeeper.io/fault-type=cpu-overload`
   - `chaos.alarmkeeper.io/fault-id`
   - `kubernetes.io/change-cause` 包含 `chaos inject-cpu-overload`
2. Pod spec 出现 `chaos-cpu-hog` 容器
3. `chaos-cpu-hog` 日志包含：
   - `CHAOS_CPU_OVERLOAD_ACTIVE fault_id=...`

---

## 3. 止损动作（Incident 级）

> 本文动作按 Incident 级执行，不按单条告警执行。

### Action A1（首选）：回滚到上一健康 Revision

- `action_id`: `rollback_injected_revision`
- `dedup_scope`: `incident`
- `cooldown`: `10m`
- `max_executions`: `1`

执行条件：
- 已确认注入证据
- 上一 revision 已知健康

建议动作：
1. rollout undo / 重新部署干净版本（不含 `chaos-cpu-hog`）
2. 等待 rollout 完成并验证恢复

### Action A2（备选）：重发干净清单

- `action_id`: `redeploy_clean_manifest`
- `dedup_scope`: `incident`
- `cooldown`: `10m`
- `max_executions`: `1`

适用：
- rollout undo 不可用
- revision 历史不可信

### Action A3（临时缓解）：扩容

- `action_id`: `temporary_scale_out`
- `dedup_scope`: `incident`
- `cooldown`: `15m`
- `max_executions`: `2`

说明：
- 仅缓解，不移除注入根因
- 必须后续执行 A1/A2 才算根因修复

### Action A4（不推荐作为根因修复）：删除单 Pod

- `action_id`: `delete_single_pod`
- `dedup_scope`: `incident`
- `cooldown`: `5m`
- `max_executions`: `1`

说明：
- 如果 Deployment 模板仍带 `chaos-cpu-hog`，新 Pod 仍会继续过载
- 仅在“短期止血 + 已计划 A1/A2”时使用

---

## 4. 恢复判定

连续观察至少 5~10 分钟，满足：
1. 新 Pod Ready
2. CPU throttling 明显回落
3. P99 和错误率回到阈值内
4. 关联告警进入 resolved

---

## 5. 自动化执行约束（必须）

执行前检查：
- 是否已存在相同 `idempotency_key = incident_id + cause_id + action_id`
- 是否处于 cooldown
- 是否拿到 incident lock

执行后记录：
- `incident_id`
- `cause_id=cpu_overload_injection`
- `action_id`
- `result`（success/failed/skipped）
- `evidence_refs`（annotation/log/metric）

Grafana annotation 约定（建议）：
- 注入阶段：由 `/inject-cpu-overload` 仅在注入成功后写 `event:inject_start`
- 止损阶段：Runbook 仅在动作完成后写
  - `event:mitigation_done` 或 `event:mitigation_failed`
- 统一 tags：`event`, `service`, `namespace`, `source`；
  - 注入事件附带：`fault_id`
  - 止损事件附带：`incident_id`, `action_id`（`fault_id` 可选）

优先通过 `incident_id` 追踪止损链路；如存在 `fault_id`，可将注入与止损事件在 dashboard 时间线上串联回放。

详细机制见：`../policies/incident-dedup-and-idempotency.md`。

---

## 6. 实战排查 Runbook：Frontend 延迟上涨（已验证案例）

> 目标：当 `ServiceHighLatencyP99` 与 `ServiceHighCPUUtilization` 同窗触发时，快速判断是否为 `cpu_overload_injection` 引起的级联延迟。

### 6.1 先做“同窗关联”

1. 确认告警同窗触发：
   - `ServiceHighLatencyP99` = firing（阈值 200ms）
   - `ServiceHighCPUUtilization` = firing（阈值 0.45）
2. 初步观察是否是“延迟 + CPU”组合，而非单纯错误率。

### 6.2 四项关键指标并行验证（先排除误判）

按同一时间窗（建议近 2h）并行看 4 组数据：

1. `frontend` 与 `checkoutservice` P99
2. `frontend` QPS（calls rate）
3. `frontend` 错误率
4. 各服务 CPU usage / limit

本案例关键观测值：
- `frontend` P99：常态约 35~45ms，抬升到约 241~247ms
- `checkoutservice` P99：抬升到约 350~494ms
- `frontend` QPS：约 28~30 rps，未出现同量级突增
- `frontend` 错误率：接近 0（仅极小尖刺）
- `redis-cart` CPU util：约 0.97（接近打满）

判定：
- **不是流量突增主导**（QPS 未明显上升）
- **不是错误风暴主导**（错误率接近 0）
- 更像下游性能瓶颈导致上游延迟级联。

### 6.3 用 Span 拆解慢点位置

对 `frontend`/`checkoutservice` 做 `span_name` 维度 topk(P99)：

本案例慢点集中在：
- `hipstershop.CheckoutService/PlaceOrder`（~494ms）
- `hipstershop.CartService/AddItem`（~489ms）
- `hipstershop.CartService/GetCart`（~246ms）

判定：瓶颈集中在 checkout/cart 路径，与 `redis-cart` 依赖链一致。

### 6.4 锁定 redis-cart 是否 CPU 饱和 + 节流

建议查询：

```promql
sum(rate(container_cpu_usage_seconds_total{namespace="online-boutique",container!="",container!="POD",pod=~"redis-cart-.+"}[5m]))
```

```promql
sum(kube_pod_container_resource_limits{namespace="online-boutique",resource="cpu",container!="",container!="POD",pod=~"redis-cart-.+"})
```

```promql
sum(rate(container_cpu_cfs_throttled_periods_total{namespace="online-boutique",container!="",container!="POD",pod=~"redis-cart-.+"}[5m]))
/
clamp_min(sum(rate(container_cpu_cfs_periods_total{namespace="online-boutique",container!="",container!="POD",pod=~"redis-cart-.+"}[5m])),0.0001)
```

本案例关键观测值：
- CPU usage ≈ **0.125 core**
- CPU limit = **0.125 core (125m)**
- throttling ratio ≈ **0.125**

判定：redis-cart 长时间满配额运行并发生明显节流。

### 6.5 进入 Pod 做最终根因确认（决定性证据）

```bash
kubectl -n online-boutique exec <redis-cart-pod> -- ps aux
```

若出现以下特征，可直接判定为注入导致：
- 进程命令包含 `CHAOS_CPU_OVERLOAD_ACTIVE fault_id=...`
- 同时存在多个 `yes >/dev/null` 进程

本案例观测到：
- `sh -c echo CHAOS_CPU_OVERLOAD_ACTIVE fault_id=cpu-20260313T154446Z ...`
- 4 个 `yes` 进程持续占用 CPU

可用补强证据：

```bash
kubectl -n online-boutique exec <redis-cart-pod> -- redis-cli SLOWLOG LEN
kubectl -n online-boutique exec <redis-cart-pod> -- redis-cli SLOWLOG GET 10
```

本案例 slowlog 出现大量近 100ms 的 `HMGET/HMSET`，与 CPU 饱和一致。

### 6.6 根因结论模板（可直接复用）

> Frontend 延迟上涨由 `redis-cart` 容器内持续 CPU 过载注入引起。`redis-cart` CPU usage 持续触顶 limit 并发生节流，导致 checkout/cart 路径耗时抬升，进而级联影响 frontend P99。

### 6.7 推荐止损与验证

止损优先级：
1. 回滚/重发干净模板（移除注入）
2. 无法立即回滚时，先终止注入进程临时止血
3. 仅缓解手段：临时扩容（不能替代根因修复）

恢复验证（连续 5~10 分钟）：
- `redis-cart` CPU util 明显回落
- throttling ratio 回落
- `checkoutservice` 与 `frontend` P99 回到阈值内
- 相关告警 resolved

### 6.8 本案例记录（可作为排障基线）

- 受影响服务：`frontend`
- 关键下游：`checkoutservice` / `cartservice` / `redis-cart`
- 触发组合：`ServiceHighLatencyP99` + `ServiceHighCPUUtilization`
- 决定性证据：Pod 内 `CHAOS_CPU_OVERLOAD_ACTIVE` + `yes` 进程
- 根因类型：`cpu_overload_injection`
- fault_id：`cpu-20260313T154446Z`

> 建议将该 fault_id 与 incident_id 一并记录到时间线 annotation，便于后续回放注入-止损链路。
