---
name: chaos-report
description: 生成完整混沌实验报告，整合 Pod 状态、Prometheus 指标、Alertmanager 告警、自我恢复数据，输出结构化 Markdown 报告。用法：/chaos-report [experiment-id]
license: MIT
compatibility:
  claude_code: ">=1.0"
metadata:
  author: xianb
  version: 1.0.0
  generatedBy: claude-sonnet-4-6
---

# 生成实验报告

整合实验信息、可观测性数据、告警验证结果、自我恢复数据，生成完整的混沌实验报告。

## 用法

```
/chaos-report [experiment-id]
```

### 参数

- `experiment-id`: 可选，实验 ID（格式：`<type>-<service>-YYYYMMDD-HHMMSS`）。不指定则根据对话上下文获取最近实验信息。

## 执行步骤

### 步骤 1：收集实验基本信息

从对话上下文（注入 skill 的输出）中获取：
- 实验 ID、类型、目标服务
- 故障类型（PodKill / NetworkPartition / StressCPU / StressMemory）
- 实验时长、开始/结束时间

若无上下文，查询 Chaos Mesh 历史（如已安装）：
```bash
kubectl get podchaos,networkchaos,stresschaos --all-namespaces \
  -o custom-columns="NAME:.metadata.name,TYPE:.kind,STATUS:.status.experiment.desiredPhase,START:.metadata.creationTimestamp" 2>/dev/null
```

### 步骤 2：收集 Pod 状态数据

```bash
# 当前状态
kubectl get pods -n online-boutique --no-headers | \
  awk '{print $1, $2, $3, "重启:"$4}'

# 目标服务事件（最近 10 条）
kubectl get events -n online-boutique \
  --sort-by='.lastTimestamp' \
  --field-selector reason!=Scheduled \
  2>/dev/null | tail -10
```

### 步骤 3：收集性能指标（Prometheus）

```bash
kubectl exec -n monitoring prometheus-kube-prometheus-stack-prometheus-0 -- \
  wget -qO- "http://localhost:9090/api/v1/query?query=sum+by+(service_name)(rate(traces_spanmetrics_calls_total%5B5m%5D))" | \
  python3 -c "
import json,sys
r=json.load(sys.stdin)['data']['result']
print('=== RPS (5m) ===')
for x in sorted(r,key=lambda a:float(a['value'][1]),reverse=True):
    print(f'  {x[\"metric\"].get(\"service_name\",\"?\")}: {float(x[\"value\"][1]):.3f} rps')
" 2>/dev/null

kubectl exec -n monitoring prometheus-kube-prometheus-stack-prometheus-0 -- \
  wget -qO- "http://localhost:9090/api/v1/query?query=histogram_quantile(0.99%2C+sum+by+(service_name%2Cle)(rate(traces_spanmetrics_duration_milliseconds_bucket%5B5m%5D)))" | \
  python3 -c "
import json,sys
r=json.load(sys.stdin)['data']['result']
print('=== P99 延迟 (5m) ===')
for x in sorted(r,key=lambda a:float(a['value'][1]),reverse=True)[:6]:
    print(f'  {x[\"metric\"].get(\"service_name\",\"?\")}: {float(x[\"value\"][1]):.0f} ms')
" 2>/dev/null
```

### 步骤 4：收集告警数据

```bash
# 当前 Chaos 告警
kubectl exec -n monitoring alertmanager-kube-prometheus-stack-alertmanager-0 -- \
  wget -qO- 'http://localhost:9093/api/v2/alerts?filter=chaos_test%3D%22true%22' | \
  python3 -c "
import json,sys
alerts=json.load(sys.stdin)
print(f'=== Chaos 告警 ({len(alerts)} 条) ===')
for a in alerts:
    print(f'  [{a[\"labels\"].get(\"severity\",\"?\").upper()}] {a[\"labels\"].get(\"alertname\",\"?\")} [{a[\"status\"][\"state\"]}]')
" 2>/dev/null
```

### 步骤 5：整合输出报告

将以上数据整合为完整 Markdown 报告：

```markdown
# 混沌实验报告

**实验 ID**: <id>
**报告时间**: <now>
**实验类型**: <type>
**目标服务**: <service>
**故障类型**: <fault>
**实验时长**: <duration>

## 观察数据

### Pod 状态
<kubectl 输出>

### 性能指标
| 服务 | RPS | P99 延迟 | 错误率 |
|-----|-----|---------|-------|
| ... | ... | ... | ... |

### 告警触发
<alertmanager 输出>

## 验证结果

### 告警验证
✅/❌ <预期告警> - 是否触发

### 自我恢复
✅/⚠️ Pod 恢复 / 错误率清零 / 延迟恢复

## 问题识别

1. <问题描述>

## 改进建议

1. <建议> → 代码路径: `deploy/monitoring/alerting/chaos-testing-alerts.yaml`

## 总结

- 系统弹性: ✅ 优秀 / ⚠️ 待改进
- 告警有效性: ✅ 100% / ⚠️ X%
- 整体评价: ✅ 通过 / ⚠️ 需关注
```

## 核心原则

**告警规则必须代码固化** — 改进建议必须指向代码文件路径（`deploy/monitoring/alerting/`），禁止建议手动创建告警规则。

## 验收标准

- [x] 自动收集 Pod 状态、Events、RPS、P99、错误率
- [x] 自动收集 Alertmanager Chaos 告警
- [x] 整合输出结构化 Markdown 报告
- [x] 改进建议指向具体代码路径
