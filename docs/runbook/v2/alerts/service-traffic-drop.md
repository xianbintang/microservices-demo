# Alert Playbook: ServiceTrafficDrop

## 1. 告警现象 (What's Happening?)

- **告警名**: `ServiceTrafficDrop`
- **触发条件**: 1m 流量 / 30m 基线 < **0.3**（且基线 > 0.2），持续 **1m**
- **潜在影响**: 可能是入口故障、上游阻断、级联失败导致请求掉量

## 2. 可能原因 (Why?)

1. `downstream_dependency_issue`（链路中断/超时）
2. `cpu_overload_injection`（CPU 注入导致请求失败与流量下滑）
3. `traffic_pattern_shift_or_upstream_issue`（上游流量源变化）
4. `bad_release_cpu_regression`

## 3. 排查方法 (How to Troubleshoot)

1. 先对齐是否有 `ServiceHighLatencyP99` / `ServiceHighErrorRate`
2. 查入口层（gateway/frontend）是否 4xx/5xx 上升
3. 查关键下游依赖是否不可用
4. 若同窗存在 CPU 告警，验证是否注入导致级联

## 4. 根因路由与止损入口

- `downstream_dependency_issue` -> `../causes/downstream-dependency-issue.md`
- `cpu_overload_injection` -> `../causes/cpu-overload-injection.md`
- `traffic_pattern_shift_or_upstream_issue` -> `../causes/traffic-pattern-shift-or-upstream-issue.md`
- `bad_release_cpu_regression` -> `../causes/cpu-regression-after-release.md`

> 止损按问题级执行，不按单条流量告警执行。
