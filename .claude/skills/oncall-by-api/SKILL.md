---
name: oncall-by-api
description: 通用告警值班数字员工（纯 API 版），无需 mcp-grafana，直接调用 Prometheus/Loki HTTP API。用法：/oncall-by-api [interval=60s] [namespace=online-boutique]
license: MIT
compatibility:
  claude_code: ">=1.0"
metadata:
  author: xianb
  version: 1.0.0
  generatedBy: claude-sonnet-4-6
---

# 告警值班数字员工（纯 API 版）

持续监控 Prometheus 告警状态，无告警时定期巡检，发现已知类型告警则按 Runbook 自动止损，未知告警则分析并上报。

**本版本不依赖 mcp-grafana**，所有 Prometheus/Loki 查询均通过 `curl` 直接调用 HTTP API。

## 用法

```
/oncall-by-api [interval=60s] [namespace=online-boutique]
```

### 参数

- `interval`: 可选，无告警时的巡检间隔（默认 `60s`，支持 `30s`/`60s`/`2m`/`5m`）
- `namespace`: 可选，监控的业务命名空间（默认 `online-boutique`）

---

## API 端点配置

从以下环境变量读取（自动探测，无需手动配置）：

```bash
# 优先级：环境变量 > .mcp.json 自动读取 > 默认值
GRAFANA_URL      # 如 http://47.83.217.162:3000
GRAFANA_TOKEN    # 如 glsa_xxx（Service Account Token）
PROMETHEUS_URL   # 如 http://47.83.217.162:9090（可选，优先直连）
LOKI_URL         # 如 http://47.83.217.162:3100（可选，优先直连）
```

**自动探测逻辑**（步骤 0 执行）：

1. 读取 `$GRAFANA_URL` / `$GRAFANA_TOKEN` 环境变量
2. 若未设置，读取项目根目录 `.mcp.json` 中 `mcpServers.grafana.env`
3. Prometheus 默认通过 Grafana datasource proxy：`$GRAFANA_URL/api/datasources/proxy/1/api/v1`
4. Loki 默认通过 Grafana datasource proxy：`$GRAFANA_URL/api/datasources/proxy/2`
5. 若设置了 `$PROMETHEUS_URL`，直连 Prometheus，不走 Grafana proxy

---

## API 调用规范（经验沉淀）

### 铁律：curl 结果必须先存文件，再 cat | python3 解析

**错误写法（三种常见坑，全部禁止）：**

```bash
# ❌ 坑1: python3 -c 里的 != 在双引号字符串中被 shell 转义为 \!，导致 SyntaxError
curl ... | python3 -c "... if x['value'][1] != '+Inf' ..."

# ❌ 坑2: curl | python3 << 'EOF' —— curl 和 heredoc 都抢 stdin，json 数据和代码混流
curl ... | python3 << 'EOF'
import json,sys
...
EOF

# ❌ 坑3: python3 << 'EOF' < file —— heredoc 和文件重定向互斥，文件内容被吞掉
python3 << 'EOF' < /tmp/result.json
...
EOF
```

**正确写法（唯一推荐模式）：**

```bash
# ✅ 第一步：curl 结果存文件
curl -s -H "Authorization: Bearer $GRAFANA_TOKEN" \
  "$GRAFANA_URL/api/datasources/proxy/uid/$PROM_DS_UID/api/v1/query" \
  --data-urlencode "query=ALERTS{alertstate=\"firing\"}" \
  > /tmp/oncall_alerts.json

# ✅ 第二步：cat file | python3 -c "..." 解析（python3 -c 内部不含 shell 特殊字符）
cat /tmp/oncall_alerts.json | python3 -c "
import json,sys
r = json.load(sys.stdin)
results = r.get('data', {}).get('result', [])
print(len(results))
"
```

**Loki 时间范围（用 python3 生成纳秒时间戳，不用 date -d）：**

