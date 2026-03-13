# Cause Runbook: traffic_hotspot_cpu_saturation

## 1. 根因定义

真实流量高峰、热点请求或容量不足导致服务 CPU 持续高位并出现节流。

---

## 2. 识别证据

1. QPS 明显高于基线
2. CPU usage 与 throttling 同步上升
3. HPA 接近或达到上限
4. 无混沌注入证据（无 `chaos-cpu-hog` / 无注入注解）

---

## 3. 止损动作（Incident 级）

### Action B1（首选）：临时扩容
- `action_id`: `scale_out_for_hot_traffic`
- `dedup_scope`: `incident`
- `cooldown`: `10m`
- `max_executions`: `2`

### Action B2：启用限流/降级
- `action_id`: `enable_rate_limit_or_degrade`
- `dedup_scope`: `incident`
- `cooldown`: `15m`
- `max_executions`: `1`

### Action B3：热点隔离
- `action_id`: `isolate_hot_endpoint_or_tenant`
- `dedup_scope`: `incident`
- `cooldown`: `20m`
- `max_executions`: `1`

---

## 4. 恢复判定

- CPU throttling 回落
- P99 与错误率回落
- 相关告警进入 resolved

---

## 5. 幂等要求

统一遵循 `../policies/incident-dedup-and-idempotency.md`。
