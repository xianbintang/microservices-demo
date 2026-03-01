---
description: 查看 Online Boutique 系统的 Tracing、Metrics、Logs，生成观测报告，发现异常。用法：/obs-check [时间窗口，默认 5m，例如 30m、1h]
---

## 任务

对 Online Boutique 微服务系统进行全面的可观测性巡检，覆盖 Metrics、Tracing Pipeline、Logs、告警状态和资源使用。

时间窗口参数：`$ARGUMENTS`（若为空则默认使用 `5m`）

## 执行步骤

### 步骤 1：确定时间窗口

从 `$ARGUMENTS` 中解析时间窗口。支持格式：`5m`、`30m`、`1h` 等 Prometheus duration 格式。若为空，默认 `5m`。

### 步骤 2：获取基础状态

并行执行以下检查：

1. **Pod 状态检查**
   ```bash
   kubectl get pods -n online-boutique --no-headers | awk '{print $1, $2, $3, $5}'
   kubectl get pods -n monitoring --no-headers | awk '{print $1, $2, $3, $5}'
   ```

2. **启动 Prometheus 端口转发**（查询完成后关闭）
   ```bash
   kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 19090:9090 &
   sleep 3
   ```

### 步骤 3：写入并执行观测查询脚本

将以下 Python 脚本写入 `/tmp/obs_check_run.py`，然后执行。脚本中 `TIME_WINDOW` 替换为步骤 1 解析的时间窗口。

```python
#!/usr/bin/env python3
import urllib.request
import urllib.parse
import json

TIME_WINDOW = "5m"  # 由调用方替换

PROM = "http://localhost:19090"

def prom_query(q):
    url = f"{PROM}/api/v1/query?" + urllib.parse.urlencode({"query": q})
    handler = urllib.request.ProxyHandler({})
    opener = urllib.request.build_opener(handler)
    try:
        with opener.open(url, timeout=10) as r:
            return json.load(r)["data"]["result"]
    except Exception as e:
        return []

def prom_alerts():
    url = f"{PROM}/api/v1/alerts"
    handler = urllib.request.ProxyHandler({})
    opener = urllib.request.build_opener(handler)
    try:
        with opener.open(url, timeout=10) as r:
            return json.load(r)["data"]["alerts"]
    except Exception as e:
        return []

def safe_float(v):
    try:
        f = float(v)
        return 0 if f != f else f
    except:
        return 0

W = TIME_WINDOW

print("=" * 65)
print(f"  Online Boutique 系统观测报告 (最近 {W})")
print("=" * 65)

# ── 发现可用的 spanmetrics 指标名 ──────────────────────────────
def find_metric(pattern):
    results = prom_query(f'count by (__name__) ({{__name__=~"{pattern}"}})')
    return [r["metric"].get("__name__", "") for r in results]

calls_candidates = find_metric("traces_spanmetrics_calls.*total$")
dur_candidates   = find_metric("traces_spanmetrics_duration.*bucket$")
calls_metric = calls_candidates[0] if calls_candidates else None
duration_metric = dur_candidates[0] if dur_candidates else None

# ── 1. 请求速率 ────────────────────────────────────────────────
print(f"\n{'─'*65}")
print(f"1. 请求速率 RPS (最近 {W})")
print(f"{'─'*65}")
if calls_metric:
    results = prom_query(f'sum by (service_name) (rate({calls_metric}[{W}]))')
    if results:
        for r in sorted(results, key=lambda x: safe_float(x["value"][1]), reverse=True):
            svc = r["metric"].get("service_name", "unknown")
            val = safe_float(r["value"][1])
            print(f"  {svc:<38} {val:7.3f} rps")
    else:
        print("  (暂无 spanmetrics 数据，otel-collector 可能未就绪)")
else:
    print("  (未找到 traces_spanmetrics_calls 指标)")

# ── 2. 错误率 ─────────────────────────────────────────────────
print(f"\n{'─'*65}")
print(f"2. 错误率 (最近 {W})")
print(f"{'─'*65}")
any_error = False
if calls_metric:
    results = prom_query(
        f'sum by (service_name) (rate({calls_metric}{{status_code="STATUS_CODE_ERROR"}}[{W}]))'
        f' / sum by (service_name) (rate({calls_metric}[{W}])) * 100'
    )
    for r in sorted(results, key=lambda x: safe_float(x["value"][1]), reverse=True):
        svc = r["metric"].get("service_name", "unknown")
        val = safe_float(r["value"][1])
        if val > 0.01:
            any_error = True
            if val > 5:   status = "🔴 CRITICAL"
            elif val > 1: status = "🟡 WARNING "
            else:         status = "🟢 LOW     "
            print(f"  {status}  {svc:<35} {val:.2f}%")
    if not any_error:
        print("  ✅ 所有服务错误率正常 (0%)")

# ── 3. P99 延迟 ───────────────────────────────────────────────
print(f"\n{'─'*65}")
print(f"3. P99 延迟 (最近 {W})")
print(f"{'─'*65}")
if duration_metric:
    results = prom_query(
        f'histogram_quantile(0.99, sum by (service_name, le) (rate({duration_metric}[{W}])))'
    )
    if results:
        for r in sorted(results, key=lambda x: safe_float(x["value"][1]), reverse=True):
            svc = r["metric"].get("service_name", "unknown")
            val = safe_float(r["value"][1])
            if val > 5000:   status = "🔴 SLOW   "
            elif val > 1000: status = "🟡 HIGH   "
            else:            status = "🟢 OK     "
            print(f"  {status}  {svc:<35} {val:7.0f} ms")
    else:
        print("  (暂无延迟数据)")

# ── 4. Prometheus 告警 ────────────────────────────────────────
print(f"\n{'─'*65}")
print("4. Prometheus 告警状态")
print(f"{'─'*65}")
alerts = prom_alerts()
# 过滤掉 Watchdog / InfoInhibitor 系统占位告警
skip = {"Watchdog", "InfoInhibitor"}
firing  = [a for a in alerts if a["state"] == "firing"  and a["labels"].get("alertname") not in skip]
pending = [a for a in alerts if a["state"] == "pending" and a["labels"].get("alertname") not in skip]
if not firing and not pending:
    print("  ✅ 无异常告警")
if firing:
    print(f"  🔴 Firing 告警 ({len(firing)} 条):")
    for a in firing:
        name = a["labels"].get("alertname", "?")
        ns   = a["labels"].get("namespace", a["labels"].get("service", "?"))
        sev  = a["labels"].get("severity", "none").upper()
        print(f"    [{sev}] {name}  (ns: {ns})")
if pending:
    print(f"  🟡 Pending 告警 ({len(pending)} 条):")
    for a in pending[:5]:
        print(f"    {a['labels'].get('alertname','?')}")

# ── 5. Pod 资源使用 (online-boutique) ─────────────────────────
print(f"\n{'─'*65}")
print(f"5. Pod 资源使用 online-boutique (最近 {W})")
print(f"{'─'*65}")
cpu_r = prom_query(
    f'sum by (pod) (rate(container_cpu_usage_seconds_total{{namespace="online-boutique",container!="",container!="POD"}}[{W}])) * 1000'
)
mem_r = prom_query(
    'sum by (pod) (container_memory_working_set_bytes{namespace="online-boutique",container!="",container!="POD"}) / 1024 / 1024'
)
cpu_map = {r["metric"]["pod"]: safe_float(r["value"][1]) for r in cpu_r}
mem_map = {r["metric"]["pod"]: safe_float(r["value"][1]) for r in mem_r}
all_pods = sorted(set(list(cpu_map) + list(mem_map)))
if all_pods:
    print(f"  {'Pod':<50} {'CPU':>8}  {'MEM':>7}")
    for pod in all_pods:
        cpu = cpu_map.get(pod, 0)
        mem = mem_map.get(pod, 0)
        cf = " ⚠️" if cpu > 500 else ""
        mf = " ⚠️" if mem > 400 else ""
        print(f"  {pod:<50} {cpu:6.1f}m{cf}  {mem:5.0f}Mi{mf}")
else:
    print("  (无资源数据)")

# ── 6. Tracing 管道健康 ───────────────────────────────────────
print(f"\n{'─'*65}")
print("6. Tracing 管道健康 (Tempo)")
print(f"{'─'*65}")
spans_r = prom_query('tempo_distributor_spans_received_total{tenant="single-tenant"}')
traces_r = prom_query('tempo_ingester_traces_created_total{tenant="single-tenant"}')
if spans_r:
    spans = safe_float(spans_r[0]["value"][1])
    print(f"  Tempo 累计接收 Spans:  {spans:,.0f}")
if traces_r:
    traces = safe_float(traces_r[0]["value"][1])
    print(f"  Tempo 累计创建 Traces: {traces:,.0f}")
# Span 接收速率
rate_r = prom_query(f'rate(tempo_distributor_spans_received_total{{tenant="single-tenant"}}[{W}])')
if rate_r:
    rate = safe_float(rate_r[0]["value"][1])
    print(f"  Span 接收速率 ({W}):   {rate:.1f} spans/s")
if not spans_r and not traces_r:
    print("  (无 Tempo 数据，请检查 otel-collector → Tempo 链路)")

print(f"\n{'='*65}")
print("  报告完成")
print(f"{'='*65}\n")
```

