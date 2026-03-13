# Cause Runbook: traffic_pattern_shift_or_upstream_issue

## 1. 根因定义

上游流量模式变化（突增/突降）、入口路由策略变化或上游故障，导致当前服务流量异常。

## 2. 识别证据

- 流量突增/突降与上游事件时间一致
- 上游服务或网关同时出现告警
- 本服务资源与错误信号符合被动受影响特征

## 3. 止损动作（Incident 级）

- `action_id`: `adjust_rate_limit_or_routing`
- `action_id`: `temporary_scale_out`
- `action_id`: `activate_degrade_mode`

## 4. 恢复判定

- 流量曲线恢复到可接受区间
- 级联告警回落

## 5. 幂等要求

遵循 `../policies/incident-dedup-and-idempotency.md`。
