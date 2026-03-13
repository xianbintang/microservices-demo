# Alert Playbook: ServiceHighCPUUtilization

## 1. 告警现象 (What's Happening?)

- **告警名**: `ServiceHighCPUUtilization`
- **触发条件**: 服务 CPU / CPU limit > **45%**，持续 **1m**
- **潜在影响**: 可能继续演化为延迟升高、错误率升高、流量下降

## 2. 可能原因 (Why?)

1. `cpu_overload_injection`（混沌注入）
2. `traffic_hotspot_cpu_saturation`（真实流量热点）
3. `bad_release_cpu_regression`（发布/配置回归）
4. `noisy_alert_rule`（阈值或窗口过紧）

## 3. 排查方法 (How to Troubleshoot)

按顺序执行：

1. **先查是否有级联告警**：`ServiceHighLatencyP99` / `ServiceHighErrorRate` / `ServiceTrafficDrop`
2. **查注入证据**（优先假设）：
   - `chaos.alarmkeeper.io/fault-type=cpu-overload`
   - `chaos-cpu-hog`
   - `CHAOS_CPU_OVERLOAD_ACTIVE`
3. **查变更相关性**：告警时间附近是否发布或改配置
4. **查容量与负载**：QPS、HPA、CPU throttling 走势

## 4. 根因路由与止损入口

- `cpu_overload_injection` -> `../causes/cpu-overload-injection.md`
- `traffic_hotspot_cpu_saturation` -> `../causes/cpu-saturation-by-traffic.md`
- `bad_release_cpu_regression` -> `../causes/cpu-regression-after-release.md`
- `noisy_alert_rule` -> `../causes/noisy-alert-rule.md`

> 执行动作前必须做 Incident 级去重：`../policies/incident-dedup-and-idempotency.md`
