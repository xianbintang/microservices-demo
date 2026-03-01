## 背景

Online Boutique 微服务演示部署在 Kubernetes 上，配有完整的可观测性栈，包括 Prometheus、Grafana、Loki、Tempo 和 AlertManager。虽然系统有全面的监控，但缺乏通过混沌工程进行的系统化弹性测试。

当前状态：
- 微服务位于 `online-boutique` 命名空间（frontend、checkoutservice、adservice、recommendationservice 等）
- 可观测性栈位于 `monitoring` 命名空间
- 未部署混沌工程工具
- 无系统化的故障注入或弹性测试
- 告警规则存在但未经过系统性验证

约束：
- 必须与现有部署和可观测性栈集成
- 必须使用现有的 Helm 部署方式
- 不得影响生产稳定性（需要防护机制）
- 告警必须真实记录，不得抑制

## 目标 / 非目标

**目标：**
- 部署具有故障注入能力的混沌工程工具
- 为常见的 Online Boutique 故障场景提供预定义实验
- 与现有可观测性栈集成以进行监控
- 建立防护机制以防止破坏性实验
- 记录运行和分析混沌实验的工作流程
- 使用混沌工程验证告警系统的完整性和有效性
- 建立告警验证流程，确保告警在正确时间触发

**非目标：**
- 生产环境中的混沌实验（初始范围：开发/测试）
- CI/CD 流水线中的自动化混沌测试（未来增强）
- 与外部 SRE 平台集成
- 多集群场景的混沌实验
- 抑制混沌实验期间的告警

## 决策

### 1. Chaos Mesh vs Chaos Monkey

**决策：** 使用 Chaos Mesh

**理由：**
- Chaos Mesh 是云原生的 Kubernetes 原生混沌工程平台
- 提供丰富的故障注入类型（Pod、网络、压力等）
- 具有内置的安全机制和防护
- 与可观测性栈集成良好
- 支持 Web UI 进行实验管理
- 活跃的开源社区（CNCF 沙箱项目）

**考虑的替代方案：**
- **Chaos Monkey (Spotify)：** 更简单但缺乏 Kubernetes 原生集成和网络故障注入
- **Litmus：** 不错的选择，但 Chaos Mesh 具有更好的可观测性集成和 UI

### 2. 部署命名空间

**决策：** 将 Chaos Mesh 部署到 `monitoring` 命名空间

**理由：**
- 与可观测性基础设施逻辑契合
- 与现有基础设施模式一致
- 易于与 Prometheus、Grafana 等一起管理

**考虑的替代方案：**
- **新的 `chaos` 命名空间：** 更清晰的分离，但增加了运营开销

### 3. Helm Chart 来源

**决策：** 使用 `chaos-mesh/chaos-mesh` 仓库的官方 Chaos Mesh Helm chart

**理由：**
- 官方 chart 维护良好
- 遵循与 kube-prometheus-stack、Loki、Tempo 相同的部署模式
- 易于通过 `helm upgrade` 更新

### 4. 实验防护实现

**决策：** 多层防护

1. **命名空间白名单：** 将混沌实验限制在 `online-boutique` 命名空间
2. **资源黑名单：** 保护 `monitoring` 命名空间和 kube-system
3. **准入 Webhook：** 在创建前验证实验清单
4. **安全默认值：** 强制执行最大故障强度和时长限制

**理由：**
- 纵深防御方法
- Kubernetes 原生机制
- 符合 Chaos Mesh 最佳实践

### 5. 可观测性集成方法

**决策：** 使用现有可观测性栈和 Chaos Mesh 指标

**理由：**
- Chaos Mesh 暴露 Prometheus 指标用于实验状态
- 现有 Grafana 大盘已监控服务健康状况
- 添加专用混沌大盘用于实验特定视图
- 无需额外基础设施

**集成点：**
- Chaos Mesh 控制器指标 → Prometheus
- 混沌实验状态 → 自定义 Grafana 大盘
- 实验期间的告警验证 → AlertManager 记录
- 实验事件的 Loki 日志聚合

### 6. 告警验证策略

**决策：** 主动验证，不抑制告警

**理由：**
- 混沌工程的目的之一是验证告警系统的有效性
- 抑制告警会导致无法验证告警是否在正确时间触发
- 真实的告警记录有助于评估告警覆盖率和响应时间
- 混沌实验期间触发的告警是有价值的信号，不应被丢弃

**实现：**
- 每个混沌实验定义预期触发的告警列表
- 实验执行后验证告警是否触发
- 记录告警触发时间和故障时间的差值
- 识别告警缺失的场景并标记需要新增的告警规则
- 生成告警验证报告

### 7. 告警验证流程

**决策：** 三阶段验证流程

1. **准备阶段：** 定义实验应触发的告警
2. **执行阶段：** 观察告警触发情况
3. **分析阶段：** 对比预期和实际，生成报告

**原因：**
- 结构化验证流程确保覆盖所有关键场景
- 明确的预期告警列表便于自动化验证
- 分析报告提供可操作的改进建议

---

## 告警覆盖度检查设计

### 为什么需要告警覆盖度检查

混沌实验前检查告警覆盖度的重要性：

1. **及时发现能力不足**：如果关键场景没有告警覆盖，混沌实验引发故障时无法及时发现，可能导致问题扩大
2. **确保实验安全**：告警覆盖不足的实验存在风险，应该在补充告警后再执行
3. **提高实验价值**：良好的告警覆盖使混沌实验的验证结果更有意义

### 告警覆盖度检查清单

针对 Online Boutique 微服务，定义关键告警场景：

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

### 告警覆盖度检查流程

```
1. 执行前检查（Pre-Experiment Check）
   ├─ 扫描当前告警规则（PrometheusRule/AlertManagerConfig）
   ├─ 对比关键告警场景清单
   ├─ 识别缺失的告警规则
   ├─ 计算告警覆盖率
   └─ 生成告警覆盖度检查报告

2. 覆盖度评估（Coverage Assessment）
   ├─ 覆盖率 ≥ 80% 且关键场景全覆盖 → 允许执行实验
   └─ 覆盖率 < 80% 或关键场景缺失 → 阻止实验，提示补充告警

3. 告警补充（Alert Supplementation）
   ├─ 根据缺失场景生成告警规则模板
   ├─ 添加告警规则到部署
   ├─ 重新执行覆盖度检查
   └─ 通过后允许执行实验
```

### 告警覆盖度检查报告模板

```markdown
# 告警覆盖度检查报告

## 检查时间
2024-01-01 10:00:00

## 覆盖度统计
- 关键场景总数: 15
- 已覆盖场景数: 12
- 缺失场景数: 3
- 告警覆盖率: 80%

## 已覆盖的告警 ✅
| 场景 | 告警名称 | 严重级别 | 状态 |
|------|---------|---------|------|
| Pod 崩溃/终止 | PodNotReady | Critical | ✅ |
| 服务完全不可用 | ServiceDown | Critical | ✅ |
| 高延迟 | HighLatency | Warning | ✅ |
| ... | ... | ... | ... |

## 缺失的告警 ❌
| 场景 | 重要性 | 建议告警名称 | 建议严重级别 |
|------|--------|-------------|-------------|
| Pod CrashLoopBackOff | **关键** | PodCrashLoopBackOff | Critical |
| Pod OOM | **关键** | PodOOMKilled | Critical |
| 熔断器打开 | 重要 | CircuitBreakerOpen | Warning |

## 评估结果
- 覆盖率: 80% ⚠️
- 关键缺失: 2 个 ❌
- 建议: 补充关键缺失的告警规则后再执行混沌实验

## 操作建议
1. 添加 PodCrashLoopBackOff 告警规则（Critical）
2. 添加 PodOOMKilled 告警规则（Critical）
3. 添加 CircuitBreakerOpen 告警规则（Warning）
4. 重新执行告警覆盖度检查
5. 通过后执行混沌实验

## 阻塞状态
❌ 实验执行被阻塞，请补充缺失的告警规则
```

### 告警覆盖度检查自动化

为了提高效率，可以自动化告警覆盖度检查：

1. **自动扫描**：定期或实验前自动扫描告警规则
2. **自动评估**：自动计算覆盖率和识别缺失
3. **自动报告**：自动生成检查报告
4. **自动阻塞**：自动阻塞告警不足的实验

**实现方案：**
- 使用 Promtool 或直接查询 Prometheus API 获取告警规则
- 对比关键场景清单
- 生成报告并通过 webhook 发送通知

