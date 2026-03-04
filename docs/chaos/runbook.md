# 混沌实验运行手册 (Runbook)

## 概述

本文档提供了 Online Boutique 混沌实验的完整操作指南，包括前置检查、执行步骤、观察指标、验证点和故障排除。

## 核心原则

**告警规则必须代码固化** - 所有告警规则必须存储在代码仓库中（`deploy/monitoring/alerting/`），禁止使用临时 `kubectl apply` 命令创建告警规则。

任何告警规则的变更必须遵循以下流程：
1. 修改 `deploy/monitoring/alerting/` 目录下的 YAML 文件
2. 提交代码并通过代码审查
3. 部署到目标环境
4. 验证告警规则生效

**违反原则的后果**：
- 临时创建的告警规则在 Pod 重启后会丢失
- 无法追溯告警规则的变更历史
- 无法在不同环境间一致部署
- 无法进行代码审查和合规检查

## 前置条件

### 1. 告警覆盖度检查

在执行混沌实验前，**必须**进行告警覆盖度检查，确保关键场景都有告警覆盖。

```bash
/chaos-check-alerts online-boutique
```

#### 关键告警场景清单

| 类别 | 关键场景 | 必需告警 | 严重级别 |
|------|---------|---------|---------|
| Pod 状态 | Pod 崩溃/终止 | PodDown/PodNotReady | Critical |
| Pod 状态 | Pod 重启次数过多 | PodRestartTooMany | Warning |
| Pod 状态 | Pod CrashLoopBackOff | PodCrashLoopBackOff | Critical |
| 服务可用性 | 服务完全不可用 | ServiceDown | Critical |
| 服务可用性 | 服务部分不可用 | ServiceUnavailable | Warning |
| 性能指标 | 高延迟（P95） | HighLatency | Warning |
| 性能指标 | 高错误率 | HighErrorRate | Warning |
| 性能指标 | 高 5xx 率 | High5xxRate | Critical |
| 资源使用 | CPU 使用率过高 | HighCPUUsage | Warning |
| 资源使用 | 内存使用率过高 | HighMemoryUsage | Warning |
| 资源使用 | Pod OOM | PodOOMKilled | Critical |
| 资源使用 | CPU 节流严重 | CPUThrottlingHigh | Warning |
| 依赖服务 | 上游错误率高 | DependencyErrorRateHigh | Warning |
| 依赖服务 | 依赖服务超时 | DependencyTimeout | Warning |
| 熔断器 | 熔断器打开 | CircuitBreakerOpen | Warning |

#### 告警覆盖率阈值

- **总体覆盖率**: ≥ 80%
- **关键场景覆盖率**: 100% (所有 Critical 级别场景必须有告警覆盖)

#### 阻塞状态

如果告警覆盖度不足：
- 覆盖率 < 80% → 阻塞实验执行
- 关键场景缺失 → 阻塞实验执行
- 建议: 补充缺失的告警规则后重新检查

---

## 实验类型

### 1. Pod 故障实验 (Pod Failure)

#### 目标
验证应用在 Pod 突然终止时的自愈能力，包括自动重启、连接重建和状态恢复。

#### 预期行为
- Pod 终止 → Kubernetes 重建 Pod → 服务恢复

#### 预期告警
- `ChaosPodNotReady` (Critical)
- `ChaosServiceDown` (Critical) - 仅在所有副本均不可用时触发

#### 执行步骤

```bash
# 使用 Claude Code skill
/chaos-inject-pod [service] [duration]

# 示例：对 frontend 服务执行 2 分钟的 Pod 故障实验
/chaos-inject-pod frontend 2m

# 或手动应用 YAML
kubectl apply -f deploy/chaos/pod-failure.yaml
```

#### 观察指标

**Pod 状态**
- `kube_pod_status_phase{namespace="online-boutique"}` - Pod 阶段
- `kube_pod_container_status_ready{namespace="online-boutique"}` - 容器就绪状态
- `kube_pod_container_status_restarts_total{namespace="online-boutique"}` - 重启次数

**服务可用性**
- `up{job="blackbox-exporter"}` - 服务可用性
- `traces_spanmetrics_calls_total{namespace="online-boutique"}` - 请求量

