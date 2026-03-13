# Alert Playbook: ServiceTrafficSpike

## 1. 告警现象 (What's Happening?)

- **告警名**: `ServiceTrafficSpike`
- **触发条件**: 1m 流量 / 30m 基线 > **2.5**（且基线 > 0.2），持续 **1m**
- **潜在影响**: 容量不足导致 CPU、延迟、错误率上升

## 2. 可能原因 (Why?)

1. `traffic_pattern_shift_or_upstream_issue`（上游流量激增）
2. `traffic_hotspot_cpu_saturation`（热点导致局部过载）
3. `bad_release_cpu_regression`（发布导致重试风暴）
4. `noisy_alert_rule`（低流量服务下的统计噪声）

## 3. 排查方法 (How to Troubleshoot)

1. 识别激增服务和来源（入口、租户、接口）
2. 看是否伴随 CPU、延迟、错误率告警
3. 查是否有上游批任务/重试/网关策略变更
4. 评估是否需要限流、扩容或降级

## 4. 根因路由与止损入口

- `traffic_pattern_shift_or_upstream_issue` -> `../causes/traffic-pattern-shift-or-upstream-issue.md`
- `traffic_hotspot_cpu_saturation` -> `../causes/cpu-saturation-by-traffic.md`
- `bad_release_cpu_regression` -> `../causes/cpu-regression-after-release.md`
- `noisy_alert_rule` -> `../causes/noisy-alert-rule.md`

> 动作前先做 incident 去重，避免多告警重复止损。
