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