```bash
# ✅ macOS/Linux 通用（date -d 在 macOS 不支持）
START_NS=$(python3 -c "import time; print(int((time.time()-300)*1e9))")
END_NS=$(python3 -c "import time; print(int(time.time()*1e9))")

curl -s -H "Authorization: Bearer $GRAFANA_TOKEN" \
  "$GRAFANA_URL/api/datasources/proxy/uid/$LOKI_DS_UID/loki/api/v1/query_range" \
  --data-urlencode 'query={namespace="online-boutique"} |~ "(?i)(error|timeout|fatal)"' \
  --data-urlencode "limit=20" \
  --data-urlencode "start=$START_NS" \
  --data-urlencode "end=$END_NS" \
  --data-urlencode "direction=backward" \
  > /tmp/oncall_loki.json
cat /tmp/oncall_loki.json | python3 -c "
import json,sys
r = json.load(sys.stdin)
streams = r.get('data', {}).get('result', [])
for stream in streams[:3]:
    pod = stream.get('stream', {}).get('pod', '?')
    for ts, line in stream.get('values', [])[:3]:
        print(pod, line[:100])
"
```

> **Datasource UID**: 通常固定为 `prometheus` 和 `loki`（Grafana 默认命名规范，已验证）。初始化时通过 `GET /api/datasources` 确认。

---

## 状态机

```
IDLE
  ↓ 每 interval 秒
POLLING ──── 无告警 ──→ IDLE（输出"巡检正常"）
  ↓ 发现 firing 告警
ANALYZING（查 metrics + logs via curl）
  ↓
  ├── 已知止损路径 ──→ MITIGATING（执行止损）──→ MONITORING_RECOVERY
  └── 未知/复杂告警 ──→ 上报分析结论，等待人工介入，继续 POLLING
```

---

## 执行步骤

### 步骤 0：初始化 — 探测 API 配置

**0.1 读取配置**

按以下优先级获取 `GRAFANA_URL` 和 `GRAFANA_TOKEN`：

```bash
# 1. 环境变量
GRAFANA_URL="${GRAFANA_URL:-}"
GRAFANA_TOKEN="${GRAFANA_TOKEN:-}"

# 2. 若为空，从 .mcp.json 读取
if [ -z "$GRAFANA_URL" ] && [ -f ".mcp.json" ]; then
  GRAFANA_URL=$(python3 -c "
import json
d=json.load(open('.mcp.json'))
g=d.get('mcpServers',{}).get('grafana',{})
print(g.get('env',{}).get('GRAFANA_URL','') or g.get('env',{}).get('GRAFANA_SERVICE_ACCOUNT_TOKEN','').split('@')[-1] if '@' in g.get('env',{}).get('GRAFANA_SERVICE_ACCOUNT_TOKEN','') else '')
" 2>/dev/null)
  GRAFANA_TOKEN=$(python3 -c "
import json
d=json.load(open('.mcp.json'))
g=d.get('mcpServers',{}).get('grafana',{})
print(g.get('env',{}).get('GRAFANA_SERVICE_ACCOUNT_TOKEN',''))
" 2>/dev/null)
fi
```

**0.2 发现 Prometheus datasource UID**

```bash
# ✅ 存文件再解析
curl -s -H "Authorization: Bearer $GRAFANA_TOKEN" \
  "$GRAFANA_URL/api/datasources" > /tmp/oncall_ds.json
cat /tmp/oncall_ds.json | python3 -c "
import json,sys
ds=json.load(sys.stdin)
for d in ds:
    if d.get('type') == 'prometheus':
        print('PROM_DS_UID=' + d['uid'])
    if d.get('type') == 'loki':
        print('LOKI_DS_UID=' + d['uid'])
"
# 实测结果：prometheus / loki（Grafana 默认 uid 即类型名）
PROM_DS_UID="prometheus"
LOKI_DS_UID="loki"
```

将 `PROM_DS_UID` 和 `LOKI_DS_UID` 存为 shell 变量，后续步骤复用。

**0.3 验证连通性**

```bash
# ✅ 存文件再解析（单行 python3 -c 只在无特殊字符时安全）
curl -s -H "Authorization: Bearer $GRAFANA_TOKEN" \
  "$GRAFANA_URL/api/datasources/proxy/uid/$PROM_DS_UID/api/v1/query" \
  --data-urlencode "query=up" > /tmp/oncall_up.json
cat /tmp/oncall_up.json | python3 -c "import json,sys; r=json.load(sys.stdin); print('Prometheus OK, series:', len(r['data']['result']))"
```

