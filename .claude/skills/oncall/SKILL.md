---
name: oncall
description: 通用告警值班数字员工，持续监控线上告警，发现告警后按 Runbook 自动止损（删除 Pod、分析根因）。无告警则每 60 秒巡检一次。用法：/oncall [interval=60s] [namespace=online-boutique]
license: MIT
compatibility:
  claude_code: ">=1.0"
metadata:
  author: xianb
  version: 1.0.0
  generatedBy: claude-sonnet-4-6
---

# 告警值班数字员工

持续监控 Prometheus 告警状态，无告警时定期巡检，发现已知类型告警则按 Runbook 自动止损，未知告警则分析并上报。

## 用法

```
/oncall [interval=60s] [namespace=online-boutique]
```

### 参数

- `interval`: 可选，无告警时的巡检间隔（默认 `60s`，支持 `30s`/`60s`/`2m`/`5m`）
- `namespace`: 可选，监控的业务命名空间（默认 `online-boutique`）

---

## 状态机

```
IDLE
  ↓ 每 interval 秒
POLLING ──── 无告警 ──→ IDLE（输出"巡检正常"）
  ↓ 发现 firing 告警
ANALYZING（查 metrics + logs）
  ↓
  ├── 已知止损路径 ──→ MITIGATING（执行止损）──→ MONITORING_RECOVERY
  └── 未知/复杂告警 ──→ 上报分析结论，等待人工介入，继续 POLLING
```

---

## 执行步骤

### 步骤 0：解析参数，打印值班开始横幅

从 `$ARGUMENTS` 解析 `interval`（默认 `60`，单位秒）和 `namespace`（默认 `online-boutique`）。

输出：

```
╔══════════════════════════════════════════╗
║         🚨 告警值班员 已上线              ║
╠══════════════════════════════════════════╣
║  命名空间: online-boutique               ║
║  巡检间隔: 60s                           ║
║  Runbook:  docs/runbook/                 ║
║  开始时间: 2026-03-10 14:00:00           ║
╚══════════════════════════════════════════╝

按 Ctrl+C 或关闭对话结束值班。
```

---

### 步骤 1：巡检轮次开始

输出当前轮次和时间戳：

```
─────────────────────────────────────────
🔍 巡检轮次 #N  [2026-03-10 14:01:00]
─────────────────────────────────────────
```

---

### 步骤 2：查询当前 Firing 告警

使用 mcp-grafana 工具 `query_prometheus` 查询：

```promql
ALERTS{alertstate="firing", namespace="online-boutique"}
```

同时过滤掉系统占位告警（`alertname=~"Watchdog|InfoInhibitor"`）。

**无 firing 告警时**：

```
✅ 无异常告警 — 系统正常
   (Pending: N 条 | 跳过: Watchdog)
   等待 60s 后进行下一次巡检...
```

→ 等待 interval 秒后回到步骤 1。

**有 firing 告警时**：进入步骤 3。

---

### 步骤 3：告警分类与初步分析

对每条 firing 告警，提取 `alertname`、`pod`、`container`、`service`、`severity`，按以下规则分类：

#### 已知止损路径（可自动处理）

| alertname 匹配 | 分类 | 止损动作 | Runbook |
|---------------|------|---------|---------|
| `AppCPUThrottling` 或 `ChaosCPUThrottling` | CPU 节流 | 删除目标 Pod | [high-cpu-runbook](../../docs/runbook/business/high-cpu-runbook.md) |
| `AppHighCPUUsage` 或 `ChaosHighCPUUsage` | CPU 高用量 | 删除目标 Pod（仅当同时伴随延迟或错误率告警时） | [high-cpu-runbook](../../docs/runbook/business/high-cpu-runbook.md) |
| `AppPodCrashLooping` 或 `ChaosPodCrashLooping` | Pod 崩溃循环 | 删除 Pod（触发重建） | [delete-pod](../../docs/runbook/ops/delete-pod.md) |
| `AppPodNotReady` 或 `ChaosPodNotReady` | Pod 不就绪 | 删除 Pod（仅当已 Pending > 3min） | [delete-pod](../../docs/runbook/ops/delete-pod.md) |

#### 需分析不自动操作

| alertname 匹配 | 分析重点 |
|---------------|---------|
| `AppHighLatency` 或 `ChaosHighLatency` | 查 P99 + 找级联来源 |
| `AppHighErrorRate` 或 `ChaosHighErrorRate` | 查错误率 + Loki error 日志 |
| `AppHighMemoryUsage` 或 `ChaosHighMemoryUsage` | 查内存 + OOMKill 情况 |
| 其他未知告警 | 通用排查（参考 general-alert-handling） |

