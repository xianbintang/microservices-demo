---
name: chaos-validate-self-heal
description: 验证混沌实验后系统自我恢复能力，检查 Pod 状态、错误率、延迟是否恢复基准，生成自我恢复验证报告。用法：/chaos-validate-self-heal [service]
license: MIT
compatibility:
  claude_code: ">=1.0"
metadata:
  author: xianb
  version: 1.0.0
  generatedBy: claude-sonnet-4-6
---

# 自我恢复验证

通过 kubectl + Prometheus 查询验证实验结束后系统是否完全恢复，覆盖 Pod 状态、错误率、P99 延迟、资源使用。

## 用法

```
/chaos-validate-self-heal [service]
```

### 参数

- `service`: 可选，目标服务名称（如 `frontend`），不指定则检查所有 online-boutique 服务

## 执行步骤

### 步骤 1：检查 Pod 恢复状态

```bash
# 检查所有 Pod 是否 Running
kubectl get pods -n online-boutique --no-headers | \
  awk '$3 != "Running" && $3 != "Completed" {print "⚠️ 未就绪:", $1, $3, $4}'

# 统计就绪情况
kubectl get pods -n online-boutique --no-headers | \
  awk 'BEGIN{ok=0;total=0} {total++; if($2=="1/1" && $3=="Running") ok++} \
       END{
         status=(ok==total)?"✅":"⚠️"
         print status, "Pod 就绪:", ok"/"total
       }'
```

**恢复标准**：所有 Pod `1/1 Running`，无 `CrashLoopBackOff` 或 `Pending`。

### 步骤 2：检查错误率恢复

```bash
kubectl exec -n monitoring prometheus-kube-prometheus-stack-prometheus-0 -- \
  wget -qO- "http://localhost:9090/api/v1/query?query=sum+by+(service_name)(rate(traces_spanmetrics_calls_total%7Bstatus_code%3D%22STATUS_CODE_ERROR%22%7D%5B2m%5D))+%2F+sum+by+(service_name)(rate(traces_spanmetrics_calls_total%5B2m%5D))+*+100" | \
  python3 -c "
import json, sys
results = json.load(sys.stdin)['data']['result']
print('错误率 (2m 滚动窗口):')
any_high = False
for r in sorted(results, key=lambda x: float(x['value'][1] or 0), reverse=True):
    svc = r['metric'].get('service_name', '?')
    val = float(r['value'][1] or 0)
    if val > 1:
        any_high = True
        print(f'  ⚠️  {svc}: {val:.2f}%')
    else:
        print(f'  ✅ {svc}: {val:.2f}%')
if not any_high:
    print('所有服务错误率已恢复基准 (< 1%)')
" 2>/dev/null || echo "  (spanmetrics 数据暂未就绪)"
```

**恢复标准**：所有服务错误率 < 1%（实验前基准约 0%）。

### 步骤 3：检查 P99 延迟恢复

```bash
kubectl exec -n monitoring prometheus-kube-prometheus-stack-prometheus-0 -- \
  wget -qO- "http://localhost:9090/api/v1/query?query=histogram_quantile(0.99%2C+sum+by+(service_name%2C+le)(rate(traces_spanmetrics_duration_milliseconds_bucket%5B2m%5D)))" | \
  python3 -c "
import json, sys
results = json.load(sys.stdin)['data']['result']
print('P99 延迟 (2m 滚动窗口):')
for r in sorted(results, key=lambda x: float(x['value'][1] or 0), reverse=True)[:8]:
    svc = r['metric'].get('service_name', '?')
    val = float(r['value'][1] or 0)
    if val > 2000:
        print(f'  ⚠️  {svc}: {val:.0f} ms (未恢复)')
    else:
        print(f'  ✅ {svc}: {val:.0f} ms')
" 2>/dev/null || echo "  (延迟数据暂未就绪)"
```

**恢复标准**：P99 < 2000ms（实验前基准各服务约 10–500ms）。

### 步骤 4：检查重启计数

```bash
kubectl get pods -n online-boutique --no-headers | \
  awk '$4 > 0 {print "  ⚠️ 重启次数异常:", $1, "重启:", $4}'
kubectl get pods -n online-boutique --no-headers | \
  awk 'BEGIN{r=0} $4>0{r++} END{if(r==0) print "  ✅ 所有 Pod 无异常重启"}'
```

### 步骤 5：生成恢复报告

```
自我恢复验证报告
================
实验后时间点: <now>

Pod 状态:       ✅ 13/13 Running  /  ⚠️ X/13
错误率 (2m):    ✅ 全部 < 1%      /  ⚠️ <service>: X%
P99 延迟 (2m):  ✅ 全部 < 2s      /  ⚠️ <service>: Xms
重启计数:       ✅ 无异常重启      /  ⚠️ <pod>: X次

恢复时间估算 (从实验结束):
- Pod 就绪: ~Xs
- 错误率清零: ~Xm

整体评价: ✅ 通过  /  ⚠️ 待观察 (建议 2min 后重新检查)
```

## 核心原则

**告警规则必须代码固化** — 告警规则保留在 `deploy/monitoring/alerting/chaos-testing-alerts.yaml`，本 skill 只做状态验证。

## 验收标准

- [x] kubectl 查询所有 Pod 就绪状态（不依赖 Chaos Mesh）
- [x] Prometheus spanmetrics 查询错误率和 P99 延迟
- [x] 检查 Pod 重启计数
- [x] 给出通过/待观察的明确结论