### 与混沌实验的集成

```
混沌实验执行流程（带告警覆盖度检查）:

1. 准备阶段
   └─ 运行告警覆盖度检查 ← 新增

2. 覆盖度评估
   ├─ 通过 → 继续执行实验
   └─ 不通过 → 阻塞，提示补充告警

3. 实验定义
   └─ 创建实验 YAML（包含预期告警列表）

4. 实验执行
   └─ 应用故障注入

5. 观察和验证
   ├─ 系统弹性验证
   ├─ 告警触发验证
   └─ 自我恢复验证

6. 分析和报告
   ├─ 告警验证报告
   └─ 自我恢复验证报告
```

---

## 故障注入全生命周期设计

### Pod 故障注入全流程

**目标：** 验证应用在 Pod 突然终止时的自愈能力，包括自动重启、连接重建和状态恢复。同时验证告警是否正确触发。

**全流程步骤：**

1. **准备阶段（Pre-Chaos）**
   - 记录基准指标：Pod 状态、服务 QPS、错误率、P95/P99 延迟、活跃连接数
   - 获取当前链路样本（用于对比）
   - 记录相关服务的日志级别
   - 定义预期告警列表：
     - `PodNotReady` 或 `PodDown`
     - `ServiceUnavailable`（如服务完全不可用）
   - 记录当前告警状态（作为基线）

2. **执行阶段（Chaos Injection）**
   - 选择目标 Pod（可指定或随机）
   - 应用 PodKill 故障（终止 Pod）
   - Kubernetes 触发重建 Pod
   - 记录故障开始时间（t0）

3. **观察阶段（During Chaos）**
   - 监控 Pod 重建时间（Pending → Running → Ready）
   - 观察 Service endpoints 更新
   - 监控错误率是否超过阈值
   - 观察 Temporal traces 是否出现超时或失败
   - 检查应用日志是否有连接错误、重试日志
   - **验证告警触发**：
     - `PodNotReady` 告警是否在 t0 + X 秒内触发（X 告警延迟阈值）
     - 告警严重级别是否正确（Critical/Warning）
     - 告警标签是否正确（namespace、service、pod）
     - 记录告警触发时间（t_alert）

4. **恢复阶段（Post-Chaos）**
   - 等待 Pod Ready 后持续观察 2-5 分钟
   - 验证 QPS 是否恢复到基准水平
   - 验证错误率是否恢复正常
   - 验证 P95/P99 延迟是否恢复正常
   - 检查是否有"僵尸连接"或泄漏
   - **验证告警恢复**：
     - PodReady 后告警是否自动恢复
     - 恢复时间是否符合预期
     - 是否有告警未恢复（需手动处理）

5. **分析阶段（Post-Analysis）**
   - 对比预期告警和实际触发的告警
   - 计算告警响应时间（t_alert - t0）
   - 识别告警缺失场景（预期触发但未触发）
   - 识别告警误报（未预期但触发了）
   - 生成告警验证报告

**观察指标：**
| 指标类型 | 具体指标 | 工具 |
|---------|---------|------|
| Pod 状态 | pod_phase, pod_ready, restart_count | Prometheus |
| 服务可用性 | up, service_available | Prometheus |
| 请求量 | http_server_requests_total, grpc_server_handled_total | Prometheus |
| 错误率 | error_rate, 5xx_rate | Prometheus |
| 延迟 | P50/P95/P99 latency, traces_spanmetrics_duration_milliseconds | Prometheus/Tempo |
| 连接 | active_connections, connection_errors | Prometheus |
| 链路 | Trace span status, trace duration | Tempo |
| 告警 | ALERTS, alert_response_time, alert_labels | AlertManager |
| 告警日志 | Alert fire, alert resolve | Loki |

**验证点：**
1. Pod 在定义的重启时间（如 60s）内恢复 Ready 状态
2. Service endpoints 在 Pod Ready 后 30s 内更新
3. 错误率 spike 不超过 10%（除非目标服务单副本）
4. 5 分钟内 QPS 恢复到基准的 90% 以上
5. 链路中出现的错误 span 集中在故障期间
6. 日志中能看到连接重建、重试的成功记录
7. **告警验证点**：
   - PodNotReady 告警在故障后 30s 内触发
   - 告警严重级别为 Critical
   - 告警包含正确的 namespace 和 service 标签
   - PodReady 后 30s 内告警自动恢复

**验收标准：**
- [ ] Pod 故障注入后能在预期时间内自动重建并 Ready
- [ ] 服务流量能自动切换到健康的 Pod
- [ ] 错误率 spike 在可接受范围内并快速恢复
- [ ] 无持久化资源泄漏（连接、文件描述符等）
- [ ] 可观测性数据完整记录故障和恢复过程
- [ ] 无人工干预情况下系统完全自动恢复
- [ ] **告警验收标准**：
  - [ ] 预期告警（PodNotReady）在故障后正确触发
  - [ ] 告警响应时间在阈值范围内（≤30s）
  - [ ] 告警恢复时间在阈值范围内（≤60s）
  - [ ] 无预期外的告警误报
  - [ ] 告警标签准确反映故障上下文

---

### 网络延迟注入全流程

**目标：** 验证应用在高网络延迟下的超时处理、重试逻辑和用户体验降级。同时验证高延迟告警是否正确触发。

**全流程步骤：**

1. **准备阶段（Pre-Chaos）**
   - 记录基准 P50/P95/P99 延迟
   - 记录超时配置（client timeout, server timeout）
   - 记录重试策略（重试次数、退避算法）
   - 获取正常链路样本
   - 定义预期告警列表：
     - `HighLatency`（如 P95 > 1s）
     - `High5xxRate`（如超过超时阈值）
   - 记录当前告警状态

2. **执行阶段（Chaos Injection）**
   - 选择目标服务（如 recommendationservice）
   - 应用 NetworkDelay 故障（如 500ms 延迟，jitter 50ms）
   - 可选：同时注入丢包（如 5%）
   - 记录故障开始时间（t0）

3. **观察阶段（During Chaos）**
   - 监控 P50/P95/P99 延迟变化
   - 观察是否触发超时
   - 监控重试次数
   - 观察是否触发熔断（如果有）
   - 检查是否返回降级响应（如缓存数据、默认值）
   - 监控客户端请求队列积压
   - **验证告警触发**：
     - HighLatency 告警是否在延迟超过阈值后触发
     - High5xxRate 告警是否在错误率超过阈值后触发
     - 告警严重级别是否正确
     - 记录告警触发时间

4. **恢复阶段（Post-Chaos）**
   - 移除网络延迟
   - 观察 2-5 分钟，验证延迟恢复正常
   - 验证无"慢启动"问题（连接池预热）
   - 验证队列积压已清空
   - **验证告警恢复**：
     - 延迟恢复正常后告警是否自动恢复
     - 恢复时间是否符合预期

5. **分析阶段（Post-Analysis）**
   - 对比预期告警和实际触发的告警
   - 分析告警触发时间与延迟 spike 的关系
   - 识别告警阈值是否合理（是否过高或过低）
   - 生成告警验证报告

**观察指标：**
| 指标类型 | 具体指标 | 工具 |
|---------|---------|------|
| 延迟 | P50/P95/P99, 99.9th percentile | Prometheus/Tempo |
| 超时 | timeout_count, timeout_rate | Prometheus |
| 重试 | retry_count, retry_backoff | Prometheus/Loki |
| 熔断 | circuit_state, circuit_open_count | Prometheus |
| 降级 | fallback_hit_count, default_response_count | Prometheus |
| 队列 | request_queue_length, pending_requests | Prometheus |
| 客户端 | client_timeout, client_retry | Tempo |
| 告警 | ALERTS, alert_response_time | AlertManager |
| 日志 | Timeout logs, fallback logs, queue warnings | Loki |

**验证点：**
1. P95 延迟 spike 符合注入的延迟量 + 处理时间
2. 超时仅在延迟超过配置阈值时发生
3. 重试次数符合配置策略（不会无限重试）
4. 熔断器在持续错误时正确触发
5. 降级机制在服务不可用时正确返回
6. 移除延迟后无"慢恢复"现象
7. **告警验证点**：
   - HighLatency 告警在 P95 超过阈值后触发
   - High5xxRate 告警在错误率超过阈值后触发
   - 告警响应时间合理（不超过 2 分钟）
   - 延迟恢复正常后告警及时恢复

