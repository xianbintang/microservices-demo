# 根因分析（RCA）操作手册

> 适用时机：完成告警排查，掌握足够 metrics/logs/tracing 证据后，输出 RCA 报告。
> 前置文档：[通用告警处理 SOP](../alert-runbook/general-alert-handling.md)

---

## RCA 五步法

### Step 1：现象收集

列出所有告警和观测到的异常：
- 哪些告警在何时 firing（从 `ALERTS{alertstate="firing"}` 获取时间戳）
- 用户可感知的影响（P99 延迟升高、错误率升高、服务不可用）
- 影响的服务列表和命名空间

**输出格式**：
```
现象摘要：
- [时间] 告警 X firing，影响服务 A
- [时间] 告警 Y firing，影响服务 B
- 用户影响：frontend P99 从 XXms 升至 XXXms
```

### Step 2：时间线梳理

**方法**：用 Prometheus 时间戳将所有异常事件排序。

```promql
# 各告警首次 firing 时间（通过 Grafana 查看时间序列）
ALERTS{alertstate="firing"} offset 0

# 各服务 P99 开始上升的时间点
histogram_quantile(0.99, sum(rate(traces_spanmetrics_duration_milliseconds_bucket[1m])) by (service_name, le))
```

从 Loki 找到第一条错误日志的时间戳，与 Prometheus 时间点对比。

**时间线表格模板**：

| 时间（相对 T0） | 事件 | 来源 |
|--------------|------|------|
| T0 - 0min | [根因事件] | Prometheus / Loki |
| T0 + 1min | 服务 X 错误率开始上升 | Prometheus |
| T0 + 2min | 告警 Y firing | Alertmanager |
| T0 + 3min | 用户可感知影响出现 | Prometheus P99 |

### Step 3：因果链推导

根据时间线，从最早的异常事件向后追溯，建立因果链。

**通用因果链模板（微服务级联故障）**：

```
资源异常（CPU 节流 / OOM / 磁盘满）
  ↓
中间件超时（Redis timeout / DB slow query / 消息队列积压）
  ↓
直接依赖服务错误（gRPC FailedPrecondition / connection refused）
  ↓
上游服务延迟上升（P99 ↑，重试风暴加剧）
  ↓
用户可感知影响（frontend P99 ↑，成功率下降）
```

**注意**：因果方向是从底层资源向上游传播，排查时反向追溯（从告警 → 找直接原因 → 找根因）。

### Step 4：根因确认

根因须满足以下条件：
1. **时间上最早**：在所有异常中最先出现
2. **可解释后续异常**：移除该原因，后续异常理论上不会发生
3. **有直接证据**：有 metrics + logs 双重证据支撑

**证据三角**（每个因果节点都应具备）：
- **Metrics 证据**：Prometheus 时间序列显示指标异常（CPU 节流率、错误率、延迟）
- **Logs 证据**：Loki 日志显示对应错误消息（timeout、OOM、connection refused）
- **可选 Tracing 证据**：Tempo 中的慢 Trace 或错误 Trace

### Step 5：证据标注

在报告中，每个结论都需要标注证据来源：

```markdown
**根因**：redis-cart 容器 CPU 节流（节流率 > 80%），导致 Redis 命令处理延迟超过客户端超时阈值。

证据：
- [Metrics] `container_cpu_cfs_throttled_periods_total` 显示 redis-cart 节流率在 T0 达到 85%
- [Logs] redis-cart Pod 日志：`BUSY Redis is busy running a script`（T0 + 30s）
- [Metrics] cartservice `traces_spanmetrics_calls_total{status_code="STATUS_CODE_ERROR"}` 在 T0 + 1min 开始上升
```

---

## 重要提醒：命名陷阱

**告警名称 / label 命名不能作为根因判断依据。**

例如：告警名包含 "Chaos" 字样，不代表根因一定是混沌实验注入。告警名是人为定义的字符串，可能：
- 来自历史遗留的命名规范
- 被复用于真实故障场景

**正确做法**：以 Prometheus metrics 时间序列和 Loki 日志内容为根因判断的唯一依据。

---

## RCA 报告模板

```markdown
# RCA 报告：[告警名称或故障描述]

**日期**：YYYY-MM-DD
**严重级别**：P1 / P2 / P3
**持续时间**：HH:MM - HH:MM（约 N 分钟）
**撰写人**：

---

## 1. 现象

- 受影响服务：
- 用户影响：
- 告警列表：
  - `AlertName` firing at HH:MM

## 2. 时间线

| 时间 | 事件 | 来源 |
|------|------|------|
| T+0  |      |      |
| T+N  |      |      |

## 3. 根因链

[描述从根因到用户影响的完整因果链]

```
根因 → 中间影响 → 用户影响
```

## 4. 证据

### 根因证据
- [Metrics] ...
- [Logs] ...

### 关联证据
- [Metrics] ...

## 5. 后续建议

- [ ] 短期缓解：[如调整 CPU limit、HPA 扩容]
- [ ] 中期修复：[如优化服务性能、添加熔断]
- [ ] 长期改进：[如容量规划、告警阈值调整]
```

---

## 参考链接

- [通用告警处理 SOP](../alert-runbook/general-alert-handling.md)
- [删除 Pod 操作手册](../ops/delete-pod.md)
- [CPU 高负载 Runbook](../business/high-cpu-runbook.md)
