# Alert Playbook: ServiceHighLatencyP99

## 1. 告警现象 (What's Happening?)

- **告警名**: `ServiceHighLatencyP99`
- **触发条件**: P99 延迟 > **200ms** 且服务有流量（rate > 0.2），持续 **1m**
- **潜在影响**:
  - 用户页面慢、结算慢、超时增多
  - 上游重试增加，可能放大流量与资源压力
  - 进一步触发 `ServiceHighErrorRate` / `ServiceTrafficDrop` / `ServiceHighCPUUtilization`

---

## 2. 本 Runbook 的目标

该 Runbook 的目标不是“看一个指标就下结论”，而是通过**统一排查路径**，在 10~30 分钟内把延迟上涨归因到可执行的根因类别：

1. `downstream_dependency_issue`（下游依赖慢/故障）
2. `cpu_overload_injection`（CPU 注入/故障演练残留）
3. `traffic_hotspot_cpu_saturation`（真实流量热点导致 CPU/队列饱和）
4. `bad_release_cpu_regression`（发布/配置变更引入性能回归）
5. `service_memory_pressure`（内存压力、GC 抖动、OOM 前后抖动）
6. `traffic_pattern_shift_or_upstream_issue`（上游流量模式变化/入口异常）
7. `runtime_or_pool_contention`（线程池/连接池/锁竞争导致排队）
8. `noisy_alert_rule`（告警规则噪音/阈值过紧）

---

## 3. 10 分钟快排（先定方向）

### 3.1 同窗告警关联

先看同窗（同一时间段）是否同时出现：

- `ServiceHighCPUUtilization`
- `ServiceHighErrorRate`
- `ServiceHighMemoryUtilization`
- `ServiceTrafficSpike` / `ServiceTrafficDrop`

这一步用于快速判断是“资源型 / 依赖型 / 流量型 / 规则型”哪条主路径。

### 3.2 四个基础面板（必须一起看）

对告警服务（以及其关键下游）同时看：

1. P99（延迟）
2. QPS（请求速率）
3. Error Rate（错误率）
4. CPU/Memory/Throttling（资源）

> 经验：只看 P99 很容易误判。P99 + QPS + Error + 资源必须并行对照。

### 3.3 先给出临时分类（不等于最终结论）

- **P99 升 + QPS 基本稳 + 错误率低 + 某下游资源顶满** → 倾向下游瓶颈
- **P99 升 + QPS 明显升 + CPU/Throttling 升** → 倾向流量热点/容量不足
- **P99 升 + 发布后立即阶跃** → 倾向发布回归
- **告警反复抖动、业务无感** → 倾向规则噪音

---

## 4. 标准排查流程（按顺序执行）

## 4.1 锁定时间窗与影响面

记录：
- 告警开始/结束时间
- 受影响 `service_name`
- 影响范围（单服务、多服务、是否级联）

推荐查询（示例）：

```promql
histogram_quantile(
  0.99,
  sum by (le, service_name) (
    rate(traces_spanmetrics_duration_milliseconds_bucket{service_name=~".+"}[5m])
  )
)
```

## 4.2 用 Trace/Span 找“慢点归属”

先看哪个服务慢，再看哪个 span 慢：

```promql
topk(10,
  histogram_quantile(
    0.99,
    sum by (le, service_name) (
      rate(traces_spanmetrics_duration_milliseconds_bucket{service_name=~".+"}[5m])
    )
  )
)
```

```promql
topk(10,
  histogram_quantile(
    0.99,
    sum by (le, span_name) (
      rate(traces_spanmetrics_duration_milliseconds_bucket{service_name="<suspect-service>"}[5m])
    )
  )
)
```

判定要点：
- 若慢点集中在下游 RPC span（如 `xxxService/Get...`）→ 继续查下游
- 若慢点集中在服务入口 span（如 `frontend`）且下游正常 → 查本服务 runtime/资源/池化

## 4.3 判断是否“流量驱动”

```promql
sum(rate(traces_spanmetrics_calls_total{service_name="<service>"}[5m]))
```