**0.4 解析参数，打印值班横幅**

从 `$ARGUMENTS` 解析 `interval`（默认 `60`，单位秒）和 `namespace`（默认 `online-boutique`）。

输出：

```
╔══════════════════════════════════════════════════════╗
║           🚨 告警值班员（API版）已上线                  ║
╠══════════════════════════════════════════════════════╣
║  命名空间: online-boutique                            ║
║  巡检间隔: 60s                                        ║
║  Grafana:  http://47.83.217.162:3000                 ║
║  Prom UID: abc123                                    ║
║  开始时间: 2026-03-12 14:00:00                        ║
╚══════════════════════════════════════════════════════╝

按 Ctrl+C 或关闭对话结束值班。
```

---

### 步骤 1：巡检轮次开始

输出当前轮次和时间戳：

```
─────────────────────────────────────────
🔍 巡检轮次 #N  [2026-03-12 14:01:00]
─────────────────────────────────────────
```

---

### 步骤 2：查询当前 Firing 告警

**方式 A：通过 Grafana datasource proxy（推荐）**

```bash
# ✅ 存文件再解析
curl -s -H "Authorization: Bearer $GRAFANA_TOKEN" \
  "$GRAFANA_URL/api/datasources/proxy/uid/$PROM_DS_UID/api/v1/query" \
  --data-urlencode 'query=ALERTS{alertstate="firing", namespace="online-boutique"}' \
  > /tmp/oncall_alerts.json

cat /tmp/oncall_alerts.json | python3 -c "
import json,sys
r = json.load(sys.stdin)
results = r.get('data', {}).get('result', [])
skip = {'Watchdog', 'InfoInhibitor'}
firing = [x for x in results if x['metric'].get('alertname') not in skip]
print('FIRING_COUNT=' + str(len(firing)))
for a in firing:
    m = a['metric']
    print(m.get('severity','?').upper(), m.get('alertname'), 'pod=' + m.get('pod',''), 'svc=' + m.get('service',''))
"
```

**方式 B：直连 Prometheus（若设置了 $PROMETHEUS_URL，无需 token）**

```bash
curl -s "$PROMETHEUS_URL/api/v1/query" \
  --data-urlencode 'query=ALERTS{alertstate="firing", namespace="online-boutique"}' \
  > /tmp/oncall_alerts.json
# 同方式 A 解析 /tmp/oncall_alerts.json
```

**方式 C：查询 Alertmanager API（备用）**

```bash
# ✅ 存文件再解析
curl -s "$ALERTMANAGER_URL/api/v2/alerts?active=true&silenced=false&inhibited=false" \
  > /tmp/oncall_am_alerts.json

cat /tmp/oncall_am_alerts.json | python3 -c "
import json,sys
alerts = json.load(sys.stdin)
firing = [a for a in alerts
          if a['labels'].get('alertname') not in {'Watchdog','InfoInhibitor'}
          and a['labels'].get('namespace') == 'online-boutique']
for a in firing:
    print(a['labels'].get('alertname'), a['labels'].get('pod',''), a['labels'].get('severity',''))
"
```

**无 firing 告警时**：

```
✅ 无异常告警 — 系统正常
   (Pending: N 条 | 跳过: Watchdog)
   等待 60s 后进行下一次巡检...
```

→ 执行 `sleep $INTERVAL`，回到步骤 1。

**有 firing 告警时**：进入步骤 3。

---

### 步骤 3：告警分类与初步分析

对每条 firing 告警，提取 `alertname`、`pod`、`container`、`service`、`severity`，按以下规则分类：

#### 已知止损路径（可自动处理）

| alertname 匹配 | 分类 | 止损动作 |
|---------------|------|---------|
| `AppCPUThrottling` 或 `ChaosCPUThrottling` | CPU 节流 | 删除目标 Pod |
| `AppHighCPUUsage` 或 `ChaosHighCPUUsage` | CPU 高用量 | 删除目标 Pod（仅当伴随延迟/错误率告警）|
| `AppPodCrashLooping` 或 `ChaosPodCrashLooping` | Pod 崩溃循环 | 删除 Pod（触发重建）|
| `AppPodNotReady` 或 `ChaosPodNotReady` | Pod 不就绪 | 删除 Pod（仅当 Pending > 3min）|