**性能指标**
- `traces_spanmetrics_duration_milliseconds_bucket{namespace="online-boutique"}` - 延迟分布
- `rate(traces_spanmetrics_calls_total{http_response_status_code=~"5.."}[5m])` - 5xx 错误率

**告警状态**
- `ALERTS{alertstate="firing", namespace="online-boutique"}` - 触发的告警

#### 验证点

**自我恢复能力验证**
- [ ] Pod 自动重建并在 60s 内 Ready
- [ ] Service 自动更新 endpoints
- [ ] 流量自动切换到健康 Pod
- [ ] 无资源泄漏（连接、文件描述符）
- [ ] 无需人工干预完全恢复

**告警验证**
- [ ] PodNotReady 告警在 30s 内触发
- [ ] 告警标签正确（namespace、service、pod）
- [ ] PodReady 后告警在 60s 内恢复
- [ ] 无预期外的告警误报

#### 验收标准

- [ ] Pod 在 60s 内恢复 Ready
- [ ] Service endpoints 在 30s 内更新
- [ ] 错误率 spike 不超过 10%
- [ ] 5 分钟内 QPS 恢复到基准的 90% 以上
- [ ] 无持久化资源泄漏
- [ ] 无人工干预情况下系统完全自动恢复
- [ ] **告警验收标准**: 全部通过

#### 故障排除

| 问题 | 表现 | 根本原因 | 解决方案 |
|------|------|---------|---------|
| Pod 无法恢复 | Pod 持续 CrashLoopBackOff | 应用启动失败、资源不足 | 检查应用日志、调整资源配置 |
| 告警未触发 | 实验期间无告警 | 告警规则缺失或阈值不合理 | 检查告警规则、调整阈值 |
| 恢复时间过长 | Pod 重建超过 60s | 镜像拉取慢、启动时间长 | 优化镜像、增加资源 |

---

### 2. 网络延迟实验 (Network Latency)

#### 目标
验证应用在高网络延迟下的超时处理、重试逻辑和用户体验降级。

#### 预期行为
- 延迟注入 → 超时/重试/熔断 → 移除延迟 → 恢复

#### 预期告警
- `ChaosHighLatency` (Warning) - P95 延迟 > 2s
- `ChaosHighErrorRate` (Critical) - 错误率 > 10%

#### 执行步骤

```bash
# 使用 Claude Code skill
/chaos-inject-network [service] [latency] [duration]

# 示例：对 recommendationservice 注入 500ms 延迟，持续 3 分钟
/chaos-inject-network recommendationservice 500ms 3m

# 或手动应用 YAML
kubectl apply -f deploy/chaos/network-latency.yaml
```

#### 观察指标

**延迟指标**
- `histogram_quantile(0.95, traces_spanmetrics_duration_milliseconds_bucket{namespace="online-boutique"})` - P95 延迟
- `histogram_quantile(0.99, traces_spanmetrics_duration_milliseconds_bucket{namespace="online-boutique"})` - P99 延迟

**超时和重试**
- `rate(traces_spanmetrics_calls_total{status_code="timeout"}[5m])` - 超时率
- `rate(traces_spanmetrics_calls_total{status_code="canceled"}[5m])` - 取消率

**熔断器状态**
- 需要应用暴露熔断器指标

#### 验证点

**自我恢复能力验证**
- [ ] 延迟移除后应用性能自动恢复
- [ ] 连接池无泄漏
- [ ] 无慢恢复现象
- [ ] 重试机制自动恢复

**告警验证**
- [ ] HighLatency 告警在 P95 超过阈值后触发
- [ ] High5xxRate 告警在错误率超过阈值后触发
- [ ] 延迟恢复后告警及时恢复
- [ ] 告警标签准确

#### 验收标准

- [ ] P95 延迟 spike 符合注入量 + 处理时间
- [ ] 超时仅在延迟超过配置阈值时发生
- [ ] 重试次数符合配置策略
- [ ] 移除延迟后无"慢恢复"现象
- [ ] 无级联故障
- [ ] **告警验收标准**: 全部通过

---

