# Self-Hosted Observability Stack

自建可观测性栈，用于替代火山引擎 APM Plus。

## 架构

```
online-boutique namespace
  微服务群 (OTLP gRPC 4317)
      │
      ▼
  otel-collector-self (Deployment)
      ├── prometheusremotewrite ──→ Prometheus:9090
      ├── otlp/tempo            ──→ Tempo:4317
      └── loki                  ──→ Loki:3100

monitoring namespace
  Prometheus + AlertManager (kube-prometheus-stack)
  Grafana (LoadBalancer)
  Loki (SingleBinary)
  Promtail DaemonSet
  Tempo (OTLP receiver)
```

## 快速部署

```bash
# 1. 创建 namespace
kubectl create namespace monitoring

# 2. 添加 Helm 仓库
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

# 3. 部署 kube-prometheus-stack
helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  -n monitoring \
  -f kube-prometheus-stack-values.yaml \
  --version 65.5.0 \
  --wait --timeout 10m

# 4. 部署 Loki
helm upgrade --install loki grafana/loki \
  -n monitoring \
  -f loki-values.yaml \
  --version 6.6.2 \
  --wait --timeout 5m

# 5. 部署 Promtail
helm upgrade --install promtail grafana/promtail \
  -n monitoring \
  -f promtail-values.yaml \
  --wait --timeout 5m

# 6. 部署 Tempo
helm upgrade --install tempo grafana/tempo \
  -n monitoring \
  -f tempo-values.yaml \
  --version 1.10.3 \
  --wait --timeout 5m

# 7. 应用告警规则
kubectl apply -f alerting/ -n monitoring
```

## 访问 Grafana

```bash
# 获取 Grafana 外网 IP
kubectl get svc kube-prometheus-stack-grafana -n monitoring

# 默认账号: admin / admin (首次登录需修改)
```

## 切换到自建栈

修改 `deploy/values-volc.yaml`:

```yaml
volcengineAPM:
  enabled: false

selfHostedObservability:
  enabled: true
```

然后重新部署应用：

```bash
make -f Makefile.volc deploy
```

## 组件说明

| 组件 | 用途 | 端口 |
|------|------|------|
| Prometheus | 指标存储和查询 | 9090 |
| Grafana | 统一可视化 | 3000 (LB) |
| AlertManager | 告警路由 | 9093 |
| Loki | 日志聚合 | 3100 |
| Promtail | 日志采集 | - |
| Tempo | 链路追踪 | 4317 (OTLP) |

## 告警通知

钉钉 Webhook 配置位于 `alerting/dingtalk-webhook.yaml`，需要填入实际的钉钉机器人 Token。

## Dashboard

预置 Dashboard 位于 `dashboards/` 目录，可通过 Grafana UI 导入。

## 故障排查

```bash
# 查看 Collector 日志
kubectl logs -n online-boutique deploy/otel-collector-self

# 检查 Prometheus targets
kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090
# 访问 http://localhost:9090/targets

# 检查 Loki 日志
kubectl logs -n monitoring -l app.kubernetes.io/name=loki
```