**验收标准：**
- [ ] 应用正确处理高延迟场景（超时、重试、熔断生效）
- [ ] 降级机制在需要时正确触发
- [ ] 移除延迟后系统快速恢复到基准性能
- [ ] 无级联故障（延迟不会传播到上游服务）
- [ ] 可观测性清晰反映延迟注入的影响
- [ ] 无资源耗尽（连接池、线程池、队列）
- [ ] **告警验收标准**：
  - [ ] 预期告警（HighLatency、High5xxRate）正确触发
  - [ ] 告警阈值合理，及时反映性能降级
  - [ ] 告警标签准确反映受影响服务
  - [ ] 延迟恢复后告警及时恢复

---

### 服务依赖故障注入全流程

**目标：** 验证应用在依赖服务不可用时的优雅降级、熔断和缓存机制。同时验证服务不可用告警是否正确触发。

**全流程步骤：**

1. **准备阶段（Pre-Chaos）**
   - 识别服务依赖图（如 frontend → adservice → recommendationservice）
   - 记录依赖服务的调用频率
   - 检查是否有缓存（本地缓存、Redis、Memcached）
   - 检查降级配置（默认值、缓存过期策略）
   - 记录熔断器配置
   - 定义预期告警列表：
     - `ServiceUnavailable`（依赖服务不可用）
     - `DependencyErrorRateHigh`（上游调用失败率高）
     - `CircuitBreakerOpen`（熔断器打开）
   - 记录当前告警状态

2. **执行阶段（Chaos Injection）**
   - 选择依赖服务（如 adservice）
   - 应用 PodNetworkFault（网络隔离）或 HTTPFault（HTTP 500）
   - 或直接删除 Pod 模拟服务下线
   - 记录故障开始时间（t0）

3. **观察阶段（During Chaos）**
   - 监控上游服务的错误率（如 frontend 调用 adservice）
   - 观察熔断器状态变化
   - 监控降级响应命中数
   - 检查缓存命中/未命中比
   - 观察用户体验是否有明显影响（如广告位为空但页面可访问）
   - 监控是否有重试风暴
   - **验证告警触发**：
     - ServiceUnavailable 告警是否触发
     - DependencyErrorRateHigh 告警是否触发
     - CircuitBreakerOpen 告警是否触发
     - 记录告警触发时间和严重级别

4. **恢复阶段（Post-Chaos）**
   - 恢复依赖服务
   - 观察熔断器恢复时间（半开 → 关闭）
   - 验证流量逐步恢复
   - 检查是否有"惊群效应"（所有请求同时涌入恢复的服务）
   - **验证告警恢复**：
     - 服务恢复后告警是否及时恢复
     - 熔断器关闭后 CircuitBreakerOpen 告警是否恢复

5. **分析阶段（Post-Analysis）**
   - 对比预期告警和实际触发的告警
   - 分析告警是否正确反映依赖故障的影响范围
   - 识别是否缺少关键告警（如降级触发告警）
   - 生成告警验证报告

**观察指标：**
| 指标类型 | 具体指标 | 工具 |
|---------|---------|------|
| 上游错误 | upstream_error_rate, 5xx_upstream | Prometheus |
| 熔断 | circuit_state, circuit_transition_count | Prometheus |
| 降级 | fallback_hit_rate, cache_hit_rate | Prometheus |
| 用户体验 | user_visible_error_count, page_load_time | Prometheus/Tempo |
| 重试风暴 | retry_rate_spike, connection_timeout | Prometheus |
| 缓存 | cache_hit_ratio, cache_miss_count | Prometheus |
| 链路 | Dependency failure span, fallback span | Tempo |
| 告警 | ALERTS, alert_response_time | AlertManager |
| 日志 | Fallback logs, cache logs, circuit logs | Loki |

**验证点：**
1. 依赖故障后上游服务错误率 spike 但在可控制范围
2. 熔断器在持续错误后快速打开，避免重试风暴
3. 降级响应正确返回（如空广告、默认推荐）
4. 缓存命中率在故障期间提升（如果有）
5. 用户体验未完全中断（关键功能可用）
6. 恢复后流量逐步恢复，无惊群效应
7. **告警验证点**：
   - ServiceUnavailable 告警在依赖故障后及时触发
   - DependencyErrorRateHigh 告警准确反映上游错误率
   - CircuitBreakerOpen 告警在熔断器打开时触发
   - 告警标签准确标识受影响的依赖服务

**验收标准：**
- [ ] 依赖故障不导致级联故障
- [ ] 熔断器正确打开和恢复
- [ ] 降级机制有效，用户体验保持可用
- [ ] 无重试风暴或资源耗尽
- [ ] 恢复后服务平滑过渡，无性能 spike
- [ ] 可观测性清晰反映故障传播和恢复
- [ ] **告警验收标准**：
  - [ ] 预期告警（ServiceUnavailable、DependencyErrorRateHigh、CircuitBreakerOpen）正确触发
  - [ ] 告警准确反映依赖故障的影响
  - [ ] 服务恢复后告警及时恢复
  - [ ] 无预期外的告警误报

---

### 资源耗尽注入全流程

**目标：** 验证应用在 CPU 或内存资源紧张时的表现，包括节流、OOM 保护和 graceful degradation。同时验证资源告警是否正确触发。

**全流程步骤：**

1. **准备阶段（Pre-Chaos）**
   - 记录当前资源使用（CPU %, Memory %）
   - 检查资源限制配置（limits, requests）
   - 记录 QPS 和响应时间基准
   - 检查是否有优雅降级逻辑（如降低缓存、减少计算）
   - 定义预期告警列表：
     - `HighCPUUsage`（CPU 使用率 > 80%）
     - `HighMemoryUsage`（内存使用率 > 80%）
     - `PodOOMKilled`（内存耗尽被 OOM Kill）
     - `CPUThrottlingHigh`（CPU 节流严重）
   - 记录当前告警状态

2. **执行阶段（Chaos Injection）**
   - 选择目标 Pod
   - 应用 CPUStress（如 90% CPU）或 MemoryStress（如 80% 内存）
   - 可选：同时压测流量以放大效果
   - 记录故障开始时间（t0）

3. **观察阶段（During Chaos）**
   - 监控 CPU/Memory 使用率是否达到 limits
   - 观察是否触发 CPU 节流（CPU throttling）
   - 检查是否触发 OOM（内存耗尽）
   - 监控 QPS 下降幅度
   - 观察 P95/P99 延迟 spike
   - 检查是否有 graceful degradation（如减少计算量）
   - 监控 Kubernetes 的 QoS 调度
   - **验证告警触发**：
     - HighCPUUsage 告警是否触发
     - HighMemoryUsage 告警是否触发
     - PodOOMKilled 告警是否触发（如 OOM）
     - CPUThrottlingHigh 告警是否触发
     - 记录告警触发时间和严重级别

4. **恢复阶段（Post-Chaos）**
   - 移除压力
   - 观察 Pod 是否需要重启（如 OOM 后）
   - 验证资源使用恢复正常
   - 验证性能逐步恢复
   - **验证告警恢复**：
     - 资源使用恢复正常后告警是否恢复
     - Pod 重建后告警是否正确更新

5. **分析阶段（Post-Analysis）**
   - 对比预期告警和实际触发的告警
   - 分析告警阈值是否合理（是否过低导致频繁告警）
   - 识别是否缺少关键告警（如 QPS 下降告警）
   - 生成告警验证报告

**观察指标：**
| 指标类型 | 具体指标 | 工具 |
|---------|---------|------|
| 资源使用 | container_cpu_usage_seconds_total, container_memory_working_set_bytes | Prometheus |
| CPU 节流 | container_cpu_cfs_throttled_periods_total, container_cpu_cfs_periods_total | Prometheus |
| OOM | oom_killed, memory_usage_exceeds_limit | Prometheus/K8s |
| 性能 | QPS, P50/P95/P99 latency | Prometheus/Tempo |
| 降级 | degraded_mode_active, reduced_computation | Prometheus/Loki |
| QoS | pod_qos_class, kubernetes_pod_status | Prometheus |
| 告警 | ALERTS, alert_response_time | AlertManager |
| 日志 | Throttling logs, OOM logs, degradation logs | Loki |

