# 业务 Runbook：CPU 高负载处理

> 场景：CPU 节流率或 CPU 使用量告警 firing，伴随下游延迟或错误率上升。
> 引用文档：[通用告警处理](../alert-runbook/general-alert-handling.md) | [删除 Pod](../ops/delete-pod.md) | [RCA 指南](../rca/rca-guide.md)

---

## 触发条件

以下任一组合触发本 Runbook：

| 告警 | 条件 |
|------|------|
| `AppCPUThrottling` | CPU 节流率 > 50% 持续 5 分钟 |
| `AppHighCPUUsage` | CPU 使用量 > 0.5 core 持续 5 分钟 |
| 伴随 | `AppHighLatency`（P99 > 500ms）或 `AppHighErrorRate`（错误率 > 1%）|

---

## 响应流程

### Step 1：确认影响面

按照[通用告警处理 SOP](../alert-runbook/general-alert-handling.md) Step 1-2 执行。

重点查询 P99 延迟变化曲线（使用 mcp-grafana `query_prometheus`）：

```promql
# 查看所有服务 P99 延迟趋势（最近 30 分钟，1 分钟粒度）
histogram_quantile(0.99,
  sum(rate(traces_spanmetrics_duration_milliseconds_bucket[1m])) by (service_name, le)
)
```

**判断影响面**：
- 仅 1 个服务延迟高 → 局部问题，直接进入 Step 2
- 多个服务延迟级联升高 → 级联故障，优先找最底层（依赖链末端）的异常服务

### Step 2：定位受影响 Pod

```promql
# 查找 CPU 节流率 > 50% 的容器（namespace=online-boutique）
sum(rate(container_cpu_cfs_throttled_periods_total{namespace="online-boutique"}[5m]))
  by (pod, container)
/
sum(rate(container_cpu_cfs_periods_total{namespace="online-boutique"}[5m]))
  by (pod, container)
> 0.5
```

记录结果：节流率最高的 `pod` 和 `container` 名称。

```bash
# 确认 Pod 状态和重启次数
kubectl get pod <pod-name> -n online-boutique
```

### Step 3：评估是否需要重启

| 条件 | 建议操作 |
|------|---------|
| 节流率 > 80% 且持续 > 10 分钟 | 立即重启 Pod |
| 节流率 50-80% 且 P99 > 500ms | 重启 Pod，同时评估 CPU limit |
| Pod 重启次数 > 5 | 重启 Pod 同时排查根本原因（代码死循环？内存泄漏？） |
| 节流率 < 50% 且 P99 < 200ms | 观察 15 分钟，无需立即操作 |

### Step 4：执行删除操作

按照 [删除 Pod 操作手册](../ops/delete-pod.md) 执行。

**快速参考**：
```bash
# 删除节流的 Pod（Deployment 管理，自动重建）
kubectl delete pod <pod-name> -n online-boutique

# 观察新 Pod 启动
kubectl get pod -n online-boutique -w
```

### Step 5：观察恢复

新 Pod Ready 后，用 mcp-grafana 监控关键指标回落：

```promql
# P99 延迟是否回落到基线（< 100ms）
histogram_quantile(0.99,
  sum(rate(traces_spanmetrics_duration_milliseconds_bucket[2m])) by (service_name, le)
)

# CPU 节流率是否回落
sum(rate(container_cpu_cfs_throttled_periods_total{namespace="online-boutique", pod=~"<new-pod-name>.*"}[2m]))
  by (pod, container)
/
sum(rate(container_cpu_cfs_periods_total{namespace="online-boutique", pod=~"<new-pod-name>.*"}[2m]))
  by (pod, container)
```

**预期恢复时间**：Pod 重建后约 1-3 分钟内指标应回落到基线。

### Step 6：恢复确认

确认以下告警状态变为 resolved（查询 Alertmanager 或 `ALERTS{alertstate="firing"}`）：
- `AppCPUThrottling` resolved
- `AppHighLatency` resolved
- `AppHighErrorRate` resolved（如有）

### Step 7：未恢复时升级处理

若删除 Pod 后 5 分钟内指标仍未回落：

**选项 A：调整 CPU Limit**
```bash
# 临时上调 CPU limit（示例：从 200m 调整到 500m）
kubectl set resources deployment/<name> -n online-boutique \
  --limits=cpu=500m --requests=cpu=200m
```

**选项 B：HPA 扩容**
```bash
# 临时扩容副本数分散负载
kubectl scale deployment/<name> -n online-boutique --replicas=3
```

**选项 C：升级排查**
- 参考[通用告警处理 SOP](../alert-runbook/general-alert-handling.md) Step 3-5 进行日志和链路追踪分析
- 若发现是代码 bug（死循环、低效算法），需走代码修复流程

---

## 实际案例复盘（2026-03-10）

### 案例：redis-cart CPU 节流 → 级联延迟

**现象**：
- `AppCPUThrottling` firing（redis-cart 节流率 > 80%）
- `AppHighLatency` firing（cartservice P99 > 1s）
- `AppHighLatency` firing（checkoutservice P99 > 2s）
- `AppHighLatency` firing（frontend P99 > 3s）

**根因链**：
```
redis-cart CPU 节流（节流率 85%）
  ↓ Redis 命令处理延迟 > 客户端超时阈值
  ↓ cartservice Redis 操作超时 → FailedPrecondition 错误
  ↓ checkoutservice 调用 cartservice 超时 → P99 上升
  ↓ frontend 请求 checkoutservice → 用户可感知延迟上升
```

**处理结果**：
- 删除 redis-cart Pod → 新 Pod Ready（约 45s）
- 2 分钟内 P99 全部回落到 < 50ms
- 所有告警 resolved

**后续建议**：
- 调整 redis-cart CPU limit 从 200m 到 500m（已执行）
- 考虑 Redis 迁移到独立节点避免资源竞争

---

## 相关文档

- [通用告警处理 SOP](../alert-runbook/general-alert-handling.md)
- [删除 Pod 操作手册](../ops/delete-pod.md)
- [RCA 报告指南](../rca/rca-guide.md)
