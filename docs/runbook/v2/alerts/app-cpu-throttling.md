# Alert Playbook: AppCPUThrottling

## 1. 告警现象 (What's Happening?)

- **告警名**: `AppCPUThrottling`（兼容 `ChaosCPUThrottling`）
- **触发条件（规则来源）**: 容器 CPU 节流率持续高于阈值（当前规则约 50%）
- **典型影响**:
  - 请求排队、响应变慢
  - 上游服务出现超时重试
  - 可能级联触发 `AppHighLatency`、`AppHighErrorRate`

> 该 Playbook 只负责“定位与分流”，不直接定义止损动作细节。止损由根因 Runbook 统一定义，避免重复执行。

---

## 2. 可能原因 (Why?)

按优先级从高到低排查：

1. **混沌注入导致的 CPU 过载**（`cause_id: cpu_overload_injection`）
2. **真实流量高峰/热点请求导致 CPU 饱和**（`cause_id: traffic_hotspot_cpu_saturation`）
3. **近期变更导致资源回归**（`cause_id: bad_release_cpu_regression`）
4. **告警噪音/阈值过紧**（`cause_id: noisy_cpu_throttling_rule`）

---

## 3. 排查方法 (How to Troubleshoot)

> 目标：10 分钟内将告警归类到一个 `cause_id`，并路由到对应根因 Runbook。

### 步骤 1：确认是否存在用户影响

建议先看同时间窗（近 5~15 分钟）内：
- `AppHighLatency`
- `AppHighErrorRate`

判定：
- **有用户影响**：优先级升高，进入止损路径评估
- **无用户影响**：先完成根因识别，再决定是否止损

### 步骤 2：验证“混沌注入”假设（优先）

检查以下证据（满足越多置信度越高）：

1. Deployment 注解存在：
   - `chaos.alarmkeeper.io/fault-type=cpu-overload`
   - `chaos.alarmkeeper.io/fault-id`
   - `kubernetes.io/change-cause` 包含 `chaos inject-cpu-overload`
2. Pod 容器列表包含 `chaos-cpu-hog`
3. `chaos-cpu-hog` 日志包含前缀：
   - `CHAOS_CPU_OVERLOAD_ACTIVE fault_id=...`

若证据成立，归类为：`cpu_overload_injection`。

### 步骤 3：检查是否与近期变更重合

关注告警开始时间前后是否发生：
- 新版本发布
- 动态配置修改
- 资源规格（requests/limits）调整

若高度重合且无混沌证据，优先归类：`bad_release_cpu_regression`。

### 步骤 4：检查流量热点与容量不足

观察：
- QPS 是否突增
- 某 endpoint/租户是否热点集中
- HPA 是否已打满上限
- CPU usage 与 throttling 是否同步爬升

若成立，归类：`traffic_hotspot_cpu_saturation`。

### 步骤 5：检查告警噪音

若指标长期在阈值边界抖动、且无用户影响、且无变更/注入证据：
- 归类：`noisy_cpu_throttling_rule`

---

## 4. 根因路由与止损入口

| 命中根因 `cause_id` | 跳转 Runbook | 说明 |
|---|---|---|
| `cpu_overload_injection` | `../causes/cpu-overload-injection.md` | 故障演练注入导致 |
| `traffic_hotspot_cpu_saturation` | `../causes/cpu-saturation-by-traffic.md` | 真实流量压力 |
| `bad_release_cpu_regression` | `../causes/cpu-regression-after-release.md` | 发布/配置回归 |
| `noisy_cpu_throttling_rule` | `../causes/noisy-alert-rule.md` | 规则治理 |

> 执行动作前必须经过 Incident 去重与幂等校验：见 `../policies/incident-dedup-and-idempotency.md`。

---

## 5. 输出模板（给虚拟员工）

```text
[Alert Triage]
alert=AppCPUThrottling
scope=namespace=<ns>, pod=<pod>, service=<svc>
impact=user_impact=<yes/no>
classified_cause=<cause_id>
confidence=<high/medium/low>
next_runbook=<path>
```