- 若 QPS 相对基线上升明显，且 CPU/throttling 同步上升，优先走流量热点路径。
- 若 QPS 平稳但 P99 上升，优先查依赖、资源争用、注入或发布回归。

## 4.4 判断是否“错误驱动”

```promql
sum(rate(traces_spanmetrics_calls_total{service_name="<service>",status_code="STATUS_CODE_ERROR"}[5m]))
/
clamp_min(sum(rate(traces_spanmetrics_calls_total{service_name="<service>"}[5m])), 0.001)
```

- 错误率高：优先查下游超时/拒绝、连接池耗尽、发布问题。
- 错误率低但延迟高：优先查排队/资源节流/慢依赖。

## 4.5 判断是否“资源驱动”（CPU/内存/节流）

CPU 利用率（service 维度）：

```promql
sum by (service) (
  label_replace(
    rate(container_cpu_usage_seconds_total{namespace="online-boutique",container!="",container!="POD",image!="",pod=~".+-.+-.+"}[5m]),
    "service", "$1", "pod", "^(.*)-[a-z0-9]+-[a-z0-9]+$"
  )
)
/
clamp_min(
  sum by (service) (
    label_replace(
      kube_pod_container_resource_limits{namespace="online-boutique",resource="cpu",container!="",container!="POD",pod=~".+-.+-.+"},
      "service", "$1", "pod", "^(.*)-[a-z0-9]+-[a-z0-9]+$"
    )
  ),
  0.001
)
```

节流比例（按 Pod）：

```promql
sum by (pod,container) (
  rate(container_cpu_cfs_throttled_periods_total{namespace="online-boutique",container!="",container!="POD",pod=~"<service>-.+"}[5m])
)
/
clamp_min(
  sum by (pod,container) (
    rate(container_cpu_cfs_periods_total{namespace="online-boutique",container!="",container!="POD",pod=~"<service>-.+"}[5m])
  ),
  0.0001
)
```

内存与重启：

```promql
sum(container_memory_working_set_bytes{namespace="online-boutique",container!="",container!="POD",pod=~"<service>-.+"})
```

```promql
sum(kube_pod_container_status_restarts_total{namespace="online-boutique",pod=~"<service>-.+"})
```

## 4.6 判断是否“发布/配置变更驱动”

检查告警时间附近是否有发布或配置调整：

```bash
kubectl -n <namespace> rollout history deployment/<deployment>
kubectl -n <namespace> get deploy/<deployment> -o jsonpath='{.metadata.annotations.kubernetes\.io/change-cause}{"\n"}'
```

- 若指标在变更后出现阶跃式恶化，优先归入 `bad_release_cpu_regression`。

## 4.7 判断是否“注入/演练驱动”

重点检查：

- Pod/Deployment 是否存在 `chaos.alarmkeeper.io/*` 注解
- Pod 内是否存在 `CHAOS_CPU_OVERLOAD_ACTIVE` / `chaos-cpu-hog` / `yes >/dev/null`

```bash
kubectl -n <namespace> exec <pod> -- ps aux
```

若命中以上特征，可归入 `cpu_overload_injection`。

## 4.8 判断是否“依赖/网络/池化争用驱动”

日志关键词建议：

- 依赖类：`timeout`, `connection refused`, `deadline exceeded`, `pool exhausted`
- 网络/DNS：`i/o timeout`, `no route to host`, `lookup`, `TLS handshake timeout`
- 池化/并发：`thread pool queue`, `max connections reached`, `semaphore timeout`

示例（Loki）：

```logql
{namespace="online-boutique",service_name="<service>"} |= "timeout"
```

若错误不高但延迟高，且日志出现池耗尽/排队关键词，归入 `runtime_or_pool_contention`。

## 4.9 判断是否“告警噪音”

满足以下特征时考虑 `noisy_alert_rule`：

- 指标长期在阈值附近上下抖动
- 告警频繁 firing/resolved 来回切换
- 业务无明显受损（核心 SLO 未受影响）
- 无发布、无依赖故障、无资源瓶颈证据