### 3. 依赖故障实验 (Dependency Failure)

#### 目标
验证应用在依赖服务不可用时的优雅降级、熔断和缓存机制。

#### 预期行为
- 服务不可用 → 降级/熔断 → 恢复服务 → 流量恢复

#### 预期告警
- `ChaosHighErrorRate` (Critical) - 上游服务错误率 > 10%
- `ChaosPodRestart` (Warning) - 依赖不可用导致 Pod 重启

注意：Online Boutique 未实现熔断器，CircuitBreakerOpen 告警不会触发。

#### 执行步骤

```bash
# 使用 Claude Code skill
/chaos-inject-dependency [upstream] [dependency] [duration]

# 示例：隔离 adservice，测试 frontend 的依赖容错能力
/chaos-inject-dependency frontend adservice 3m

# 或手动应用 YAML
kubectl apply -f deploy/chaos/dependency-failure.yaml
```

#### 观察指标

**上游错误率**
- `rate(traces_spanmetrics_calls_total{service_name="frontend",http_response_status_code=~"5.."}[5m])`

**熔断器状态**
- 需要应用暴露熔断器指标

**降级命中率**
- 需要应用暴露降级指标

**缓存命中率**
- 需要应用暴露缓存指标

#### 验证点

**自我恢复能力验证**
- [ ] 熔断器自动打开和关闭
- [ ] 依赖恢复后流量自动恢复
- [ ] 无惊群效应
- [ ] 缓存自动预热

**告警验证**
- [ ] ServiceUnavailable 告警及时触发
- [ ] DependencyErrorRateHigh 告警准确触发
- [ ] CircuitBreakerOpen 告警在熔断器打开时触发
- [ ] 服务恢复后告警及时恢复

#### 验收标准

- [ ] 依赖故障不导致级联故障
- [ ] 熔断器正确打开和恢复
- [ ] 降级机制有效，用户体验保持可用
- [ ] 无重试风暴
- [ ] 恢复后流量平滑过渡
- [ ] **告警验收标准**: 全部通过

---

### 4. 资源耗尽实验 (Resource Exhaustion)

#### 目标
验证应用在 CPU 或内存资源紧张时的表现，包括节流、OOM 保护和 graceful degradation。

#### 预期行为
- CPU/内存压力 → 节流/OOM → 移除压力 → 恢复

#### 预期告警
- `ChaosHighCPUUsage` (Warning) - CPU > 0.5 cores 持续 1m
- `ChaosHighMemoryUsage` (Warning) - 内存 > 400MiB 持续 1m
- `ChaosOOMKilled` (Critical) - 容器被 OOM 终止
- `ChaosCPUThrottling` (Warning) - CPU 节流 > 50% 持续 1m

#### 执行步骤

```bash
# 使用 Claude Code skill
/chaos-inject-resource [service] [type] [value] [duration]

# 示例：对 checkoutservice 应用 80% 内存压力
/chaos-inject-resource checkoutservice memory 80 5m

# 或手动应用 YAML
kubectl apply -f deploy/chaos/resource-exhaustion.yaml
```

#### 观察指标

**资源使用**
- `container_cpu_usage_seconds_total{namespace="online-boutique"}` - CPU 使用
- `container_memory_working_set_bytes{namespace="online-boutique"}` - 内存使用
- `container_cpu_cfs_throttled_periods_total` - CPU 节流

**OOM 事件**
- `kube_pod_container_status_terminated_reason{reason="OOMKilled"}` - OOM 终止

**性能指标**
- `rate(traces_spanmetrics_calls_total{namespace="online-boutique"}[5m])` - QPS
- `histogram_quantile(0.95, traces_spanmetrics_duration_milliseconds_bucket{namespace="online-boutique"})` - P95 延迟

#### 验证点

**自我恢复能力验证**
- [ ] CPU/Memory 限制正确配置并生效
- [ ] 资源紧张时应用表现符合预期（节流或 OOM）
- [ ] 不影响其他 Pod（通过 QoS 隔离）
- [ ] 资源移除后应用正常恢复