**验证点：**
1. 资源使用达到限制时触发节流或 OOM
2. 应用有足够的 CPU limits，避免影响其他 Pod
3. Memory limits 配置合理，避免频繁 OOM
4. QPS 下降在预期范围内
5. 延迟 spike 在可接受范围
6. 如果有 graceful degradation，正确触发
7. **告警验证点**：
   - HighCPUUsage 告警在 CPU 使用率超过阈值后触发
   - HighMemoryUsage 告警在内存使用率超过阈值后触发
   - PodOOMKilled 告警在 OOM 时立即触发
   - 告警标签准确标识受影响的 Pod 和节点

**验收标准：**
- [ ] 资源限制正确配置并生效
- [ ] 资源紧张时应用表现符合预期（节流或 OOM）
- [ ] 不影响其他 Pod（通过 QoS 隔离）
- [ ] 资源移除后应用正常恢复
- [ ] 可观测性清晰反映资源状态
- [ ] 无系统性资源饥饿（Kubernetes node 正常）
- [ ] **告警验收标准**：
  - [ ] 预期告警（HighCPUUsage、HighMemoryUsage、PodOOMKilled）正确触发
  - [ ] 告警阈值合理，不过早也不过晚
  - [ ] 资源恢复后告警及时恢复
  - [ ] 无预期外的告警误报

---

### 级联故障注入全流程

**目标：** 验证系统在多个故障同时发生时的弹性，包括隔离机制、断路器和熔断链。同时验证告警是否正确反映级联故障的范围和影响。

**全流程步骤：**

1. **准备阶段（Pre-Chaos）**
   - 绘制完整的服务依赖图
   - 识别关键路径和单点故障
   - 记录各服务的熔断器配置
   - 检查是否有隔离机制（如资源隔离、连接池隔离）
   - 定义预期告警列表：
     - `CascadeFailureDetected`（检测到级联故障）
     - `ServiceUnavailable`（多个服务不可用）
     - `SystemDegraded`（系统整体降级）
     - `CircuitBreakerCascade`（多个熔断器打开）
   - 记录当前告警状态

2. **执行阶段（Chaos Injection）**
   - 选择多个故障点（如：adservice PodKill + recommendationservice NetworkDelay + checkoutservice CPUStress）
   - 同时或按顺序注入故障
   - 可选：增加流量压力以放大效果
   - 记录故障开始时间（t0）

3. **观察阶段（During Chaos）**
   - 监控错误率 spike（各服务）
   - 观察熔断器链（哪些打开，哪些保持关闭）
   - 检查是否有级联故障（如 frontend → adservice → 上游）
   - 监控整体系统可用性（关键功能是否可用）
   - 观察资源使用（是否有资源饥饿）
   - 检查是否有"雪崩"效应（请求积压导致更多失败）
   - **验证告警触发**：
     - CascadeFailureDetected 告警是否触发
     - ServiceUnavailable 告警是否准确反映受影响服务
     - SystemDegraded 告警是否反映整体系统状态
     - 告警是否准确标识故障传播路径
     - 记录告警触发时间和严重级别

4. **恢复阶段（Post-Chaos）**
   - 按相反顺序移除故障
   - 观察熔断器恢复链
   - 验证系统逐层恢复
   - 检查恢复后是否有性能问题
   - **验证告警恢复**：
     - 故障移除后告警是否及时恢复
     - 系统恢复后 SystemDegraded 告警是否恢复
     - 熔断器恢复后相关告警是否更新

5. **分析阶段（Post-Analysis）**
   - 对比预期告警和实际触发的告警
   - 分析告警是否准确反映级联故障的范围
   - 识别是否缺少关键告警（如级联故障检测告警）
   - 评估告警严重级别是否合理
   - 生成告警验证报告

**观察指标：**
| 指标类型 | 具体指标 | 工具 |
|---------|---------|------|
| 系统可用性 | system_available, critical_function_available | Prometheus |
| 错误传播 | error_rate_by_service, cascading_failures | Prometheus |
| 熔断链 | circuit_state_by_service, cascade_depth | Prometheus |
| 资源隔离 | resource_usage_by_pod, node_resource_usage | Prometheus |
| 请求积压 | request_queue_length, pending_requests | Prometheus |
| 链路 | Cascade failure trace span, timeout chain | Tempo |
| 告警 | ALERTS, alert_response_time, alert_severity | AlertManager |
| 日志 | Cascade logs, circuit logs, isolation logs | Loki |

**验证点：**
1. 级联故障被隔离在故障服务，不传播到其他服务
2. 熔断器链正确工作，防止雪崩
3. 系统核心功能保持可用（如浏览商品可用，但下单可能受影响）
4. 资源隔离生效，故障不影响其他服务的资源
5. 恢复时系统逐层恢复，无二次故障
6. **告警验证点**：
   - CascadeFailureDetected 告警在检测到级联故障时触发
   - ServiceUnavailable 告警准确反映受影响的服务
   - SystemDegraded 告警反映整体系统降级程度
   - 告警标签准确标识故障传播路径和影响范围
   - 告警严重级别符合故障严重程度

**验收标准：**
- [ ] 级联故障被有效隔离
- [ ] 系统关键功能保持可用
- [ ] 熔断器链正确工作
- [ ] 资源隔离生效
- [ ] 恢复时系统平滑过渡
- [ ] 可观测性完整记录级联故障和恢复
- [ ] **告警验收标准**：
  - [ ] 预期告警（CascadeFailureDetected、ServiceUnavailable、SystemDegraded）正确触发
  - [ ] 告警准确反映级联故障的范围和影响
  - [ ] 告警严重级别符合故障严重程度
  - [ ] 故障恢复后告警及时恢复
  - [ ] 无预期外的告警误报

---

## 告警验证报告设计

### 报告结构

每个混沌实验后生成告警验证报告，包含以下部分：

```markdown
# 告警验证报告 - [实验名称]

## 实验信息
- 实验类型: [Pod故障 / 网络延迟 / 依赖故障 / 资源耗尽 / 级联故障]
- 目标服务: [service-name]
- 开始时间: [timestamp]
- 结束时间: [timestamp]
- 持续时长: [duration]

## 预期告警
| 告警名称 | 严重级别 | 预期触发条件 |
|---------|---------|-------------|
| PodNotReady | Critical | Pod 进入 NotReady 状态 |
| HighLatency | Warning | P95 延迟 > 1s |

## 实际触发的告警
| 告警名称 | 触发时间 | 恢复时间 | 持续时长 | 响应时间 |
|---------|---------|---------|---------|---------|
| PodNotReady | 2024-01-01 10:00:05 | 2024-01-01 10:01:00 | 55s | 5s |

## 告警验证结果
### 成功触发的告警 ✅
- PodNotReady: 5s 内触发，符合预期（≤30s）

### 未触发的告警 ❌
- 无

### 未预期触发的告警 ⚠️
- HighErrorRate: 错误率 spike 但未在预期列表中

## 告警响应时间分析
| 告警名称 | 预期响应时间 | 实际响应时间 | 评价 |
|---------|-------------|-------------|------|
| PodNotReady | ≤30s | 5s | ✅ 优秀 |

## 改进建议
1. 建议添加 HighErrorRate 告警到 Pod 故障实验的预期列表
2. 无其他改进建议

## 总结
- 告警覆盖率: 100% (1/1)
- 告警响应及时性: 优秀
- 整体评价: 通过 ✅
```

### 告警验证自动化

为了提高效率，可以自动化告警验证流程：

1. **实验定义阶段**：在实验 YAML 中添加 `expectedAlerts` 字段
2. **实验执行阶段**：Chaos Mesh 或外部脚本自动记录告警触发情况
3. **实验分析阶段**：对比预期和实际，自动生成报告

---

## 自我恢复能力验证设计

### Kubernetes 自我恢复机制

Kubernetes 提供了多层次的自我恢复能力：

| 机制 | 触发条件 | 恢复行为 | 验证指标 |
|------|---------|---------|---------|
| Pod 自动重启 | Pod 崩溃或被终止 | Deployment/StatefulSet 自动重建 Pod | restart_count, pod_age |
| 健康检查 | liveness probe 失败 | 重启 Pod | liveness_probe_failures |
| 就绪检查 | readiness probe 失败 | 从 Service endpoints 移除 Pod | ready_replicas, available_replicas |
| 资源限制 | OOM 或 CPU 节流 | OOM Kill 或性能降级 | oom_killed, cpu_throttling |
| 节点故障 | Node NotReady | Pod 调度到其他节点 | node_ready, pod_node |

