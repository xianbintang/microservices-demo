# Cause Runbook: service_memory_pressure

## 1. 根因定义

服务内存压力过高（泄漏、缓存膨胀、对象突增或 limit 设置不合理）导致性能下降甚至 OOM。

## 2. 识别证据

- 内存利用率持续高位
- OOMKilled / restart 增加
- 发布前后趋势出现明显差异

## 3. 止损动作（Incident 级）

- `action_id`: `temporary_scale_out`
- `action_id`: `raise_memory_limit_if_safe`
- `action_id`: `rollback_release_or_config`

## 4. 恢复判定

- 内存回落并稳定
- OOM 不再出现
- 延迟/错误率恢复

## 5. 幂等要求

遵循 `../policies/incident-dedup-and-idempotency.md`。
