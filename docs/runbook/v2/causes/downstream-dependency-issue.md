# Cause Runbook: downstream_dependency_issue

## 1. 根因定义

下游依赖（DB/缓存/外部服务/内部微服务）故障、超时或连接问题，导致上游延迟与错误率升高。

## 2. 识别证据

- Trace 显示错误/慢 span 集中在下游调用
- 日志出现 timeout / connection refused / pool exhausted
- 下游服务同窗也出现错误率或资源告警

## 3. 止损动作（Incident 级）

- `action_id`: `degrade_or_bypass_dependency`（降级/熔断）
- `action_id`: `restart_unhealthy_dependency_pod`（重启异常实例）
- `action_id`: `scale_dependency`（扩容下游）

> 仅在满足幂等与 cooldown 条件下执行。

## 4. 恢复判定

- 下游错误率下降
- 上游 P99 与错误率恢复
- 关联告警 resolved

## 5. 幂等要求

遵循 `../policies/incident-dedup-and-idempotency.md`。
