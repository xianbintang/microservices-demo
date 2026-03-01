# 混沌实验故障排除指南

## 常见问题和解决方案

### 实验被拒绝（命名空间/资源黑名单）

#### 问题
尝试创建实验时被拒绝，提示命名空间或资源在黑名单中。

#### 根本原因
- 实验目标在禁止的命名空间中（如 monitoring、kube-system）
- 实验目标在资源黑名单中

#### 解决方案
1. 检查实验 YAML 的 `selector.namespaces` 配置
2. 确保目标命名空间在允许列表中（online-boutique）
3. 避免对监控组件或系统组件注入故障

```yaml
# 正确配置
selector:
  namespaces:
    - online-boutique
```

---

### 告警覆盖度不足

#### 问题
告警覆盖度检查失败，无法执行实验。

#### 根本原因
- 关键告警场景缺失
- 告警规则配置错误
- 告警阈值不合理

#### 解决方案
1. 运行告警覆盖度检查，识别缺失的告警
2. 添加缺失的告警规则
3. 重新执行告警覆盖度检查

```bash
# 检查告警覆盖度
/chaos-check-alerts online-boutique

# 添加告警规则后重新检查
```

详见 [告警覆盖度检查指南](./alert-coverage-check-guide.md)

---

### Pod 无法恢复（资源不足、镜像拉取失败）

#### 问题
Pod 崩溃后无法重建，持续处于 CrashLoopBackOff 状态。

#### 根本原因
- 镜像拉取失败
- 资源不足
- 应用启动失败
- 配置错误

#### 解决方案
1. 检查 Pod 事件

```bash
kubectl describe pod <pod-name> -n online-boutique
```

2. 检查 Pod 日志

```bash
kubectl logs <pod-name> -n online-boutique
```

3. 检查镜像是否可拉取

```bash
kubectl get pods -n online-boutique -o jsonpath='{.items[*].spec.containers[*].image}'
```

4. 调整资源配置

```yaml
resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 512Mi
```

---

### 告警不触发（告警规则缺失、阈值不合理）

#### 问题
混沌实验期间预期告警未触发。

#### 根本原因
- 告警规则缺失
- 告警阈值过高
- 告警表达式错误
- Prometheus 抓取失败

#### 解决方案
1. 检查告警规则是否存在

```bash
kubectl get prometheusrules -A
kubectl describe promethearule <name> -n monitoring
```

2. 查询 Prometheus 中的指标

```bash
kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090:9090

# 在 Prometheus UI 中查询指标
# http://localhost:9090/graph
```

3. 调整告警阈值

```yaml
- alert: HighLatency
  expr: histogram_quantile(0.95, ...) > 1000  # 降低阈值
  for: 5m
```

4. 验证告警规则评估

```bash
# 在 Prometheus UI 中测试告警表达式
# http://localhost:9090/graph
```

详见 [告警验证指南](./alert-validation-guide.md)

---

### 告警不恢复（告警规则配置错误）

#### 问题
故障恢复后告警未自动恢复。

#### 根本原因
- 告警表达式错误
- `for` 时间过长
- 条件判断逻辑错误

#### 解决方案
1. 检查告警表达式是否正确反映恢复条件

```yaml
# 错误示例：持续触发
- alert: PodNotReady
  expr: kube_pod_status_phase{phase="Running"} == 0
  for: 10m  # for 时间过长

# 正确示例：及时恢复
- alert: PodNotReady
  expr: kube_pod_status_phase{phase="Running"} == 0
  for: 1m
```

2. 检查告警恢复逻辑

```bash
# 查询告警状态
ALERTS{alertname="PodNotReady"}

# 检查是否应该恢复
# 条件满足时告警应该自动恢复
```

3. 手动清除告警（仅用于测试）

```bash
# 重启 Prometheus
kubectl rollout restart deployment prometheus-kube-prometheus-prometheus -n monitoring
```

---

### 自我恢复失败（资源限制、健康检查配置问题）

#### 问题
故障移除后系统无法自动恢复。

#### 根本原因
- 资源限制过于严格
- 健康检查配置不合理
- 应用启动失败
- 连接泄漏

#### 解决方案
1. 检查健康检查配置

```yaml
livenessProbe:
  httpGet:
    path: /healthz
    port: 8080
  initialDelaySeconds: 30
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3

readinessProbe:
  httpGet:
    path: /readyz
    port: 8080
  initialDelaySeconds: 10
  periodSeconds: 5
  timeoutSeconds: 3
  failureThreshold: 3
```

2. 调整资源限制

```yaml
resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 512Mi
```

3. 检查应用启动日志

```bash
kubectl logs <pod-name> -n online-boutique
```

4. 实现优雅终止

```yaml
terminationGracePeriodSeconds: 30
lifecycle:
  preStop:
    exec:
      command: ["/bin/sh","-c","sleep 15"]
```

详见 [自我恢复能力验证指南](./self-healing-validation-guide.md)

---

### 观察数据缺失（Prometheus 抓取失败、Grafana 大盘未更新）

#### 问题
混沌实验期间无法获取指标数据，Grafana 大盘显示无数据。

#### 根本原因
- Prometheus 抓取失败
- ServiceMonitor/Service 配置错误
- 标签不匹配
- 数据被过滤

#### 解决方案
1. 检查 Prometheus 目标状态

```bash
kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090:9090

# 在 Prometheus UI 中检查目标状态
# http://localhost:9090/targets
```

2. 检查 ServiceMonitor 配置

```bash
kubectl get servicemonitor -A
kubectl describe servicemonitor <name> -n monitoring
```

