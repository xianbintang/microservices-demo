# 通用告警处理 SOP

> 适用范围：收到任意告警后的第一响应排查流程，不涉及业务逻辑。
> 工具依赖：mcp-grafana MCP 服务器（Grafana URL + Token 已配置）。
> 参考配置：`.claude/commands/mcp-grafana-setup.md`

---

## 前置条件

1. Grafana 可访问，mcp-grafana 配置就绪（运行 `/mcp-grafana-setup` 验证）
2. `kubectl` 已配置正确的 kubeconfig（`kubectl get nodes` 返回正常）
3. 已知告警名称（AlertManager 通知中获取）

---

## Step 1：确认告警现状

**目标**：确认哪些告警正在 firing，影响范围是什么。

使用 `list_alert_rules` 列出所有告警规则，然后用 `query_prometheus` 查询当前 firing：

```promql
# 查询所有当前 firing 的告警
ALERTS{alertstate="firing"}

# 按告警名过滤
ALERTS{alertname="AppHighLatency", alertstate="firing"}

# 查看告警的 labels（了解影响的服务/Pod）
ALERTS{alertstate="firing", namespace="online-boutique"}
```

**输出关注点**：
- `alertname`：告警名称
- `service` / `pod` / `container`：影响的具体资源
- `namespace`：命名空间

---

## Step 2：指标排查

**目标**：通过 Prometheus 指标确认异常的量化程度，缩小排查范围。

### 2.1 延迟排查

```promql
# P99 请求延迟（spanmetrics，按服务聚合）
histogram_quantile(0.99,
  sum(rate(traces_spanmetrics_duration_milliseconds_bucket[5m])) by (service_name, le)
)

# 按服务和 span_name 细化
histogram_quantile(0.99,
  sum(rate(traces_spanmetrics_duration_milliseconds_bucket[5m])) by (service_name, span_name, le)
)
```

### 2.2 错误率排查

```promql
# 各服务错误率（HTTP 5xx）
sum(rate(traces_spanmetrics_calls_total{status_code="STATUS_CODE_ERROR"}[5m])) by (service_name)
/
sum(rate(traces_spanmetrics_calls_total[5m])) by (service_name)

# gRPC 错误（非 OK 状态码）
sum(rate(traces_spanmetrics_calls_total{rpc_grpc_status_code!="0"}[5m])) by (service_name, rpc_grpc_status_code)
```

### 2.3 CPU / 内存排查

```promql
# CPU 节流率（按容器）
sum(rate(container_cpu_cfs_throttled_periods_total{namespace="online-boutique"}[5m]))
  by (pod, container)
/
sum(rate(container_cpu_cfs_periods_total{namespace="online-boutique"}[5m]))
  by (pod, container)

# CPU 使用量（单位 core）
sum(rate(container_cpu_usage_seconds_total{namespace="online-boutique"}[5m]))
  by (pod, container)

# 内存使用量（单位 MiB）
container_memory_working_set_bytes{namespace="online-boutique"}
  / 1024 / 1024
```

**输出关注点**：确认哪个服务/容器的指标超过正常基线，记录异常的时间点。

---

## Step 3：日志排查

**目标**：从 Loki 日志中找到与指标异常时间点对应的错误事件。

使用 `query_loki_logs`，常用 LogQL：

```logql
# 查询某 namespace 的 error 日志（最近 5 分钟）
{namespace="online-boutique"} |= "error" | json

# 查询特定 Pod 的日志
{namespace="online-boutique", pod=~"redis-cart-.*"} |= "timeout"

# 查找 exception / panic
{namespace="online-boutique"} |~ "(?i)(exception|panic|fatal|timeout)"

# 查找特定服务的请求错误
{namespace="online-boutique", app="frontend"} |= "error" | logfmt | status >= 500

# 统计错误日志出现频率
sum(count_over_time({namespace="online-boutique"} |= "error" [1m])) by (app)
```

**输出关注点**：
- 第一条错误日志的时间戳（与指标异常时间对齐）
- 错误消息内容（timeout / connection refused / OOM）
- 报错的服务名

---

## Step 4：链路追踪排查

**目标**：通过 Trace 找到具体的慢请求或错误请求。

使用 `find_slow_requests` 查找慢请求：
- 指定 `service`、`operation`、时间范围
- 重点关注 P99 以上的 Trace

使用 `find_error_pattern_logs` 查找 Loki 中的错误模式：
- 可按时间范围和关键词过滤
- 自动聚合相似错误模式

**Tempo TraceQL 参考（在 Grafana Explore 中手动执行）**：
```traceql
# 查找特定服务的错误 span
{ resource.service.name = "frontend" && status = error }

# 查找慢 span（> 1s）
{ resource.service.name = "checkoutservice" && duration > 1s }
```

---

## Step 5：关联分析

**目标**：将 metrics 异常时间点与 log 事件对齐，建立因果关系。

1. 从 Step 2 确定指标开始异常的 Unix 时间戳 T0
2. 在 Step 3 中以 T0 为基准，查找 T0 前后 2 分钟内的关键日志
3. 判断：是日志错误触发了指标异常，还是指标异常在前？
4. 追溯上游调用方：如果 serviceA 有错，检查其依赖（redis、其他 gRPC 服务）是否更早出现异常

**时间关联技巧**：在 Grafana Explore 中同时打开 Prometheus 和 Loki，启用 Split View，用游标对齐时间轴。

---

## 常用 PromQL 速查表

| 场景 | PromQL |
|------|--------|
| 当前 firing 告警 | `ALERTS{alertstate="firing"}` |
| P99 延迟（ms） | `histogram_quantile(0.99, sum(rate(traces_spanmetrics_duration_milliseconds_bucket[5m])) by (service_name, le))` |
| 错误率 | `sum(rate(traces_spanmetrics_calls_total{status_code="STATUS_CODE_ERROR"}[5m])) by (service_name) / sum(rate(traces_spanmetrics_calls_total[5m])) by (service_name)` |
| CPU 节流率 | `sum(rate(container_cpu_cfs_throttled_periods_total[5m])) by (pod) / sum(rate(container_cpu_cfs_periods_total[5m])) by (pod)` |
| Pod 重启次数 | `kube_pod_container_status_restarts_total{namespace="online-boutique"}` |
| OOMKill | `kube_pod_container_status_last_terminated_reason{reason="OOMKilled"}` |

---

## 常用 LogQL 速查表

| 场景 | LogQL |
|------|-------|
| namespace error 日志 | `{namespace="online-boutique"} \|= "error"` |
| 特定 Pod 日志 | `{namespace="online-boutique", pod="<pod-name>"}` |
| timeout 关键词 | `{namespace="online-boutique"} \|= "timeout"` |
| exception/panic | `{namespace="online-boutique"} \|~ "(?i)(exception\|panic\|fatal)"` |
| HTTP 5xx | `{namespace="online-boutique", app="frontend"} \| logfmt \| status >= 500` |
| 错误日志速率 | `sum(count_over_time({namespace="online-boutique"} \|= "error" [1m])) by (app)` |

---

## 排查完成后

- 若根因已定位 → 参考 [`../rca/rca-guide.md`](../rca/rca-guide.md) 撰写 RCA 报告
- 若根因是 CPU 高负载 → 参考 [`../business/high-cpu-runbook.md`](../business/high-cpu-runbook.md)
- 若需要重启 Pod → 参考 [`../ops/delete-pod.md`](../ops/delete-pod.md)
