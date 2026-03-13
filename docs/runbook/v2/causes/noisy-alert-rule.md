# Cause Runbook: noisy_alert_rule

## 1. 根因定义

告警阈值、窗口、防抖策略不合理，导致在正常波动下频繁触发告警。

---

## 2. 识别证据

1. 指标长期在阈值附近抖动（flapping）
2. 告警与恢复频繁切换
3. 无明显用户影响（SLO 未受损）
4. 无发布回归、无混沌注入、无依赖故障证据

---

## 3. 止损动作（Incident 级）

### Action D1：抑制告警噪音（短期）
- `action_id`: `silence_or_inhibit_alert`
- `dedup_scope`: `incident`
- `cooldown`: `30m`
- `max_executions`: `1`

### Action D2：优化告警规则（长期）
- `action_id`: `tune_threshold_window_antiflap`
- `dedup_scope`: `incident`
- `cooldown`: `24h`
- `max_executions`: `1`

---

## 4. 恢复判定

- 告警抖动显著减少
- 告警触发与真实故障相关性提升

---

## 5. 幂等要求

统一遵循 `../policies/incident-dedup-and-idempotency.md`。
