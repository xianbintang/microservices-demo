# Alert Playbook: ServiceHighErrorRate

## 1. 告警现象 (What's Happening?)

- **告警名**: `ServiceHighErrorRate`
- **触发条件**: 服务错误率 > **5%**，持续 **1m**
- **潜在影响**: 直接用户可用性受损，通常需高优先级处置

## 2. 可能原因 (Why?)

1. `downstream_dependency_issue`
2. `cpu_overload_injection`
3. `bad_release_cpu_regression`
4. `traffic_hotspot_cpu_saturation`

## 3. 排查方法 (How to Troubleshoot)

1. **先确认影响范围**：哪些 service_name 在报错，错误率峰值多高
2. **查日志关键词**：timeout / refused / 5xx / panic
3. **查 Trace 错误 span**：是本服务错误还是下游透传
4. **若伴随 CPU 告警**：优先验证是否混沌注入或 CPU 饱和
5. **查发布/配置变更**：与告警开始时间是否对齐

## 4. 根因路由与止损入口

- `downstream_dependency_issue` -> `../causes/downstream-dependency-issue.md`
- `cpu_overload_injection` -> `../causes/cpu-overload-injection.md`
- `bad_release_cpu_regression` -> `../causes/cpu-regression-after-release.md`
- `traffic_hotspot_cpu_saturation` -> `../causes/cpu-saturation-by-traffic.md`

> 止损必须经过去重与幂等校验：`../policies/incident-dedup-and-idempotency.md`