### 步骤 4：查询最近错误日志

使用 `kubectl logs` 扫描主要服务最近时间窗口内的 error 日志：

```bash
for svc in frontend checkoutservice paymentservice cartservice shippingservice; do
  POD=$(kubectl get pod -n online-boutique -l app=$svc -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
  if [ -n "$POD" ]; then
    ERRORS=$(kubectl logs -n online-boutique $POD --since=TIME_WINDOW 2>/dev/null \
      | grep -iE '"severity":"error"|level=error|\bERROR\b|\bpanic\b|\bfatal\b' \
      | grep -v "visa_electron" \
      | tail -3)
    if [ -n "$ERRORS" ]; then
      echo "⚠️  $svc: $ERRORS"
    fi
  fi
done
```

（注意：`visa_electron` 错误是 Demo loadgenerator 的正常模拟行为，过滤掉）

### 步骤 5：输出汇总报告

整合所有数据，输出结构化的 Markdown 报告，包含：

1. **总体健康状态**：✅ 正常 / ⚠️ 有告警 / 🔴 有故障
2. **各指标表格**（RPS、P99、错误率）
3. **告警列表**（过滤 Watchdog/InfoInhibitor）
4. **资源使用**
5. **异常 Pod 详情**（非 Running、非 1/1 Ready 的 Pod）
6. **Tracing 管道状态**
7. **近期错误日志摘要**
8. **结论与建议**

## 重要说明

- Prometheus 查询必须使用 `ProxyHandler({})` 绕过本机 HTTP 代理（已有 `http_proxy=127.0.0.1:10809` 会拦截 localhost 请求）
- 端口转发: `kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 19090:9090`
- 执行完毕后务必 `kill` 掉后台 port-forward 进程
- 时间窗口需同时用于：Prometheus 查询的 `[Xm]`、`kubectl logs --since=Xm`（kubectl since 格式不支持 `h`，需转换：`1h` → `60m`）