### 自我恢复能力验证流程

每个混沌实验应包含自我恢复能力验证：

1. **故障注入前（Pre-Chaos）**
   - 记录当前 Pod 状态、restart_count、资源使用
   - 记录 Service endpoints
   - 记录活跃连接数

2. **故障注入中（During Chaos）**
   - 监控 Pod 状态变化
   - 监控 Service endpoints 更新
   - 监控资源使用变化

3. **故障移除后（Post-Chaos）**
   - 验证 Pod 自动恢复 Ready
   - 验证 Service endpoints 更新
   - 验证连接自动重建
   - 检测资源泄漏

4. **分析阶段（Analysis）**
   - 计算恢复时间（故障发生到完全恢复）
   - 检查是否有资源泄漏
   - 评估恢复成功率

### 自我恢复能力验证指标

| 指标类型 | 具体指标 | 验收标准 | 工具 |
|---------|---------|---------|------|
| Pod 恢复时间 | Pod 终止到 Ready 的时间 | ≤ 60s | Prometheus/K8s |
| Service 更新时间 | Pod Ready 到 endpoints 更新 | ≤ 30s | Prometheus/K8s |
| 连接重建时间 | 连接中断到重建成功 | ≤ 30s | Prometheus/Tempo |
| 资源泄漏 | 连接泄漏、内存泄漏 | 0 | Prometheus |
| 重启成功率 | 重启后恢复 Ready 的比例 | 100% | Prometheus |
| 资源使用恢复 | CPU/Memory 使用率恢复正常时间 | ≤ 5min | Prometheus |

### 自我恢复能力验证报告

每个混沌实验后生成自我恢复能力验证报告：

```markdown
# 自我恢复能力验证报告 - [实验名称]

## 实验信息
- 实验类型: [Pod故障 / 网络延迟 / 依赖故障 / 资源耗尽 / 级联故障]
- 目标服务: [service-name]
- 故障开始时间: [timestamp]
- 故障结束时间: [timestamp]

## 自我恢复验证结果

### Pod 自动重启 ✅
- 故障类型: PodKill
- Pod 重建时间: 45s (预期 ≤ 60s)
- 评价: 通过 ✅

### 健康检查 ✅
- liveness probe: 正常触发重启
- readiness probe: 正确标记 NotReady → Ready
- 评价: 通过 ✅

### Service 发现更新 ✅
- endpoints 更新时间: 20s (预期 ≤ 30s)
- 流量切换: 自动切换到健康 Pod
- 评价: 通过 ✅

### 连接重建 ✅
- 连接泄漏: 0 (预期 0)
- 连接重建时间: 15s (预期 ≤ 30s)
- 评价: 通过 ✅

### 资源使用恢复 ✅
- CPU 使用率恢复正常时间: 2min (预期 ≤ 5min)
- Memory 使用率恢复正常时间: 1min (预期 ≤ 5min)
- 评价: 通过 ✅

## 恢复时间分析
| 指标 | 实际值 | 预期值 | 评价 |
|------|--------|--------|------|
| Pod 恢复时间 | 45s | ≤ 60s | ✅ 优秀 |
| Service 更新时间 | 20s | ≤ 30s | ✅ 优秀 |
| 连接重建时间 | 15s | ≤ 30s | ✅ 优秀 |
| 完全恢复时间 | 3min | ≤ 5min | ✅ 优秀 |

## 资源泄漏检测
- 连接泄漏: 0 ✅
- 文件描述符泄漏: 0 ✅
- 内存泄漏: 0 ✅
- 评价: 无资源泄漏 ✅

## 问题识别
- 无

## 改进建议
- 无

## 总结
- 自我恢复能力: 优秀
- 恢复时间: 符合预期
- 资源泄漏: 无
- 整体评价: 通过 ✅
```

### 常见自我恢复问题

| 问题 | 表现 | 根本原因 | 解决方案 |
|------|------|---------|---------|
| Pod 无法恢复 | Pod 持续 CrashLoopBackOff | 应用启动失败、资源不足 | 检查应用日志、调整资源配置 |
| 健康检查失败 | liveness/readiness probe 持续失败 | probe 配置不合理、应用不响应 | 调整 probe 超时和间隔 |
| 连接泄漏 | 连接数持续增长 | 连接未正确关闭 | 检查应用代码，添加连接池 |
| 慢恢复 | 恢复时间过长 | 应用冷启动、依赖服务慢 | 优化应用启动、添加预热 |
| 资源未释放 | CPU/Memory 持续高 | 资源未正确释放 | 检查应用代码，添加资源清理 |

### 自我恢复能力验收标准

每个混沌实验都应通过以下自我恢复验收标准：

- [ ] Pod 在预期时间内自动恢复 Ready
- [ ] Service endpoints 在预期时间内更新
- [ ] 连接自动重建，无连接泄漏
- [ ] 资源使用在预期时间内恢复正常
- [ ] 无资源泄漏（连接、文件描述符、内存）
- [ ] 无需人工干预完全恢复

---

## 风险 / 权衡

### 风险 1：混沌实验导致生产事故

**缓解措施：**
- 严格的命名空间限制（仅 online-boutique）
- 准入 Webhook 验证
- 运维人员培训和文档
- 分阶段推出（开发 → 测试 → 生产）

### 风险 2：Chaos Mesh 控制器成为单点故障

**缓解措施：**
- 部署多个副本的 Chaos Mesh 控制器
- 对控制器管理器使用领导选举
- 实验通过 Kubernetes 垃圾回收自愈

### 风险 3：增加运营复杂性

**缓解措施：**
- 清晰的文档和运行手册
- 标准化的实验模板
- 通过现有部署脚本简化部署
- 与现有可观测性栈集成

### 风险 4：混沌实验期间告警风暴

**缓解措施：**
- 合理设置告警阈值，避免过敏感
- 告警分组和聚合，避免重复告警
- 使用告警严重级别区分关键和非关键告警
- 告警路由优化，将混沌实验告警发送到专门的通知渠道

### 权衡 1：功能丰富度 vs 简单性

**决策：** 优先考虑功能丰富度

Chaos Mesh 提供许多故障注入类型。我们将启用大部分功能，但保持默认配置保守。

### 权衡 2：自动化 vs 手动控制

**决策：** 手动控制配合自动化钩子

最初要求手动实验审批。未来增强可以添加基于计划或触发器的自动化实验。

### 权衡 3：告警抑制 vs 告警验证

**决策：** 不抑制告警，主动验证告警

虽然混沌实验期间会产生大量告警，但这些告警是验证告警系统有效性的重要数据。不抑制告警可以：
- 验证告警是否在正确时间触发
- 识别告警缺失的场景
- 评估告警响应时间
- 发现告警误报

告警风暴的风险通过告警分组、聚合和路由优化来缓解。

---

## Claude Code Skills 设计

### Skills 架构

通过 Claude Code skills 实现系统性的混沌工程流程，所有操作通过简单的命令完成：

```
.claude/skills/
├── chaos-check-alerts.md        # 告警覆盖度检查
├── chaos-inject-pod.md          # Pod 故障注入
├── chaos-inject-network.md      # 网络延迟注入
├── chaos-inject-dependency.md   # 依赖故障注入
├── chaos-inject-resource.md     # 资源耗尽注入
├── chaos-inject-cascade.md      # 级联故障注入
├── chaos-monitor.md             # 混沌实验监控
├── chaos-validate-alerts.md     # 告警验证
├── chaos-validate-self-heal.md  # 自我恢复验证
├── chaos-report.md              # 生成实验报告
└── chaos-abort.md               # 中止混沌实验
```

### Skills 功能设计

#### 1. `/chaos-check-alerts` - 告警覆盖度检查

**功能**：检查当前告警规则的覆盖度，识别缺失的告警规则

**用法**：
```
/chaos-check-alerts [namespace]
```

**参数**：
- `namespace`: 可选，指定要检查的命名空间（默认：online-boutique）

**执行流程**：
1. 扫描 Prometheus 中的告警规则
2. 对比关键告警场景清单
3. 计算告警覆盖率
4. 生成覆盖度报告
5. 评估是否允许执行混沌实验