**告警验证**
- [ ] HighCPUUsage 告警在 CPU 使用率超过阈值后触发
- [ ] HighMemoryUsage 告警在内存使用率超过阈值后触发
- [ ] PodOOMKilled 告警在 OOM 时立即触发
- [ ] 资源恢复后告警及时恢复

#### 验收标准

- [ ] 资源限制正确配置并生效
- [ ] 资源紧张时应用表现符合预期
- [ ] 不影响其他 Pod（通过 QoS 隔离）
- [ ] 资源移除后应用正常恢复
- [ ] 可观测性清晰反映资源状态
- [ ] 无系统性资源饥饿
- [ ] **告警验收标准**: 全部通过

---

### 5. 级联故障实验 (Cascade Failure)

#### 目标
验证系统在多个故障同时发生时的弹性，包括隔离机制、断路器和熔断链。

#### 预期行为
- 多个故障 → 隔离/熔断 → 移除故障 → 逐层恢复

#### 预期告警
- `ChaosPodNotReady` (Critical) - adservice 被 kill
- `ChaosServiceDown` (Critical) - adservice 所有副本不可用
- `ChaosHighMemoryUsage` (Warning) - checkoutservice 内存压力
- `ChaosHighLatency` (Warning) - 若 NetworkChaos 注入成功

#### 执行步骤

```bash
# 使用 Claude Code skill
/chaos-inject-cascade [config]

# 示例：使用默认级联故障配置
/chaos-inject-cascade default

# 或手动应用 YAML
kubectl apply -f deploy/chaos/cascade-failure.yaml
```

#### 观察指标

**系统可用性**
- `up{job="blackbox-exporter"}` - 服务可用性

**错误传播**
- `rate(traces_spanmetrics_calls_total{http_response_status_code=~"5.."}[5m]) by (service_name)` - 错误率

**熔断链**
- 需要应用暴露熔断器链指标

**资源隔离**
- `container_cpu_usage_seconds_total{namespace="online-boutique"}` by (pod) - 每个资源使用

#### 验证点

**自我恢复能力验证**
- [ ] 级联故障被隔离在故障服务，不传播到其他服务
- [ ] 熔断器链正确工作，防止雪崩
- [ ] 系统核心功能保持可用
- [ ] 资源隔离生效
- [ ] 恢复时系统逐层恢复，无二次故障

**告警验证**
- [ ] CascadeFailureDetected 告警在检测到级联故障时触发
- [ ] ServiceUnavailable 告警准确反映受影响的服务
- [ ] SystemDegraded 告警反映整体系统降级程度
- [ ] 告警标签准确标识故障传播路径和影响范围

#### 验收标准

- [ ] 级联故障被有效隔离
- [ ] 系统关键功能保持可用
- [ ] 熔断器链正确工作
- [ ] 资源隔离生效
- [ ] 恢复时系统平滑过渡
- [ ] 可观测性完整记录级联故障和恢复
- [ ] **告警验收标准**: 全部通过

---

## 通用验证流程

### 1. 实验监控

```bash
# 使用 Claude Code skill 实时监控
/chaos-monitor [experiment-id]

# 或使用 Grafana 大盘
# http://<grafana-url>/d/chaos-experiments
```

### 2. 告警验证

```bash
# 使用 Claude Code skill 验证告警
/chaos-validate-alerts [experiment-id]
```

### 3. 自我恢复验证

```bash
# 使用 Claude Code skill 验证自我恢复
/chaos-validate-self-heal [experiment-id]
```

### 4. 生成实验报告

```bash
# 使用 Claude Code skill 生成完整报告
/chaos-report [experiment-id]
```

### 5. 中止实验

```bash
# 使用 Claude Code skill 中止实验
/chaos-abort [experiment-id]

# 或手动删除实验 CRD（注意：CRD 在 chaos-mesh namespace）
kubectl delete podchaos <name> -n chaos-mesh
kubectl delete networkchaos <name> -n chaos-mesh
kubectl delete stresschaos <name> -n chaos-mesh
```

---

## 实验后清理

实验完成后，确保所有资源已正确清理：