3. 验证指标可查询

```bash
# 在 Prometheus UI 中查询指标
# http://localhost:9090/graph
sum(rate(traces_spanmetrics_calls_total[5m]))
```

4. 检查标签匹配

```bash
# 检查指标标签
traces_spanmetrics_calls_total{namespace="online-boutique"}
```

5. 重启 Grafana sidecar

```bash
kubectl rollout restart deployment grafana -n monitoring
```

---

### 实验无法中止（CRD 删除、资源清理）

#### 问题
无法中止混沌实验，故障持续存在。

#### 根本原因
- Chaos Mesh 控制器故障
- CRD 删除失败
- 权限不足
- 资源卡住

#### 解决方案
1. 尝试删除实验 CRD

```bash
kubectl delete podchaos <name> -n monitoring
kubectl delete networkchaos <name> -n monitoring
kubectl delete stresschaos <name> -n monitoring
```

2. 强制删除卡住的资源

```bash
kubectl delete podchaos <name> -n monitoring --force --grace-period=0
```

3. 重启 Chaos Mesh 控制器

```bash
kubectl rollout restart deployment chaos-controller-manager -n monitoring
```

4. 检查控制器日志

```bash
kubectl logs -l app.kubernetes.io/component=controller-manager -n monitoring
```

5. 清理残留资源

```bash
# 检查是否有残留的 Chaos Mesh 资源
kubectl get podchaos -A
kubectl get networkchaos -A
kubectl get stresschaos -A

# 删除所有实验资源
kubectl delete podchaos --all -A
kubectl delete networkchaos --all -A
kubectl delete stresschaos --all -A
```

---

### Chaos Mesh 控制器故障

#### 问题
Chaos Mesh 控制器无法正常工作，实验无法创建或删除。

#### 根本原因
- 控制器 Pod 崩溃
- CRD 未正确安装
- 权限配置错误
- 网络问题

#### 解决方案
1. 检查控制器 Pod 状态

```bash
kubectl get pods -n monitoring -l app.kubernetes.io/component=controller-manager
```

2. 检查控制器日志

```bash
kubectl logs -l app.kubernetes.io/component=controller-manager -n monitoring
```

3. 验证 CRD 已安装

```bash
kubectl get crd | grep chaos
```

4. 重启控制器

```bash
kubectl rollout restart deployment chaos-controller-manager -n monitoring
```

5. 重新安装 Chaos Mesh

```bash
helm uninstall chaos-mesh -n monitoring
helm install chaos-mesh chaos-mesh/chaos-mesh \
  --namespace monitoring \
  --values deploy/monitoring/chaos-mesh-values.yaml
```

---

### 大盘显示异常

#### 问题
Grafana 大盘显示错误、数据不正确或面板加载失败。

#### 根本原因
- 大盘 JSON 格式错误
- 数据源配置错误
- 查询表达式错误
- 标签不匹配

#### 解决方案
1. 检查大盘 JSON 格式

```bash
kubectl get configmap grafana-dashboard-chaos-experiments -n monitoring -o json
```

2. 验证数据源配置

```bash
# 在 Grafana UI 中检查数据源
# Configuration > Data Sources
```

3. 测试查询表达式

```bash
# 在 Prometheus UI 中测试查询
# http://localhost:9090/graph
```

4. 重启 Grafana

```bash
kubectl rollout restart deployment grafana -n monitoring
```

5. 重新加载大盘

```bash
# Grafana sidecar 会自动检测 ConfigMap 变化
# 或手动重启 sidecar
kubectl rollout restart deployment grafana -n monitoring
```

---

## Chaos Mesh CLI 和 Web UI 使用方法

### CLI 命令

```bash
# 列出所有实验
kubectl get podchaos -n monitoring
kubectl get networkchaos -n monitoring
kubectl get stresschaos -n monitoring

# 查看实验详情
kubectl describe podchaos <name> -n monitoring

# 删除实验
kubectl delete podchaos <name> -n monitoring

# 应用实验 YAML
kubectl apply -f deploy/chaos/pod-failure.yaml

# 查看 Chaos Mesh 日志
kubectl logs -l app.kubernetes.io/component=controller-manager -n monitoring
```

### Web UI 使用

1. 访问 Chaos Mesh Dashboard

```bash
# 端口转发
kubectl port-forward -n monitoring svc/chaos-dashboard 2333:2333

# 访问 UI
# http://localhost:2333
```

2. 创建实验
   - 导航到 "Workflow" 或 "Experiment"
   - 选择实验类型
   - 配置实验参数
   - 提交实验

3. 查看实验状态
   - 导航到 "Workflow" 或 "Experiment"
   - 选择实验查看详情
   - 查看实验进度和事件

4. 中止实验
   - 选择实验
   - 点击 "Abort" 按钮
   - 确认中止

5. 查看实验历史
   - 导航到 "Workflow" 或 "Experiment"
   - 查看历史实验列表

---

## 获取帮助

如果遇到以上文档未涵盖的问题，可以：

1. 检查 Chaos Mesh 官方文档: https://chaos-mesh.org/docs
2. 查看 Chaos Mesh GitHub Issues: https://github.com/chaos-mesh/chaos-mesh/issues
3. 查看应用日志和 Kubernetes 事件
4. 使用 Claude Code skills 进行诊断

---

## 相关文档

- [混沌实验运行手册](./runbook.md)
- [告警覆盖度检查指南](./alert-coverage-check-guide.md)
- [告警验证指南](./alert-validation-guide.md)
- [自我恢复能力验证指南](./self-healing-validation-guide.md)