**输出示例**：
```
告警覆盖度检查报告
====================
检查时间: 2024-01-01 10:00:00

覆盖度统计:
- 关键场景总数: 15
- 已覆盖场景数: 13
- 缺失场景数: 2
- 告警覆盖率: 86.7% ✅

已覆盖的告警:
✅ PodDown
✅ PodNotReady
✅ ServiceDown
✅ HighLatency
✅ HighErrorRate
✅ High5xxRate
✅ HighCPUUsage
✅ HighMemoryUsage
...

缺失的告警:
❌ PodOOMKilled (关键)
❌ CircuitBreakerOpen (重要)

评估结果:
- 覆盖率: 86.7% ✅
- 关键缺失: 1 个 ⚠️
- 建议: 补充 PodOOMKilled 告警规则后再执行关键资源实验

阻塞状态: ⚠️ 允许执行非资源实验，资源实验需要补充告警
```

**验收标准**：
- [ ] 能正确扫描当前告警规则
- [ ] 能准确对比关键场景清单
- [ ] 能计算正确的覆盖率
- [ ] 能生成可读的检查报告
- [ ] 能正确判断是否允许执行实验

---

#### 2. `/chaos-inject-pod` - Pod 故障注入

**功能**：触发 Pod 故障注入实验，终止指定服务或随机 Pod

**用法**：
```
/chaos-inject-pod [service] [duration]
```

**参数**：
- `service`: 可选，目标服务名称（如 `frontend`、`adservice`），不指定则随机选择
- `duration`: 可选，实验时长（默认：2m），格式：数字+s/m/h

**执行流程**：
1. 运行告警覆盖度检查
2. 选择目标 Pod（指定服务或随机）
3. 记录基准指标
4. 应用 PodKill 故障
5. 记录实验开始时间
6. 显示实验状态和观察指标

**输出示例**：
```
Pod 故障注入实验
================
实验 ID: pod-failure-20240101-100000
目标服务: frontend (随机选择)
目标 Pod: frontend-7d9f5c6f8d-x2k4p
实验时长: 2m
预期告警: PodNotReady, ServiceUnavailable

前置检查:
✅ 告警覆盖度: 87% (允许执行)

执行步骤:
1. 记录基准指标... ✅
2. 应用 PodKill 故障... ✅
3. Pod 正在重建...

观察指标:
- Pod 状态: Pending → Running → Ready
- Service endpoints: 更新中
- 错误率: 监控中
- 告警触发: 等待中...

下一步:
- 使用 /chaos-monitor 监控实验状态
- 使用 /chaos-validate-alerts 验证告警触发
- 使用 /chaos-validate-self-heal 验证自我恢复
- 使用 /chaos-report 生成实验报告
- 使用 /chaos-abort 中止实验
```

**验收标准**：
- [ ] 能正确执行告警覆盖度检查
- [ ] 能正确选择目标 Pod
- [ ] 能成功应用 PodKill 故障
- [ ] 能记录基准指标
- [ ] 能显示实验状态和观察指标
- [ ] 能提供下一步操作指引

---

#### 3. `/chaos-inject-network` - 网络延迟注入

**功能**：触发网络延迟注入实验，向指定服务注入网络延迟

**用法**：
```
/chaos-inject-network [service] [latency] [duration]
```

**参数**：
- `service`: 目标服务名称（如 `recommendationservice`）
- `latency`: 可选，延迟量（默认：500ms），格式：数字+ms/s
- `duration`: 可选，实验时长（默认：3m），格式：数字+s/m/h

**执行流程**：
1. 运行告警覆盖度检查
2. 检查目标服务是否存在
3. 记录基准指标（P95 延迟、错误率）
4. 应用 NetworkDelay 故障
5. 记录实验开始时间
6. 显示实验状态和观察指标

**输出示例**：
```
网络延迟注入实验
================
实验 ID: network-latency-20240101-100000
目标服务: recommendationservice
延迟量: 500ms
实验时长: 3m
预期告警: HighLatency, High5xxRate

前置检查:
✅ 告警覆盖度: 87% (允许执行)

执行步骤:
1. 记录基准指标... ✅
   - P95 延迟: 120ms
   - 错误率: 0.1%
2. 应用 NetworkDelay 故障... ✅
3. 延迟已注入，流量正在经过...

观察指标:
- P95 延迟: 监控中 (预期: ~620ms)
- 错误率: 监控中
- 告警触发: 等待中...

下一步:
- 使用 /chaos-monitor 监控实验状态
- 使用 /chaos-validate-alerts 验证告警触发
- 使用 /chaos-report 生成实验报告
- 使用 /chaos-abort 中止实验
```

**验收标准**：
- [ ] 能正确执行告警覆盖度检查
- [ ] 能成功应用网络延迟故障
- [ ] 能记录基准指标
- [ ] 能显示实验状态和观察指标
- [ ] 能提供下一步操作指引

---

#### 4. `/chaos-inject-dependency` - 依赖故障注入

**功能**：触发服务依赖故障注入实验，模拟依赖服务不可用

**用法**：
```
/chaos-inject-dependency [service] [dependency] [duration]
```

**参数**：
- `service`: 上游服务名称（如 `frontend`）
- `dependency`: 依赖服务名称（如 `adservice`）
- `duration`: 可选，实验时长（默认：3m），格式：数字+s/m/h

**执行流程**：
1. 运行告警覆盖度检查
2. 检查服务和依赖是否存在
3. 记录基准指标（上游错误率、熔断器状态）
4. 应用网络隔离或 HTTP 故障
5. 记录实验开始时间
6. 显示实验状态和观察指标

**输出示例**：
```
依赖故障注入实验
================
实验 ID: dependency-failure-20240101-100000
上游服务: frontend
依赖服务: adservice
故障类型: 网络隔离
实验时长: 3m
预期告警: ServiceUnavailable, DependencyErrorRateHigh, CircuitBreakerOpen

前置检查:
✅ 告警覆盖度: 87% (允许执行)

执行步骤:
1. 记录基准指标... ✅
   - 上游错误率: 0.1%
   - 熔断器状态: Closed
2. 应用网络隔离... ✅
3. adservice 已被隔离...

观察指标:
- 上游错误率: 监控中
- 熔断器状态: 监控中
- 降级命中: 监控中
- 告警触发: 等待中...

下一步:
- 使用 /chaos-monitor 监控实验状态
- 使用 /chaos-validate-alerts 验证告警触发
- 使用 /chaos-validate-self-heal 验证自我恢复
- 使用 /chaos-report 生成实验报告
- 使用 /chaos-abort 中止实验
```

**验收标准**：
- [ ] 能正确执行告警覆盖度检查
- [ ] 能成功应用依赖故障
- [ ] 能记录基准指标
- [ ] 能显示实验状态和观察指标
- [ ] 能提供下一步操作指引

---

#### 5. `/chaos-inject-resource` - 资源耗尽注入

**功能**：触发资源耗尽注入实验，对目标 Pod 应用 CPU 或内存压力

**用法**：
```
/chaos-inject-resource [service] [type] [value] [duration]
```

**参数**：
- `service`: 目标服务名称（如 `checkoutservice`）
- `type`: 资源类型（cpu 或 memory）
- `value`: 压力值（如 90 表示 90%）
- `duration`: 可选，实验时长（默认：5m），格式：数字+s/m/h

**执行流程**：
1. 运行告警覆盖度检查
2. 检查目标服务是否存在
3. 检查告警规则是否包含资源告警（如 PodOOMKilled）
4. 记录基准指标（CPU/Memory 使用率、QPS）
5. 应用 StressChaos 故障
6. 记录实验开始时间
7. 显示实验状态和观察指标

**输出示例**：
```
资源耗尽注入实验
================
实验 ID: resource-exhaustion-20240101-100000
目标服务: checkoutservice
资源类型: memory
压力值: 80%
实验时长: 5m
预期告警: HighMemoryUsage, PodOOMKilled

前置检查:
✅ 告警覆盖度: 87% (允许执行)
⚠️ PodOOMKilled 告警缺失，建议补充后重试

执行步骤:
1. 记录基准指标... ✅
   - CPU 使用率: 45%
   - Memory 使用率: 60%
   - QPS: 150
2. 应用 MemoryStress 故障... ✅
3. 内存压力已应用...

观察指标:
- CPU/Memory 使用率: 监控中
- QPS: 监控中
- OOM 事件: 监控中
- 告警触发: 等待中...

下一步:
- 使用 /chaos-monitor 监控实验状态
- 使用 /chaos-validate-alerts 验证告警触发
- 使用 /chaos-validate-self-heal 验证自我恢复
- 使用 /chaos-report 生成实验报告
- 使用 /chaos-abort 中止实验
```

