## 背景

Online Boutique 微服务演示部署在 Kubernetes 上，配有完整的可观测性栈，包括 Prometheus、Grafana、Loki、Tempo 和 AlertManager。虽然系统有全面的监控，但缺乏通过混沌工程进行的系统化弹性测试。

当前状态：
- 微服务位于 `online-boutique` 命名空间（frontend、checkoutservice、adservice、recommendationservice 等）
- 可观测性栈位于 `monitoring` 命名空间
- 未部署混沌工程工具
- 无系统化的故障注入或弹性测试

约束：
- 必须与现有部署和可观测性栈集成
- 必须使用现有的 Helm 部署方式
- 不得影响生产稳定性（需要防护机制）

## 目标 / 非目标

**目标：**
- 部署具有故障注入能力的混沌工程工具
- 为常见的 Online Boutique 故障场景提供预定义实验
- 与现有可观测性栈集成以进行监控和告警
- 建立防护机制以防止破坏性实验
- 记录运行和分析混沌实验的工作流程

**非目标：**
- 生产环境中的混沌实验（初始范围：开发/测试）
- CI/CD 流水线中的自动化混沌测试（未来增强）
- 与外部 SRE 平台集成
- 多集群场景的混沌实验

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
- 计划内实验期间的 AlertManager 抑制规则
- 实验事件的 Loki 日志聚合

### 6. 混沌实验期间的告警管理

**决策：** 通过 AlertManager 抑制规则进行告警抑制

**理由：**
- 减少计划内实验期间的噪音
- 保持关键告警
- 易于通过 Kubernetes 注解或标签启用/禁用
- 标准 AlertManager 功能

**实现：**
- 用 `chaos: "enabled"` 标记实验
- AlertManager 抑制规则在受影响的 Pod 上匹配此标签
- 关键告警（服务宕机）绕过抑制

## 故障注入全生命周期设计

### Pod 故障注入全流程

**目标：** 验证应用在 Pod 突然终止时的自愈能力，包括自动重启、连接重建和状态恢复。

**全流程步骤：**

1. **准备阶段（Pre-Chaos）**
   - 记录基准指标：Pod 状态、服务 QPS、错误率、P95/P99 延迟、活跃连接数
   - 获取当前链路样本（用于对比）
   - 记录相关服务的日志级别

2. **执行阶段（Chaos Injection）**
   - 选择目标 Pod（可指定或随机）
   - 应用 PodKill 故障（终止 Pod）
   - Kubernetes 触发重建 Pod

3. **观察阶段（During Chaos）**
   - 监控 Pod 重建时间（Pending → Running → Ready）
   - 观察 Service endpoints 更新
   - 监控错误率是否超过阈值
   - 观察 Temporal traces 是否出现超时或失败
   - 检查应用日志是否有连接错误、重试日志

4. **恢复阶段（Post-Chaos）**
   - 等待 Pod Ready 后持续观察 2-5 分钟
   - 验证 QPS 是否恢复到基准水平
   - 验证错误率是否恢复正常
   - 验证 P95/P99 延迟是否恢复正常
   - 检查是否有"僵尸连接"或泄漏

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
| 日志 | Error log count, retry log, connection error | Loki |

**验证点：**
1. Pod 在定义的重启时间（如 60s）内恢复 Ready 状态
2. Service endpoints 在 Pod Ready 后 30s 内更新
3. 错误率 spike 不超过 10%（除非目标服务单副本）
4. 5 分钟内 QPS 恢复到基准的 90% 以上
5. 链路中出现的错误 span 集中在故障期间
6. 日志中能看到连接重建、重试的成功记录

**验收标准：**
- [ ] Pod 故障注入后能在预期时间内自动重建并 Ready
- [ ] 服务流量能自动切换到健康的 Pod
- [ ] 错误率 spike 在可接受范围内并快速恢复
- [ ] 无持久化资源泄漏（连接、文件描述符等）
- [ ] 可观测性数据完整记录故障和恢复过程
- [ ] 无人工干预情况下系统完全自动恢复