输出分类结果：

```
🚨 发现 N 条 Firing 告警：
  [CRITICAL] AppCPUThrottling  pod=redis-cart-xxx  → 分类: CPU节流  止损: 删除Pod
  [WARNING]  AppHighLatency    service=frontend    → 分类: 高延迟   止损: 需分析
```

---

### 步骤 4：指标快速核查

针对 firing 告警涉及的服务，使用 mcp-grafana `query_prometheus` 快速收集证据：

```promql
# 4.1 CPU 节流率（告警涉及的 pod/container）
sum(rate(container_cpu_cfs_throttled_periods_total{namespace="online-boutique", pod=~"<pod-name>.*"}[2m]))
  by (pod, container)
/
sum(rate(container_cpu_cfs_periods_total{namespace="online-boutique", pod=~"<pod-name>.*"}[2m]))
  by (pod, container)

# 4.2 错误率（告警涉及的服务）
sum(rate(traces_spanmetrics_calls_total{status_code="STATUS_CODE_ERROR", service_name="<service>"}[2m]))
/
sum(rate(traces_spanmetrics_calls_total{service_name="<service>"}[2m]))

# 4.3 P99 延迟
histogram_quantile(0.99,
  sum(rate(traces_spanmetrics_duration_milliseconds_bucket{service_name="<service>"}[2m])) by (service_name, le)
)
```

如果告警涉及的服务有延迟/错误率指标异常（错误率 > 1% 或 P99 > 1000ms），记录为「有用户影响」，加入止损优先级。

---

### 步骤 5：日志快速扫描（仅在错误率或延迟异常时执行）

使用 mcp-grafana `query_loki_logs` 或 `find_error_pattern_logs` 查询最近 5 分钟告警相关 Pod 的错误日志：

```logql
{namespace="online-boutique", pod=~"<pod-name>.*"} |~ "(?i)(error|timeout|fatal|panic)" | last 20
```

提取：
- 第一条错误的时间戳（与告警 firing 时间对比）
- 错误关键词（timeout / connection refused / OOM）
- 受影响的上下游调用

---

### 步骤 6：止损执行（仅针对已知止损路径）

#### 6A：CPU 节流止损（删除 Pod）

**前置确认**（自动执行，不需人工确认）：

```bash
# 确认 Pod 由 Deployment 管理（有自动重建能力）
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.metadata.ownerReferences[0].kind}'
# 输出应为 ReplicaSet

# 确认副本数 >= 1（单副本也可删，但记录会有短暂中断）
kubectl get deployment -n <namespace> -l app=<service> -o jsonpath='{.items[0].spec.replicas}'
```

**执行删除**：

```bash
kubectl delete pod <pod-name> -n <namespace>
```

**输出**：

```
🔧 [止损] 执行删除 Pod: redis-cart-xxx (CPU节流 85%)
   依据: AppCPUThrottling firing | 节流率 85% | 持续 > 5min
   Runbook: docs/runbook/business/high-cpu-runbook.md
   执行: kubectl delete pod redis-cart-xxx -n online-boutique
   ✅ Pod 删除指令已发出，等待新 Pod 就绪...
```

#### 6B：Pod 崩溃循环止损（删除 Pod 触发重建）

```bash
kubectl delete pod <pod-name> -n <namespace>
```

输出与 6A 格式一致，依据改为 `CrashLoopBackOff N 次`。

#### 6C：需人工介入（高延迟/高错误率）

输出分析结论和建议，不自动操作：

```
📊 [分析结论] AppHighLatency — frontend P99 = 3200ms
   根因推断: checkoutservice → cartservice → redis-cart 级联超时
   证据:
     - [Metrics] redis-cart CPU节流率 85%（T-3min）
     - [Logs] cartservice: "redis: connection pool timeout"
   建议止损: 参考 docs/runbook/business/high-cpu-runbook.md
   ⚠️ 已知止损路径需确认影响范围，建议人工执行止损后观察。
   （如已有 AppCPUThrottling 并自动止损，本告警可能随之恢复）
```

---

### 步骤 7：恢复监控（止损后）

止损操作后，进入恢复观察循环（最多 5 轮，每轮 30 秒）：

```bash
# 等待新 Pod Ready
kubectl get pod -n <namespace> -l app=<service> -o jsonpath='{.items[0].status.conditions[?(@.type=="Ready")].status}'
```

同时用 `query_prometheus` 监控恢复曲线：