**验收标准**：
- [ ] 能正确执行告警覆盖度检查
- [ ] 能检查资源告警是否存在
- [ ] 能成功应用资源压力故障
- [ ] 能记录基准指标
- [ ] 能显示实验状态和观察指标
- [ ] 能提供下一步操作指引

---

#### 6. `/chaos-inject-cascade` - 级联故障注入

**功能**：触发级联故障注入实验，同时注入多个故障

**用法**：
```
/chaos-inject-cascade [config]
```

**参数**：
- `config`: 级联故障配置名称（如 `default`, `heavy`），或直接指定 JSON 配置

**执行流程**：
1. 运行告警覆盖度检查
2. 加载级联故障配置
3. 记录基准指标
4. 按配置注入多个故障
5. 记录实验开始时间
6. 显示实验状态和观察指标

**输出示例**：
```
级联故障注入实验
================
实验 ID: cascade-failure-20240101-100000
配置: default
故障组合:
1. adservice: PodKill (2m)
2. recommendationservice: NetworkDelay 500ms (3m)
3. checkoutservice: MemoryStress 80% (4m)
预期告警: ServiceUnavailable, CascadeFailureDetected, SystemDegraded

前置检查:
✅ 告警覆盖度: 87% (允许执行)

执行步骤:
1. 记录基准指标... ✅
2. 注入故障 1/3: adservice PodKill... ✅
3. 注入故障 2/3: recommendationservice NetworkDelay... ✅
4. 注入故障 3/3: checkoutservice MemoryStress... ✅
5. 所有故障已注入...

观察指标:
- 错误率: 监控中
- 熔断器状态: 监控中
- 系统可用性: 监控中
- 告警触发: 等待中...

下一步:
- 使用 /chaos-monitor 监控实验状态
- 使用 /chaos-validate-alerts 验证告警触发
- 使用 /chaos-validate-self-heal 验证自我恢复
- 使用 /chaos-report 生成实验报告
- 使用 /chaos-abort 中止实验
```

**验收标准**：
- [ ] 能正确执行告警覆盖度检查
- [ ] 能加载级联故障配置
- [ ] 能成功注入多个故障
- [ ] 能记录基准指标
- [ ] 能显示实验状态和观察指标
- [ ] 能提供下一步操作指引

---

#### 7. `/chaos-monitor` - 混沌实验监控

**功能**：监控正在运行的混沌实验，显示实时状态和关键指标

**用法**：
```
/chaos-monitor [experiment-id]
```

**参数**：
- `experiment-id`: 可选，指定实验 ID（默认：显示所有运行中的实验）

**执行流程**：
1. 查询正在运行的混沌实验
2. 获取关键指标（Pod 状态、错误率、延迟、告警状态）
3. 显示实验状态和观察指标
4. 提供跳转到 Grafana 大盘的链接

**输出示例**：
```
混沌实验监控
============
运行中的实验: 1

实验 1: pod-failure-20240101-100000
-------------------------------------
状态: Running (已运行 45s / 2m)
目标服务: frontend
故障类型: PodKill

实时指标:
Pod 状态: Running (15s 前) → Ready (5s 前)
Service endpoints: 3/3 (已更新)
错误率: 3.2% (基准: 0.1%) ⚠️
P95 延迟: 180ms (基准: 80ms)
QPS: 142 (基准: 150)

告警状态:
✅ PodNotReady: 已触发 (30s 前触发，25s 前恢复)
⏳ ServiceUnavailable: 等待中

Grafana 大盘:
http://localhost:3000/d/chaos-experiment?var-experiment=pod-failure-20240101-100000

下一步:
- 使用 /chaos-validate-alerts 验证告警触发
- 使用 /chaos-validate-self-heal 验证自我恢复
- 使用 /chaos-abort 中止实验
```

**验收标准**：
- [ ] 能正确查询运行中的实验
- [ ] 能获取实时关键指标
- [ ] 能显示告警状态
- [ ] 能提供 Grafana 大盘链接
- [ ] 能提供下一步操作指引

---

#### 8. `/chaos-validate-alerts` - 告警验证

**功能**：验证混沌实验期间告警是否正确触发，生成告警验证报告

**用法**：
```
/chaos-validate-alerts [experiment-id]
```

**参数**：
- `experiment-id`: 可选，指定实验 ID（默认：验证最近完成的实验）

**执行流程**：
1. 获取实验信息（类型、目标服务、预期告警）
2. 查询实验期间触发的告警
3. 对比预期告警和实际告警
4. 计算告警响应时间
5. 生成告警验证报告

**输出示例**：
```
告警验证报告
============
实验 ID: pod-failure-20240101-100000
实验类型: Pod 故障
目标服务: frontend

预期告警:
- PodNotReady (Critical)
- ServiceUnavailable (Warning)

实际触发的告警:
1. PodNotReady
   - 触发时间: 10:00:05 (故障后 5s)
   - 恢复时间: 10:01:00
   - 持续时长: 55s
   - 响应时间: 5s ✅ (≤30s)
   - 严重级别: Critical ✅
   - 标签: namespace=online-boutique, service=frontend ✅

验证结果:
✅ PodNotReady: 5s 内触发，符合预期
❌ ServiceUnavailable: 未触发 (预期但未触发)

告警响应时间分析:
| 告警名称 | 预期响应时间 | 实际响应时间 | 评价 |
|---------|-------------|-------------|------|
| PodNotReady | ≤30s | 5s | ✅ 优秀 |

覆盖率: 50% (1/2) ⚠️

问题识别:
❌ ServiceUnavailable 告警未触发，可能是:
   - 告警规则缺失
   - 告警阈值不合理
   - 服务未完全不可用

改进建议:
1. 检查 ServiceUnavailable 告警规则是否存在
2. 考虑调整告警阈值（如可用副本数 < 2 时触发）
3. 或从预期告警列表中移除（如果服务有多副本）

整体评价: 部分 ⚠️
```

**验收标准**：
- [ ] 能正确获取实验信息
- [ ] 能查询实验期间的告警
- [ ] 能准确对比预期和实际告警
- [ ] 能计算告警响应时间
- [ ] 能生成可读的验证报告
- [ ] 能提供改进建议

---

#### 9. `/chaos-validate-self-heal` - 自我恢复验证

**功能**：验证混沌实验后系统的自我恢复能力，生成自我恢复验证报告

**用法**：
```
/chaos-validate-self-heal [experiment-id]
```

**参数**：
- `experiment-id`: 可选，指定实验 ID（默认：验证最近完成的实验）

**执行流程**：
1. 获取实验信息（类型、目标服务、故障移除时间）
2. 查询恢复后的指标（Pod 状态、Service endpoints、QPS、资源使用）
3. 检测资源泄漏（连接、文件描述符、内存）
4. 计算恢复时间
5. 生成自我恢复验证报告

**输出示例**：
```
自我恢复验证报告
================
实验 ID: pod-failure-20240101-100000
实验类型: Pod 故障
目标服务: frontend
故障移除时间: 10:02:00

自我恢复验证:

1. Pod 自动重启 ✅
   - 重建时间: 45s (预期 ≤60s) ✅
   - Ready 状态: 已达到 ✅

2. 健康检查 ✅
   - liveness probe: 正常触发重启 ✅
   - readiness probe: 正确标记 NotReady → Ready ✅

3. Service 发现更新 ✅
   - endpoints 更新时间: 20s (预期 ≤30s) ✅
   - 流量切换: 自动切换到健康 Pod ✅

4. 连接重建 ✅
   - 连接泄漏: 0 (预期 0) ✅
   - 连接重建时间: 15s (预期 ≤30s) ✅

5. 资源使用恢复 ✅
   - CPU 使用率恢复正常时间: 2min (预期 ≤5min) ✅
   - Memory 使用率恢复正常时间: 1min (预期 ≤5min) ✅

恢复时间分析:
| 指标 | 实际值 | 预期值 | 评价 |
|------|--------|--------|------|
| Pod 恢复时间 | 45s | ≤60s | ✅ 优秀 |
| Service 更新时间 | 20s | ≤30s | ✅ 优秀 |
| 连接重建时间 | 15s | ≤30s | ✅ 优秀 |
| 完全恢复时间 | 3min | ≤5min | ✅ 优秀 |

资源泄漏检测:
- 连接泄漏: 0 ✅
- 文件描述符泄漏: 0 ✅
- 内存泄漏: 0 ✅

问题识别: 无

改进建议: 无

整体评价: 通过 ✅
```