---

### 网络延迟注入全流程

**目标：** 验证应用在高网络延迟下的超时处理、重试逻辑和用户体验降级。

**全流程步骤：**

1. **准备阶段（Pre-Chaos）**
   - 记录基准 P50/P95/P99 延迟
   - 记录超时配置（client timeout, server timeout）
   - 记录重试策略（重试次数、退避算法）
   - 获取正常链路样本

2. **执行阶段（Chaos Injection）**
   - 选择目标服务（如 recommendationservice）
   - 应用 NetworkDelay 故障（如 500ms 延迟，jitter 50ms）
   - 可选：同时注入丢包（如 5%）

3. **观察阶段（During Chaos）**
   - 监控 P50/P95/P99 延迟变化
   - 观察是否触发超时
   - 监控重试次数
   - 观察是否触发熔断（如果有）
   - 检查是否返回降级响应（如缓存数据、默认值）
   - 监控客户端请求队列积压

4. **恢复阶段（Post-Chaos）**
   - 移除网络延迟
   - 观察 2-5 分钟，验证延迟恢复正常
   - 验证无"慢启动"问题（连接池预热）
   - 验证队列积压已清空

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
| 日志 | Timeout logs, fallback logs, queue warnings | Loki |

**验证点：**
1. P95 延迟 spike 符合注入的延迟量 + 处理时间
2. 超时仅在延迟超过配置阈值时发生
3. 重试次数符合配置策略（不会无限重试）
4. 熔断器在持续错误时正确触发
5. 降级机制在服务不可用时正确返回
6. 移除延迟后无"慢恢复"现象

**验收标准：**
- [ ] 应用正确处理高延迟场景（超时、重试、熔断生效）
- [ ] 降级机制在需要时正确触发
- [ ] 移除延迟后系统快速恢复到基准性能
- [ ] 无级联故障（延迟不会传播到上游服务）
- [ ] 可观测性能清晰反映延迟注入的影响
- [ ] 无资源耗尽（连接池、线程池、队列）

---

### 服务依赖故障注入全流程

**目标：** 验证应用在依赖服务不可用时的优雅降级、熔断和缓存机制。

**全流程步骤：**

1. **准备阶段（Pre-Chaos）**
   - 识别服务依赖图（如 frontend → adservice → recommendationservice）
   - 记录依赖服务的调用频率
   - 检查是否有缓存（本地缓存、Redis、Memcached）
   - 检查降级配置（默认值、缓存过期策略）
   - 记录熔断器配置

2. **执行阶段（Chaos Injection）**
   - 选择依赖服务（如 adservice）
   - 应用 PodNetworkFault（网络隔离）或 HTTPFault（HTTP 500）
   - 或直接删除 Pod 模拟服务下线

3. **观察阶段（During Chaos）**
   - 监控上游服务的错误率（如 frontend 调用 adservice）
   - 观察熔断器状态变化
   - 监控降级响应命中数
   - 检查缓存命中/未命中比
   - 观察用户体验是否有明显影响（如广告位为空但页面可访问）
   - 监控是否有重试风暴

4. **恢复阶段（Post-Chaos）**
   - 恢复依赖服务
   - 观察熔断器恢复时间（半开 → 关闭）
   - 验证流量逐步恢复
   - 检查是否有"惊群效应"（所有请求同时涌入恢复的服务）

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
| 日志 | Fallback logs, cache logs, circuit logs | Loki |

**验证点：**
1. 依赖故障后上游服务错误率 spike 但在可控制范围
2. 熔断器在持续错误后快速打开，避免重试风暴
3. 降级响应正确返回（如空广告、默认推荐）
4. 缓存命中率在故障期间提升（如果有）
5. 用户体验未完全中断（关键功能可用）
6. 恢复后流量逐步恢复，无惊群效应