#### 需分析不自动操作

| alertname 匹配 | 分析重点 |
|---------------|---------|
| `AppHighLatency` 或 `ChaosHighLatency` | 查 P99 + 找级联来源 |
| `AppHighErrorRate` 或 `ChaosHighErrorRate` | 查错误率 + Loki error 日志 |
| `AppHighMemoryUsage` 或 `ChaosHighMemoryUsage` | 查内存 + OOMKill 情况 |
| 其他未知告警 | 通用排查 |

输出分类结果：

```
🚨 发现 N 条 Firing 告警：
  [CRITICAL] AppCPUThrottling  pod=redis-cart-xxx  → 分类: CPU节流  止损: 删除Pod
  [WARNING]  AppHighLatency    service=frontend    → 分类: 高延迟   止损: 需分析
```

---

### 步骤 4：指标快速核查（curl 直调）

针对 firing 告警涉及的服务，通过 curl 收集证据：

**4.1 CPU 节流率**

```bash
# ✅ 存文件再解析；PromQL 用单引号包裹整体避免 shell 变量展开问题
POD_PATTERN="<pod-name>"
THROTTLE_QUERY="sum(rate(container_cpu_cfs_throttled_periods_total{namespace=\"$NAMESPACE\",pod=~\"${POD_PATTERN}.*\"}[2m])) by (pod,container) / sum(rate(container_cpu_cfs_periods_total{namespace=\"$NAMESPACE\",pod=~\"${POD_PATTERN}.*\"}[2m])) by (pod,container)"

curl -s -H "Authorization: Bearer $GRAFANA_TOKEN" \
  "$GRAFANA_URL/api/datasources/proxy/uid/$PROM_DS_UID/api/v1/query" \
  --data-urlencode "query=$THROTTLE_QUERY" \
  > /tmp/oncall_cpu.json

cat /tmp/oncall_cpu.json | python3 -c "
import json,sys
r=json.load(sys.stdin)
for item in r.get('data',{}).get('result',[]):
    val = float(item['value'][1])
    pod = item['metric'].get('pod','?')
    print(f'  节流率: {val*100:.1f}% | pod={pod}')
"
```

**4.2 错误率**

```bash
# ✅ 存文件再解析
# ✅ 全服务聚合查询（加 namespace 过滤），单服务时可加 service_name="$SERVICE"
# ✅ 必须用 math.isnan() 过滤 NaN（无错误时 Prometheus 返回 NaN，不过滤会显示噪音）
ERROR_QUERY="sum(rate(traces_spanmetrics_calls_total{status_code=\"STATUS_CODE_ERROR\",namespace=\"$NAMESPACE\"}[2m])) by (service_name) / sum(rate(traces_spanmetrics_calls_total{namespace=\"$NAMESPACE\"}[2m])) by (service_name)"

curl -s -H "Authorization: Bearer $GRAFANA_TOKEN" \
  "$GRAFANA_URL/api/datasources/proxy/uid/$PROM_DS_UID/api/v1/query" \
  --data-urlencode "query=$ERROR_QUERY" \
  > /tmp/oncall_errrate.json

cat /tmp/oncall_errrate.json | python3 -c "
import json,sys,math
r=json.load(sys.stdin)
results = r.get('data',{}).get('result',[])
if not results:
    print('  错误率: 0% (无数据)')
else:
    for item in results:
        svc = item['metric'].get('service_name','?')
        try:
            val = float(item['value'][1])
            if math.isnan(val):
                continue
            status = 'WARN' if val > 0.01 else 'OK'
            print(f'  [{status}] {svc}: {val*100:.2f}%')
        except (ValueError, KeyError):
            pass
"
```

**4.3 P99 延迟**