---

## 5. 根因判定矩阵（汇总）

| 根因类别 | 典型信号 | 关键验证动作 |
|---|---|---|
| downstream_dependency_issue | 上游慢点指向下游 RPC，日志有 timeout/refused | Trace 慢 span + 下游日志/指标同窗验证 |
| cpu_overload_injection | CPU 打满、节流升高、Pod 内有注入进程特征 | `ps aux` + 注解 + 注入标识日志 |
| traffic_hotspot_cpu_saturation | QPS 上升、CPU/节流同步上升 | QPS 与资源曲线同向，且无注入证据 |
| bad_release_cpu_regression | 发布后阶跃恶化，回滚可恢复 | rollout history + 变更时间对齐 |
| service_memory_pressure | 内存高位、重启/OOM、延迟抖动 | 内存趋势 + restart/OOM 事件 |
| traffic_pattern_shift_or_upstream_issue | 上游入口异常、流量模式突变 | 上游服务/网关告警与流量曲线联动 |
| runtime_or_pool_contention | 延迟高但错误不一定高，日志有池/队列耗尽 | 线程池/连接池/锁争用日志证据 |
| noisy_alert_rule | 告警抖动且业务无感 | SLO 对照 + 历史告警 flap 频率 |

---

## 6. 根因路由与动作入口

已有根因文档：
- `downstream_dependency_issue` -> `../causes/downstream-dependency-issue.md`
- `cpu_overload_injection` -> `../causes/cpu-overload-injection.md`
- `traffic_hotspot_cpu_saturation` -> `../causes/cpu-saturation-by-traffic.md`
- `bad_release_cpu_regression` -> `../causes/cpu-regression-after-release.md`
- `service_memory_pressure` -> `../causes/service-memory-pressure.md`
- `traffic_pattern_shift_or_upstream_issue` -> `../causes/traffic-pattern-shift-or-upstream-issue.md`
- `noisy_alert_rule` -> `../causes/noisy-alert-rule.md`

新增通用归类（当前先在本文件执行）：
- `runtime_or_pool_contention`（线程池/连接池/锁竞争）

> 止损按 incident 级执行，不按告警逐条执行：`../policies/incident-dedup-and-idempotency.md`

---

## 7. 结论输出模板（建议复制）

```text
【现象】
- 告警: ServiceHighLatencyP99
- 时间窗: <start> ~ <end>
- 影响服务: <services>

【关键证据】
- P99: <value/trend>
- QPS: <value/trend>
- Error Rate: <value/trend>
- 资源(CPU/Memory/Throttling): <value/trend>
- Trace 慢点: <top spans>
- 日志关键字: <keywords>
- 变更线索: <release/config>

【根因判定】
- 根因类别: <cause_id>
- 判定理由: <2~4 条核心证据>

【止损与验证】
- 已执行动作: <actions>
- 恢复结果: <p99/error/alerts>
- 后续改进: <preventive items>
```

---

## 8. 恢复完成判定（退出事件）

连续观察 5~10 分钟，满足全部条件后可判定恢复：

1. P99 回到阈值内并稳定
2. 错误率回落到基线
3. 资源指标回落（CPU/节流/内存）
4. 关联告警 resolved
5. 根因可复现解释（不是“偶然恢复”）

---

## 9. 已验证案例参考

`cpu_overload_injection` 的实战排查案例已沉淀到：
- `../causes/cpu-overload-injection.md` 的“实战排查 Runbook”章节

可作为“同窗告警 + 指标并行 + span 定位 + Pod 内证据确认”的标准样例。

---

## 10. 注意事项

- 不要在证据不足时直接归因为“下游慢”或“流量大”。
- 不要仅凭单一指标（只看 P99 或只看 CPU）做决策。
- 先保业务，再做根因闭环；止损动作必须可审计、可回放。
- 如需跨团队协作，先给出结构化证据包（时间窗 + 指标 + trace + 日志 + 变更）。

这样能显著减少反复沟通与误判成本。
