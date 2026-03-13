# Alert Playbook: ServiceHighMemoryUtilization

## 1. 告警现象 (What's Happening?)

- **告警名**: `ServiceHighMemoryUtilization`
- **触发条件**: 服务内存 / memory limit > **90%**，持续 **1m**
- **潜在影响**: 可能演化为 OOM、重启、延迟上升

## 2. 可能原因 (Why?)

1. `service_memory_pressure`（缓存膨胀/泄漏/突发对象分配）
2. `bad_release_cpu_regression`（发布回归也可能伴随内存异常）
3. `noisy_alert_rule`（阈值偏紧）

## 3. 排查方法 (How to Troubleshoot)

1. 看是否伴随 `OOMKilled`、重启、延迟和错误率变化
2. 对比最近发布前后的内存趋势
3. 识别是持续爬升（疑似泄漏）还是短时尖峰
4. 确认是否是低 limit 导致“假高利用率”

## 4. 根因路由与止损入口

- `service_memory_pressure` -> `../causes/service-memory-pressure.md`
- `bad_release_cpu_regression` -> `../causes/cpu-regression-after-release.md`
- `noisy_alert_rule` -> `../causes/noisy-alert-rule.md`

> 仍按 incident 级执行止损：`../policies/incident-dedup-and-idempotency.md`