```bash
# 检查运行中的实验（CRD 在 chaos-mesh namespace）
kubectl get podchaos -n chaos-mesh
kubectl get networkchaos -n chaos-mesh
kubectl get stresschaos -n chaos-mesh

# 确认无残留资源
kubectl get all -n online-boutique

# 检查 Pod 状态
kubectl get pods -n online-boutique
```

---

## kind 本地环境已知限制

本节记录在 kind 本地集群（Mac ARM64 + podman）中运行混沌实验的已知限制和解决方案。

### NetworkChaos 延迟注入（源 Pod 模式）不可用

**现象**: 对 `recommendationservice`、`adservice` 等源 Pod 注入延迟时，chaos-daemon 报错 `unable to flush ip sets`，实验状态为 `NotInjected`。

**根因**: kind 容器内核不加载 `ip_set` 模块，ipset 命令不可用。

**替代方案**:
- 使用 `action: partition` + `direction: both` 对**目标 Pod**做网络隔离（已验证：redis-cart target partition 成功）
- 对 `cartservice` 测试 Redis 依赖故障时，指定 `app: redis-cart` 为目标

**已验证可用的实验类型**:
- PodChaos (pod-kill): ✅ 完全可用
- StressChaos (cpu/memory stress): ✅ 完全可用（需 SECURITY_MODE=true）
- NetworkChaos (partition, target pod): ✅ 可用
- NetworkChaos (delay, source pod): ❌ 不可用（ipset 限制）

### StressChaos 需要 SECURITY_MODE 环境变量

**现象**: StressChaos 创建后卡在 `Injecting` 状态，chaos-controller-manager 日志出现 `error reading server preface: EOF`。

**根因**: chaos-controller-manager deployment 的 `SECURITY_MODE` 等 mTLS 环境变量丢失，控制器用非 TLS 方式连接要求 TLS 的 chaos-daemon。

**排查命令**:
```bash
kubectl get deployment -n monitoring chaos-controller-manager -o json | \
  python3 -c "import sys,json; d=json.load(sys.stdin); envs={e['name'] for c in d['spec']['template']['spec']['containers'] for e in c.get('env',[])}; print(envs)"
```

**修复**: 确认 `SECURITY_MODE`, `CHAOS_DAEMON_CLIENT_CERT`, `CHAOS_DAEMON_CLIENT_KEY`, `CHAOS_MESH_CA_CERT` 等环境变量存在，详见 [故障排除指南](./troubleshooting.md)。

### Helm upgrade SSA 冲突

**现象**: `helm upgrade chaos-mesh` 失败，报 `conflicts with "before-first-apply" using apps/v1`。

**根因**: 通过 `kubectl patch` 修改过的字段引入了与 Helm SSA（Server-Side Apply）不兼容的字段管理者冲突。

**解决方案**: 使用 `kubectl patch` 直接修改 deployment，不通过 Helm 修改，详见 [故障排除指南](./troubleshooting.md)。

---

## 安全限制

### 命名空间限制
- 允许的命名空间: `online-boutique`
- 禁止的命名空间: `monitoring`, `kube-system`, `kube-public`

### 参数限制
- 最大实验时长: 10 分钟
- 最大网络延迟: 2000ms
- 最大网络丢包率: 20%
- 最大 CPU 压力: 90%
- 最大内存压力: 80%

### 禁止的操作
- 删除命名空间
- 删除节点
- 删除服务
- 修改 kubelet

---

## 最佳实践

1. **永远在告警覆盖度检查通过后执行实验**
2. **从低影响的实验开始（如 Pod 故障），逐步增加复杂度**
3. **在开发/测试环境验证后再在生产环境执行**
4. **记录每次实验的结果和发现**
5. **根据实验结果持续改进告警规则和系统弹性**
6. **实验期间保持监控，随时准备中止**
7. **实验后进行完整的验证和分析**
8. **分享实验结果，促进团队学习**

---

## 故障排除指南

详见 [故障排除指南](./troubleshooting.md)

---

## 相关文档

- [告警覆盖度检查指南](./alert-coverage-check-guide.md)
- [告警验证指南](./alert-validation-guide.md)
- [自我恢复能力验证指南](./self-healing-validation-guide.md)
- [故障排除指南](./troubleshooting.md)
