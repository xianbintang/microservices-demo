# Alert Playbook: AppHighCPUUsage

## 1. 告警现象 (What's Happening?)

- **告警名**: `AppHighCPUUsage`（兼容 `ChaosHighCPUUsage`）
- **触发条件（规则来源）**: 容器 CPU 用量超过阈值（当前规则约 0.1 core）
- **特点**: 这是“资源占用高”信号，不一定已造成用户故障

---

## 2. 可能原因 (Why?)

1. **混沌注入导致固定 CPU 压力**（`cpu_overload_injection`）
2. **短时流量峰值**（`traffic_hotspot_cpu_saturation`）
3. **发布后 CPU 回归**（`bad_release_cpu_regression`）
4. **告警阈值偏保守**（`noisy_high_cpu_usage_rule`）

---

## 3. 排查方法 (How to Troubleshoot)

### 步骤 1：与节流/业务告警做关联

如果同时存在以下任意告警，说明问题已升级：
- `AppCPUThrottling`
- `AppHighLatency`
- `AppHighErrorRate`

若仅 `AppHighCPUUsage` 单独触发，先观察趋势并定位根因，不急于执行高风险动作。

### 步骤 2：识别是否混沌注入

复用 `AppCPUThrottling` Playbook 中的注入证据检查：
- 注解 `chaos.alarmkeeper.io/fault-type=cpu-overload`
- 容器 `chaos-cpu-hog`
- 日志前缀 `CHAOS_CPU_OVERLOAD_ACTIVE`

### 步骤 3：判断是否容量问题

检查 5~15 分钟趋势：
- CPU usage 持续高位
- throttling 开始上升
- P99/错误率是否跟随恶化

若趋势持续恶化，则优先按“即将故障”处理。

---

## 4. 根因路由与止损入口

| 命中根因 `cause_id` | 跳转 Runbook |
|---|---|
| `cpu_overload_injection` | `../causes/cpu-overload-injection.md` |
| `traffic_hotspot_cpu_saturation` | `../causes/cpu-saturation-by-traffic.md` |
| `bad_release_cpu_regression` | `../causes/cpu-regression-after-release.md` |
| `noisy_high_cpu_usage_rule` | `../causes/noisy-alert-rule.md` |

> 对 `AppHighCPUUsage` 不建议单独触发“删除 Pod”作为默认动作；优先通过根因 Runbook 在 Incident 级别决策止损。

---

## 5. 输出模板（给虚拟员工）

```text
[Alert Triage]
alert=AppHighCPUUsage
scope=namespace=<ns>, pod=<pod>, service=<svc>
co_alerts=[AppCPUThrottling, AppHighLatency, ...]
classified_cause=<cause_id>
next_runbook=<path>
```