**验收标准**：
- [ ] 能正确获取实验信息
- [ ] 能查询恢复后的指标
- [ ] 能检测资源泄漏
- [ ] 能计算恢复时间
- [ ] 能生成可读的验证报告
- [ ] 能提供改进建议

---

#### 10. `/chaos-report` - 生成实验报告

**功能**：生成完整的混沌实验报告，包含实验信息、观察数据、验证结果和改进建议

**用法**：
```
/chaos-report [experiment-id]
```

**参数**：
- `experiment-id`: 可选，指定实验 ID（默认：生成最近完成实验的报告）

**执行流程**：
1. 获取实验信息（类型、目标服务、时长、预期告警）
2. 获取实验期间的观察数据（指标、链路、日志）
3. 获取告警验证结果
4. 获取自我恢复验证结果
5. 整合所有数据生成完整报告

**输出示例**：
```
混沌实验报告
============
实验 ID: pod-failure-20240101-100000
报告生成时间: 2024-01-01 10:05:00

实验信息:
- 实验类型: Pod 故障
- 目标服务: frontend
- 故障类型: PodKill
- 实验时长: 2m
- 开始时间: 2024-01-01 10:00:00
- 结束时间: 2024-01-01 10:02:00
- 预期告警: PodNotReady, ServiceUnavailable

观察数据:
Pod 状态:
- 故障前: Running (frontend-7d9f5c6f8d-x2k4p)
- 故障后: Pending → Running → Ready (45s)
- 重建后: Running (frontend-7d9f5c6f8d-p7j9l)

Service 状态:
- 故障前: 3/3 endpoints
- 故障后: 2/3 → 3/3 (20s)

性能指标:
- QPS: 150 → 120 → 145 (3min 内恢复 96.7%)
- 错误率: 0.1% → 3.2% → 0.15%
- P95 延迟: 80ms → 180ms → 85ms

链路数据:
- 错误 span: 142 个
- 超时 span: 23 个
- 平均响应时间: 120ms

告警验证结果:
✅ PodNotReady: 5s 内触发，响应时间优秀
❌ ServiceUnavailable: 未触发
覆盖率: 50% (1/2)

自我恢复验证结果:
✅ Pod 恢复时间: 45s (优秀)
✅ Service 更新时间: 20s (优秀)
✅ 连接重建: 无泄漏 (15s)
✅ 资源恢复: 3min (优秀)
评价: 通过

问题识别:
1. ServiceUnavailable 告警未触发

改进建议:
1. 检查 ServiceUnavailable 告警规则
2. 或调整预期告警列表

Runbook 更新:
- ✅ Pod 故障恢复时间: 45s
- ✅ 错误率 spike: 3.2%
- ✅ 恢复成功率: 100%

附件:
- Grafana 大盘截图: ./reports/pod-failure-20240101-100000/grafana.png
- Tempo 链路: ./reports/pod-failure-20240101-100000/traces.json
- Loki 日志: ./reports/pod-failure-20240101-100000/logs.json

总结:
- 系统弹性: 优秀 ✅
- 告警有效性: 部分 ⚠️
- 自我恢复能力: 优秀 ✅
- 整体评价: 通过 ⚠️
```

**验收标准**：
- [ ] 能正确获取实验信息
- [ ] 能整合所有观察数据
- [ ] 能包含告警验证结果
- [ ] 能包含自我恢复验证结果
- [ ] 能生成可读的完整报告
- [ ] 能提供改进建议
- [ ] 能更新 Runbook

---

#### 11. `/chaos-abort` - 中止混沌实验

**功能**：中止正在运行的混沌实验，立即移除故障

**用法**：
```
/chaos-abort [experiment-id]
```

**参数**：
- `experiment-id`: 可选，指定实验 ID（默认：中止所有运行中的实验）

**执行流程**：
1. 获取运行中的实验列表
2. 确认中止操作
3. 删除 Chaos Mesh CRD
4. 等待故障移除
5. 验证资源清理完成
6. 显示中止结果

**输出示例**：
```
中止混沌实验
============
找到运行中的实验: 1

实验 1: pod-failure-20240101-100000
状态: Running (已运行 90s / 2m)
目标服务: frontend

正在中止...
1. 删除 PodChaos CRD... ✅
2. 等待故障移除... ✅
3. 验证资源清理... ✅

中止完成:
- 实验已中止
- 故障已移除
- 资源已清理
- 系统正在恢复

下一步:
- 使用 /chaos-monitor 监控恢复状态
- 使用 /chaos-validate-self-heal 验证自我恢复
- 使用 /chaos-report 生成部分实验报告
```

**验收标准**：
- [ ] 能正确获取运行中的实验
- [ ] 能成功中止实验
- [ ] 能验证资源清理完成
- [ ] 能显示中止结果
- [ ] 能提供下一步操作指引

---

### Skills 验证计划

在交付前，需要验证所有 skills 可以用于触发所有的故障：

| Skill | 验证场景 | 验收标准 |
|-------|---------|---------|
| /chaos-check-alerts | 所有实验前 | 能正确检查覆盖度并给出建议 |
| /chaos-inject-pod | Pod 故障 | 能成功触发 PodKill 并监控 |
| /chaos-inject-network | 网络延迟 | 能成功触发网络延迟并监控 |
| /chaos-inject-dependency | 依赖故障 | 能成功触发依赖故障并监控 |
| /chaos-inject-resource | 资源耗尽 | 能成功触发资源压力并监控 |
| /chaos-inject-cascade | 级联故障 | 能成功触发多个故障并监控 |
| /chaos-monitor | 所有运行中的实验 | 能正确显示实时状态和指标 |
| /chaos-validate-alerts | 所有完成的实验 | 能正确验证告警触发并生成报告 |
| /chaos-validate-self-heal | 所有完成的实验 | 能正确验证自我恢复并生成报告 |
| /chaos-report | 所有完成的实验 | 能生成完整的实验报告 |
| /chaos-abort | 所有运行中的实验 | 能成功中止实验并清理资源 |

---

## 迁移计划

### 阶段 1：Chaos Mesh 部署
1. 将 Chaos Mesh Helm chart 仓库添加到部署脚本
2. 创建 `deploy/monitoring/chaos-mesh-values.yaml` 并配置设置
3. 将 Chaos Mesh 部署到 monitoring 命名空间
4. 验证控制器和 webhook 健康状态

### 阶段 2：实验模板
1. 为预定义实验创建 YAML 清单（参考全流程设计）
2. 为每个实验定义预期告警列表
3. 在开发/测试环境中测试每个实验
4. 记录预期行为和恢复模式

### 阶段 3：可观测性集成
1. 配置 Prometheus 抓取 Chaos Mesh 指标
2. 创建混沌实验的 Grafana 大盘（包含所有观察指标和告警面板）
3. 创建告警验证 Grafana 大盘（告警触发时间、响应时间、覆盖率）
4. 测试混沌运行期间告警正确触发

### 阶段 4：告警验证流程
1. 建立告警验证工作流程
2. 创建告警验证报告模板
3. 训练运维人员识别告警缺失和误报
4. 建立告警规则改进流程

### 阶段 5：文档和培训
1. 记录混沌实验工作流程
2. 为每种实验类型创建运行手册（包含全流程、观察指标、验证点、告警验证）
3. 创建告警验证指南
4. 培训运维人员使用 chaos mesh 和告警验证流程
5. 建立混沌实验审查流程

### 回滚策略
- 通过 `helm uninstall` 移除 Chaos Mesh
- 删除实验 CRD（如果未自动清理）
- 恢复原始监控大盘
- 保留告警验证报告用于分析

## 待解决问题

1. **混沌实验审批流程：** 谁应该批准生产环境中的混沌实验？需要定义 RBAC 和审批工作流程。

2. **实验调度：** 实验应按计划运行还是手动触发？考虑选项：
   - 手动触发（当前计划）
   - 基于 Cron 的计划运行
   - 事件触发运行（如部署后）

3. **SLO 基线定义：** Online Boutique 服务的当前 SLO 是什么？需要基线指标来衡量混沌实验影响。

4. **多集群混沌：** 我们是否应支持跨多个集群的混沌实验？目前超出范围，但值得为未来考虑。

5. **告警验证自动化：** 如何自动化告警验证流程？需要定义 `expectedAlerts` 字段格式和自动化脚本。