```bash
# ✅ 存文件再解析；+Inf 值用 try/except 处理
# ✅ 全服务聚合查询时加 namespace 过滤，避免跨命名空间数据干扰
P99_QUERY="histogram_quantile(0.99, sum(rate(traces_spanmetrics_duration_milliseconds_bucket{namespace=\"$NAMESPACE\"}[2m])) by (service_name,le))"

curl -s -H "Authorization: Bearer $GRAFANA_TOKEN" \
  "$GRAFANA_URL/api/datasources/proxy/uid/$PROM_DS_UID/api/v1/query" \
  --data-urlencode "query=$P99_QUERY" \
  > /tmp/oncall_p99.json

cat /tmp/oncall_p99.json | python3 -c "
import json,sys
r=json.load(sys.stdin)
rows = []
for item in r.get('data',{}).get('result',[]):
    svc = item['metric'].get('service_name','?')
    try:
        val = float(item['value'][1])
        rows.append((val, svc))
    except (ValueError, KeyError):
        rows.append((0, svc + '(N/A)'))
for val, svc in sorted(rows, reverse=True):
    status = 'WARN' if val > 1000 else 'OK'
    print(f'  [{status}] {svc}: P99={val:.0f}ms')
"
```

如果错误率 > 1% 或 P99 > 1000ms，记录为「有用户影响」。

---

### 步骤 5：日志快速扫描（仅在错误率或延迟异常时执行）

通过 Loki HTTP API 查询最近 5 分钟错误日志：

```bash
# ✅ 存文件再解析；时间戳用 python3 生成（date -d 在 macOS 不支持）
# ✅ Loki query 参数必须用 query= 前缀，不能裸传 LogQL 字符串
POD_PATTERN="<pod-name>"
START_NS=$(python3 -c "import time; print(int((time.time()-300)*1e9))")
END_NS=$(python3 -c "import time; print(int(time.time()*1e9))")
LOKI_QUERY="{namespace=\"$NAMESPACE\",pod=~\"${POD_PATTERN}.*\"} |~ \"(?i)(error|timeout|fatal|panic)\""

curl -s -H "Authorization: Bearer $GRAFANA_TOKEN" \
  "$GRAFANA_URL/api/datasources/proxy/uid/$LOKI_DS_UID/loki/api/v1/query_range" \
  --data-urlencode "query=$LOKI_QUERY" \
  --data-urlencode "limit=20" \
  --data-urlencode "start=$START_NS" \
  --data-urlencode "end=$END_NS" \
  --data-urlencode "direction=backward" \
  > /tmp/oncall_loki.json

cat /tmp/oncall_loki.json | python3 -c "
import json,sys
r=json.load(sys.stdin)
streams = r.get('data',{}).get('result',[])
for stream in streams[:3]:
    pod = stream.get('stream',{}).get('pod','?')
    for ts, line in stream.get('values',[])[:5]:
        print(f'  [{pod}] {line[:120]}')
"
```

提取：错误关键词（timeout / connection refused / OOM）、受影响的上下游调用。

---

### 步骤 6：止损执行（仅针对已知止损路径）

#### 6A：CPU 节流止损（删除 Pod）

**前置确认**：

```bash
# 确认 Pod 由 Deployment 管理
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.metadata.ownerReferences[0].kind}'
# 预期输出: ReplicaSet
```

**执行删除**：

```bash
kubectl delete pod <pod-name> -n <namespace>
```

输出：

```
🔧 [止损] 执行删除 Pod: redis-cart-xxx (CPU节流 85%)
   依据: AppCPUThrottling firing | 节流率 85% | 持续 > 5min
   执行: kubectl delete pod redis-cart-xxx -n online-boutique
   ✅ Pod 删除指令已发出，等待新 Pod 就绪...
```

#### 6B：Pod 崩溃循环止损

```bash
kubectl delete pod <pod-name> -n <namespace>
```

#### 6C：需人工介入（高延迟/高错误率）

```
📊 [分析结论] AppHighLatency — frontend P99 = 3200ms
   根因推断: checkoutservice → cartservice → redis-cart 级联超时
   证据: [Metrics] redis-cart CPU节流率 85% | [Logs] "redis: connection pool timeout"
   建议止损: 参考 docs/runbook/business/high-cpu-runbook.md
   ⚠️ 建议人工确认后执行止损。
```

---

### 步骤 7：恢复监控（止损后）

止损操作后，进入恢复观察循环（最多 5 轮，每轮 30 秒）：

