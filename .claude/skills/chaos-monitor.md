# 混沌实验监控 skill

监控正在运行的混沌实验，显示实时状态和关键指标。

## 核心原则

**告警规则必须代码固化** - 所有告警规则必须存储在代码仓库中（`deploy/monitoring/alerting/`），禁止使用临时 `kubectl apply` 命令创建告警规则。

## 用法

```
/chaos-monitor [name]
```

### 参数

- `name`: 可选，指定实验名称（如 `pod-failure-experiment`，默认：显示所有运行中实验）

## 执行步骤

1. 查询所有运行中的 Chaos Mesh CRD：
   ```bash
   kubectl get podchaos,networkchaos,stresschaos --all-namespaces
   ```

2. 查询目标服务当前 Pod 状态：
   ```bash
   kubectl get pods -n online-boutique -l app=<service>
   ```

3. 查询实时错误率（Prometheus）：
   ```promql
   rate(traces_spanmetrics_calls_total{service_name="<service>",status_code!="STATUS_CODE_OK"}[1m])
   / rate(traces_spanmetrics_calls_total{service_name="<service>"}[1m])
   ```

4. 查询 P95 延迟（Prometheus）：
   ```promql
   histogram_quantile(0.95, rate(traces_spanmetrics_duration_milliseconds_bucket{service_name="<service>"}[1m]))
   ```

5. 查询当前触发的 Chaos 告警（Alertmanager）：
   ```bash
   kubectl exec -n monitoring alertmanager-kube-prometheus-stack-alertmanager-0 -- \
     wget -qO- 'http://localhost:9093/api/v2/alerts?filter=chaos_test%3D%22true%22'
   ```

## 输出示例

**有实验运行时：**
```
混沌实验监控
============
运行中的实验: 1

实验: pod-failure-experiment (online-boutique)
-------------------------------------
类型: PodChaos - pod-kill
目标服务: frontend
状态: Running

实时指标:
Pod 状态: 0/1 Ready ⚠️
错误率: 3.2% (基准: ~0%) ⚠️
P95 延迟: 180ms (基准: ~80ms)

触发告警:
⚡ ChaosPodNotReady (30s 前)
⚡ ChaosPodRestart (45s 前)

Grafana: http://localhost:3000 (在线 boutique 大盘)

下一步:
- 使用 /chaos-validate-alerts 验证告警触发
- 使用 /chaos-validate-self-heal 验证自我恢复
- 使用 /chaos-abort 中止实验
```

**无实验运行时：**
```
混沌实验监控
============
运行中的实验: 0

kubectl get podchaos,networkchaos,stresschaos --all-namespaces
→ No resources found

状态: 无运行中实验，可以发起新实验
```

## 验收标准

- [x] 能正确查询运行中的实验（`--all-namespaces`）
- [x] 能获取实时关键指标（Pod 状态、错误率、P95 延迟）
- [x] 能显示告警状态（通过 Alertmanager API）
- [x] 能在无实验时输出"无运行中实验"而非报错
- [x] 能提供下一步操作指引