**验收标准：**
- [ ] 依赖故障不导致级联故障
- [ ] 熔断器正确打开和恢复
- [ ] 降级机制有效，用户体验保持可用
- [ ] 无重试风暴或资源耗尽
- [ ] 恢复后服务平滑过渡，无性能 spike
- [ ] 可观测性能清晰反映故障传播和恢复

---

### 资源耗尽注入全流程

**目标：** 验证应用在 CPU 或内存资源紧张时的表现，包括节流、OOM 保护和 graceful degradation。

**全流程步骤：**

1. **准备阶段（Pre-Chaos）**
   - 记录当前资源使用（CPU %, Memory %）
   - 检查资源限制配置（limits, requests）
   - 记录 QPS 和响应时间基准
   - 检查是否有优雅降级逻辑（如降低缓存、减少计算）

2. **执行阶段（Chaos Injection）**
   - 选择目标 Pod
   - 应用 CPUStress（如 90% CPU）或 MemoryStress（如 80% 内存）
   - 可选：同时压测流量以放大效果

3. **观察阶段（During Chaos）**
   - 监控 CPU/Memory 使用率是否达到 limits
   - 观察是否触发 CPU 节流（CPU throttling）
   - 检查是否触发 OOM（内存耗尽）
   - 监控 QPS 下降幅度
   - 观察 P95/P99 延迟 spike
   - 检查是否有 graceful degradation（如减少计算量）
   - 监控 Kubernetes 的 QoS 调度

4. **恢复阶段（Post-Chaos）**
   - 移除压力
   - 观察 Pod 是否需要重启（如 OOM 后）
   - 验证资源使用恢复正常
   - 验证性能逐步恢复

**观察指标：**
| 指标类型 | 具体指标 | 工具 |
|---------|---------|------|
| 资源使用 | container_cpu_usage_seconds_total, container_memory_working_set_bytes | Prometheus |
| CPU 节流 | container_cpu_cfs_throttled_periods_total, container_cpu_cfs_periods_total | Prometheus |
| OOM | oom_killed, memory_usage_exceeds_limit | Prometheus/K8s |
| 性能 | QPS, P50/P95/P99 latency | Prometheus/Tempo |
| 降级 | degraded_mode_active, reduced_computation | Prometheus/Loki |
| QoS | pod_qos_class, kubernetes_pod_status | Prometheus |
| 日志 | Throttling logs, OOM logs, degradation logs | Loki |

**验证点：**
1. 资源使用达到限制时触发节流或 OOM
2. 应用有足够的 CPU limits，避免影响其他 Pod
3. Memory limits 配置合理，避免频繁 OOM
4. QPS 下降在预期范围内
5. 延迟 spike 在可接受范围
6. 如果有 graceful degradation，正确触发

**验收标准：**
- [ ] 资源限制正确配置并生效
- [ ] 资源紧张时应用表现符合预期（节流或 OOM）
- [ ] 不影响其他 Pod（通过 QoS 隔离）
- [ ] 资源移除后应用正常恢复
- [ ] 可观测性能清晰反映资源状态
- [ ] 无系统性资源饥饿（Kubernetes node 正常）

---

### 级联故障注入全流程

**目标：** 验证系统在多个故障同时发生时的弹性，包括隔离机制、断路器和熔断链。

**全流程步骤：**

1. **准备阶段（Pre-Chaos）**
   - 绘制完整的服务依赖图
   - 识别关键路径和单点故障
   - 记录各服务的熔断器配置
   - 检查是否有隔离机制（如资源隔离、连接池隔离）

2. **执行阶段（Chaos Injection）**
   - 选择多个故障点（如：adservice PodKill + recommendationservice NetworkDelay + checkoutservice CPUStress）
   - 同时或按顺序注入故障
   - 可选：增加流量压力以放大效果

3. **观察阶段（During Chaos）**
   - 监控错误率 spike（各服务）
   - 观察熔断器链（哪些打开，哪些保持关闭）
   - 检查是否有级联故障（如 frontend → adservice → 上游）
   - 监控整体系统可用性（关键功能是否可用）
   - 观察资源使用（是否有资源饥饿）
   - 检查是否有"雪崩"效应（请求积压导致更多失败）