```bash
# 等待新 Pod Ready
kubectl get pod -n <namespace> -l app=<service> \
  -o jsonpath='{.items[0].status.conditions[?(@.type=="Ready")].status}'
```

同时通过 curl 查询恢复曲线（同步骤 4，缩短 rate 窗口为 1m）。

每 30 秒输出：

```
⏳ 恢复观察 [1/5] +30s  新Pod: Running(1/1) | 节流率: 12% ↓ | P99: 450ms ↓
⏳ 恢复观察 [2/5] +60s  新Pod: Running(1/1) | 节流率:  3% ↓ | P99:  80ms ✅
✅ 恢复确认：AppCPUThrottling 告警已 resolved，P99 < 100ms
```

若 5 轮后仍未恢复，输出升级提示并通知人工。

---

### 步骤 8：轮次结束，等待下一次巡检

```
─────────────────────────────────────────
📋 巡检 #N 摘要 [耗时 45s]
   告警: 2 条 Firing（已处理 1 / 待人工 1）
   止损: redis-cart Pod 删除 → 已恢复 ✅
   上报: AppHighLatency frontend → 待人工确认
─────────────────────────────────────────
💤 等待 60s 后开始下一次巡检...
```

执行 `sleep $INTERVAL`，回到步骤 1。

---

## 止损决策原则

**自动止损仅在以下条件全部满足时执行**：

1. alertname 明确匹配已知止损路径
2. 目标 Pod 由 Deployment/ReplicaSet 管理（非裸 Pod、非 StatefulSet）
3. 节流率 > 50% 或 CrashLoop 重启次数 > 3
4. 副本数 >= 1

**以下情况不自动操作，仅上报**：

- StatefulSet Pod（如 `redis-cart-0`）
- 仅有延迟/错误率告警，无 CPU/内存资源类告警
- 未知告警名称
- 同一 Pod 本次值班已操作过 2 次

---

## API 工具使用清单

| 步骤 | 工具 | API 端点 |
|------|------|---------|
| 步骤 0 | `curl` | `GET $GRAFANA_URL/api/datasources` |
| 步骤 2 | `curl` | `POST $GRAFANA_URL/api/datasources/proxy/uid/$PROM_DS_UID/api/v1/query` |
| 步骤 4.1 | `curl` | 同上（container_cpu_cfs_throttled_periods_total）|
| 步骤 4.2 | `curl` | 同上（traces_spanmetrics_calls_total）|
| 步骤 4.3 | `curl` | 同上（traces_spanmetrics_duration_milliseconds_bucket）|
| 步骤 5 | `curl` | `GET $GRAFANA_URL/api/datasources/proxy/uid/$LOKI_DS_UID/loki/api/v1/query_range` |
| 步骤 6 | `kubectl` | delete pod |
| 步骤 7 | `kubectl` + `curl` | get pod + Prometheus |

---

## 核心原则

**API 优先** — 所有监控数据查询通过 curl 直调，不依赖 MCP 工具。

**告警名不等于根因** — 须以 metrics + logs 时间序列为判断依据。

**最小化自动操作** — 只对有充分量化证据、有明确恢复路径的告警自动止损。

**止损后必须验证** — 每次操作后进入恢复观察循环。

---

## 验收标准

- [x] 无需 mcp-grafana，纯 curl + kubectl 实现全部功能
- [x] 自动从 `.mcp.json` 读取 Grafana URL 和 Token（零配置）
- [x] 自动发现 Prometheus/Loki datasource UID
- [x] 正确过滤 Watchdog / InfoInhibitor 占位告警
- [x] 按告警分类表区分「自动止损」和「人工上报」
- [x] CPU 节流止损前确认 Pod 控制器类型
- [x] 止损后进入恢复观察循环（最多 5 轮 × 30s）
- [x] 同一 Pod 本次值班最多自动操作 2 次

---

## 相关文档

- [通用告警处理 SOP](../../docs/runbook/alert-runbook/general-alert-handling.md)
- [CPU 高负载 Runbook](../../docs/runbook/business/high-cpu-runbook.md)
- [删除 Pod 操作手册](../../docs/runbook/ops/delete-pod.md)