```promql
# 节流率回落情况
sum(rate(container_cpu_cfs_throttled_periods_total{namespace="online-boutique", pod=~"<new-pod>.*"}[1m]))
  by (pod)
/
sum(rate(container_cpu_cfs_periods_total{namespace="online-boutique", pod=~"<new-pod>.*"}[1m]))
  by (pod)

# P99 回落
histogram_quantile(0.99,
  sum(rate(traces_spanmetrics_duration_milliseconds_bucket{service_name="<service>"}[1m])) by (service_name, le)
)
```

每 30 秒输出一行恢复状态：

```
⏳ 恢复观察 [1/5] +30s  新Pod: Running(1/1) | 节流率: 12% ↓ | P99: 450ms ↓
⏳ 恢复观察 [2/5] +60s  新Pod: Running(1/1) | 节流率:  3% ↓ | P99:  80ms ✅
✅ 恢复确认：AppCPUThrottling 告警已 resolved，P99 < 100ms
```

若 5 轮后仍未恢复，输出升级提示：

```
⚠️ [升级] 止损后 2.5min 仍未完全恢复
   当前状态: 节流率 55% | P99 1200ms
   建议: 调整 CPU Limit 或 HPA 扩容
   参考: docs/runbook/business/high-cpu-runbook.md#step-7
```

---

### 步骤 8：轮次结束，等待下一次巡检

输出本轮摘要：

```
─────────────────────────────────────────
📋 巡检 #N 摘要 [耗时 45s]
   告警: 2 条 Firing（已处理 1 / 待人工 1）
   止损: redis-cart Pod 删除 → 已恢复 ✅
   上报: AppHighLatency frontend → 待人工确认
─────────────────────────────────────────
💤 等待 60s 后开始下一次巡检...
```

等待 interval 秒，回到步骤 1。

---

## 止损决策原则

**自动止损仅在以下条件全部满足时执行**：

1. 告警 alertname 明确匹配已知止损路径（见步骤 3 表格）
2. 目标 Pod 由 Deployment/ReplicaSet 管理（非裸 Pod、非 StatefulSet 有状态数据服务）
3. 节流率 > 50% 或 CrashLoop 重启次数 > 3（有量化证据）
4. 副本数 >= 1（删除不会导致完全不可用，或即便单副本也接受短暂中断）

**以下情况不自动操作，仅上报分析**：

- StatefulSet Pod（如 `redis-cart-0`，数据持久化服务）
- 仅有延迟/错误率告警，无 CPU/内存资源类告警（根因不明确）
- 未知告警名称（不在规则表中）
- 同一 Pod 本次值班已操作过 2 次（防止反复重启掩盖根本原因）

---

## mcp-grafana 工具使用清单

| 步骤 | mcp-grafana 工具 | 用途 |
|------|----------------|------|
| 步骤 2 | `query_prometheus` | 查询 `ALERTS{alertstate="firing"}` |
| 步骤 4 | `query_prometheus` | CPU 节流率、错误率、P99 延迟 |
| 步骤 5 | `query_loki_logs` / `find_error_pattern_logs` | 错误日志扫描 |
| 步骤 7 | `query_prometheus` | 恢复曲线监控 |
| 可选 | `find_slow_requests` | 链路追踪慢请求分析 |
| 可选 | `list_alert_rules` | 查看所有告警规则定义 |

---

## 核心原则

**告警名不等于根因** — 告警名包含 "Chaos" 不代表是混沌实验导致，须以 metrics + logs 时间序列为判断依据。

**最小化自动操作** — 只对有充分量化证据、有明确恢复路径的告警自动止损，其余上报人工。

**止损后必须验证** — 每次操作后进入恢复观察循环，确认指标回落后才结束本轮处理。

---

## 验收标准

- [x] 无告警时按 interval 循环巡检，不产生噪音输出
- [x] 使用 mcp-grafana `query_prometheus` 查询 ALERTS（不依赖 port-forward）
- [x] 正确过滤 Watchdog / InfoInhibitor 占位告警
- [x] 按告警分类表区分「自动止损」和「人工上报」
- [x] CPU 节流止损前确认 Pod 控制器类型（防误删 StatefulSet）
- [x] 止损后进入恢复观察循环（最多 5 轮 × 30s）
- [x] 同一 Pod 本次值班最多自动操作 2 次
- [x] 输出格式结构化，每轮有摘要

---

## 相关文档

- [通用告警处理 SOP](../../docs/runbook/alert-runbook/general-alert-handling.md)
- [CPU 高负载 Runbook](../../docs/runbook/business/high-cpu-runbook.md)
- [删除 Pod 操作手册](../../docs/runbook/ops/delete-pod.md)
- [RCA 报告指南](../../docs/runbook/rca/rca-guide.md)