4. **恢复阶段（Post-Chaos）**
   - 按相反顺序移除故障
   - 观察熔断器恢复链
   - 验证系统逐层恢复
   - 检查恢复后是否有性能问题

**观察指标：**
| 指标类型 | 具体指标 | 工具 |
|---------|---------|------|
| 系统可用性 | system_available, critical_function_available | Prometheus |
| 错误传播 | error_rate_by_service, cascading_failures | Prometheus |
| 熔断链 | circuit_state_by_service, cascade_depth | Prometheus |
| 资源隔离 | resource_usage_by_pod, node_resource_usage | Prometheus |
| 请求积压 | request_queue_length, pending_requests | Prometheus |
| 链路 | Cascade failure trace span, timeout chain | Tempo |
| 日志 | Cascade logs, circuit logs, isolation logs | Loki |

**验证点：**
1. 级联故障被隔离在故障服务，不传播到其他服务
2. 熔断器链正确工作，防止雪崩
3. 系统核心功能保持可用（如浏览商品可用，但下单可能受影响）
4. 资源隔离生效，故障不影响其他服务的资源
5. 恢复时系统逐层恢复，无二次故障
6. 可观测性能清晰反映故障传播和隔离效果

**验收标准：**
- [ ] 级联故障被有效隔离
- [ ] 系统关键功能保持可用
- [ ] 熔断器链正确工作
- [ ] 资源隔离生效
- [ ] 恢复时系统平滑过渡
- [ ] 可观测性能完整记录级联故障和恢复

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

### 权衡 1：功能丰富度 vs 简单性

**决策：** 优先考虑功能丰富度

Chaos Mesh 提供许多故障注入类型。我们将启用大部分功能，但保持默认配置保守。

### 权衡 2：自动化 vs 手动控制

**决策：** 手动控制配合自动化钩子

最初要求手动实验审批。未来增强可以添加基于计划或触发器的自动化实验。

## 迁移计划

### 阶段 1：Chaos Mesh 部署
1. 将 Chaos Mesh Helm chart 仓库添加到部署脚本
2. 创建 `deploy/monitoring/chaos-mesh-values.yaml` 并配置设置
3. 将 Chaos Mesh 部署到 monitoring 命名空间
4. 验证控制器和 webhook 健康状态

### 阶段 2：实验模板
1. 为预定义实验创建 YAML 清单（参考全流程设计）
2. 在开发/测试环境中测试每个实验
3. 记录预期行为和恢复模式

### 阶段 3：可观测性集成
1. 配置 Prometheus 抓取 Chaos Mesh 指标
2. 创建混沌实验的 Grafana 大盘（包含所有观察指标）
3. 添加计划内实验的 AlertManager 抑制规则
4. 测试混沌运行期间的告警抑制

### 阶段 4：文档和培训
1. 记录混沌实验工作流程
2. 为每种实验类型创建运行手册（包含全流程、观察指标、验证点）
3. 培训运维人员使用 chaos mesh
4. 建立混沌实验审查流程

### 回滚策略
- 通过 `helm uninstall` 移除 Chaos Mesh
- 删除实验 CRD（如果未自动清理）
- 移除 AlertManager 抑制规则
- 恢复原始监控大盘

## 待解决问题

1. **混沌实验审批流程：** 谁应该批准生产环境中的混沌实验？需要定义 RBAC 和审批工作流程。

2. **实验调度：** 实验应按计划运行还是手动触发？考虑选项：
   - 手动触发（当前计划）
   - 基于 Cron 的计划运行
   - 事件触发运行（如部署后）

3. **SLO 基线定义：** Online Boutique 服务的当前 SLO 是什么？需要基线指标来衡量混沌实验影响。

4. **多集群混沌：** 我们是否应支持跨多个集群的混沌实验？目前超出范围，但值得为未来考虑。