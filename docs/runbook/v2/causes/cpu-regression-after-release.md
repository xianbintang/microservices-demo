# Cause Runbook: bad_release_cpu_regression

## 1. 根因定义

代码发布或配置变更后引入 CPU 回归，导致节流、延迟或错误率升高。

---

## 2. 识别证据

1. 告警时间与发布/配置变更时间高度重合
2. 变更前后 CPU 指标阶跃式上升
3. 回滚后指标可快速恢复

---

## 3. 止损动作（Incident 级）

### Action C1（首选）：回滚版本
- `action_id`: `rollback_release`
- `dedup_scope`: `incident`
- `cooldown`: `10m`
- `max_executions`: `1`

### Action C2：回滚配置
- `action_id`: `rollback_config`
- `dedup_scope`: `incident`
- `cooldown`: `10m`
- `max_executions`: `1`

### Action C3（临时）：扩容保服务
- `action_id`: `temporary_scale_out`
- `dedup_scope`: `incident`
- `cooldown`: `10m`
- `max_executions`: `1`

---

## 4. 恢复判定

- 回滚后 CPU/throttling 回落
- P99 与错误率恢复
- 告警 resolved

---

## 5. 幂等要求

统一遵循 `../policies/incident-dedup-and-idempotency.md`。
