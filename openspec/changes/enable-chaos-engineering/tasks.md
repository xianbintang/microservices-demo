## 1. 告警覆盖度检查

- [ ] 1.1 定义关键告警场景清单
  - 定义 Pod 状态相关告警场景（PodDown, PodNotReady, PodCrashLoopBackOff）
  - 定义服务可用性相关告警场景（ServiceDown, ServiceUnavailable）
  - 定义性能指标相关告警场景（HighLatency, HighErrorRate, High5xxRate）
  - 定义资源使用相关告警场景（HighCPUUsage, HighMemoryUsage, PodOOMKilled, CPUThrottlingHigh）
  - 定义依赖服务相关告警场景（DependencyErrorRateHigh, DependencyTimeout）
  - 定义熔断器相关告警场景（CircuitBreakerOpen）
  - 为每个场景定义必需的严重级别

- [ ] 1.2 创建告警覆盖度检查脚本
  - 创建脚本扫描当前告警规则（PrometheusRule/AlertManagerConfig）
  - 对比关键告警场景清单
  - 识别缺失的告警规则
  - 计算告警覆盖率
  - 生成检查报告

- [ ] 1.3 定义告警覆盖率阈值
  - 定义覆盖率阈值（如 ≥ 80% 允许执行实验）
  - 定义关键场景要求（所有关键场景必须有告警覆盖）
  - 定义告警严重级别要求（关键场景必须有 Critical 级别）

- [ ] 1.4 创建告警覆盖度检查报告模板
  - 设计报告结构（检查时间、覆盖度统计、已覆盖告警、缺失告警、评估结果、操作建议）
  - 创建报告模板文件（docs/chaos/alert-coverage-report-template.md）
  - 定义阻塞状态逻辑

- [ ] 1.5 执行告警覆盖度检查
  - 扫描当前告警规则
  - 对比关键场景清单
  - 生成覆盖度报告
  - 根据覆盖率评估是否允许执行混沌实验

- [ ] 1.6 补充缺失的告警规则
  - 根据覆盖度报告生成告警规则模板
  - 添加缺失的告警规则到部署
  - 重新执行覆盖度检查
  - 验证覆盖率达到要求

## 2. Chaos Mesh 部署设置

- [ ] 2.1 将 Chaos Mesh Helm 仓库添加到部署脚本
  - 编辑 `Makefile` 或部署脚本，添加 Chaos Mesh repo
  - 使用官方 Helm repo: `https://charts.chaos-mesh.org`
  - 验证 repo 可访问

- [ ] 2.2 创建 `deploy/monitoring/chaos-mesh-values.yaml` 并配置设置
  - 配置 `imagePullSecrets`（如需要）
  - 设置 `clusterScoped: false`（可选，限制在特定命名空间）
  - 配置控制器副本数为 2（高可用）
  - 配置 webhook 副本数为 2
  - 启用 Web UI（dashboard）

- [ ] 2.3 为 Chaos Mesh 镜像配置 `imagePullSecrets`（如需要）
  - 在 values.yaml 中配置 `imagePullSecrets`
  - 验证镜像可拉取
  - 如使用私有镜像，提前准备好 secret

- [ ] 2.4 使用 `helm upgrade --install` 将 Chaos Mesh 部署到 monitoring 命名空间
  - 执行 helm install 命令
  - 验证所有 Pod 正常启动
  - 验证 CRD 已安装（`kubectl get crd | grep chaos`）

- [ ] 2.5 验证 Chaos Mesh 控制器和 webhook Pod 健康状态
  - 检查 `chaos-controller-manager` Pod Ready
  - 检查 `chaos-daemon` Pod 在每个节点运行
  - 检查 `chaos-dashboard` Pod Ready（如启用）
  - 验证 webhook 正常工作（创建测试 CRD）

## 3. Chaos Mesh 配置

- [ ] 3.1 配置 Chaos Mesh 命名空间白名单（仅 online-boutique）
  - 在 values.yaml 或 ConfigMap 中配置 `namespace: online-boutique`
  - 验证其他命名空间的实验被拒绝
  - 测试：尝试在 monitoring 命名空间创建实验，应被拒绝

- [ ] 3.2 配置 Chaos Mesh 资源黑名单（monitoring、kube-system）
  - 在 admission webhook 中配置资源黑名单
  - 防止对监控组件注入故障
  - 防止对 kube-system 注入故障
  - 测试：尝试对 Prometheus Pod 创建实验，应被拒绝

- [ ] 3.3 为故障注入设置安全默认限制（最大时长、强度）
  - 设置 `duration` 最大值（如 10 分钟）
  - 设置网络延迟最大值（如 2000ms）
  - 设置 CPU 压力最大值（如 90%）
  - 设置内存压力最大值（如 80%）
  - 验证超过限制的配置被拒绝

- [ ] 3.4 配置准入 Webhook 进行实验验证
  - 启用 validation webhook
  - 配置验证规则（命名空间、资源、参数范围）
  - 测试验证逻辑

- [ ] 3.5 验证 Chaos Mesh CRD 已安装且功能正常
  - 列出所有 CRD：`PodChaos`, `NetworkChaos`, `StressChaos`, `IOChaos`, `KernelChaos`, `TimeChaos`, `HTTPChaos`, `PhysicalMachineChaos`
  - 创建测试实验验证功能
  - 验证实验可以正常创建和删除

## 4. 预定义混沌实验

- [ ] 4.1 创建 pod-failure 实验模板（deploy/chaos/pod-failure.yaml）
  - 配置 `PodChaos` 资源
  - 设置 `action: pod-kill`
  - 配置目标命名空间: `online-boutique`
  - 配置目标 selector（可指定服务或随机）
  - 设置 `duration: 2m`
  - 添加实验标签和注解（用于可观测性关联）
  - **添加预期告警列表**：`expectedAlerts: ["PodNotReady", "ServiceUnavailable"]`
  - 添加 `mode: one`（每次终止一个 Pod）或 `mode: all`（终止所有 Pod）

- [ ] 4.2 创建 network-latency 实验模板（deploy/chaos/network-latency.yaml）
  - 配置 `NetworkChaos` 资源
  - 设置 `action: delay`
  - 配置 `delay.latency: 500ms`, `delay.jitter: 50ms`
  - 配置 `direction: to` 或 `both`
  - 配置目标服务（如 recommendationservice）
  - 可选：添加 `loss: 5`（5% 丢包）
  - 添加实验标签和注解
  - **添加预期告警列表**：`expectedAlerts: ["HighLatency", "High5xxRate"]`

- [ ] 4.3 创建 dependency-failure 实验模板（deploy/chaos/dependency-failure.yaml）
  - 配置 `PodNetworkChaos` 或 `HTTPChaos`
  - 选择依赖服务（如 adservice）
  - 配置网络隔离（`action: partition`）或 HTTP 500
  - 设置 `duration: 3m`
  - 配置上游服务观察点（如 frontend）
  - 添加实验标签和注解
  - **添加预期告警列表**：`expectedAlerts: ["ServiceUnavailable", "DependencyErrorRateHigh", "CircuitBreakerOpen"]`

- [ ] 4.4 创建 resource-exhaustion 实验模板（deploy/chaos/resource-exhaustion.yaml）
  - 配置 `StressChaos` 资源
  - 配置 CPU 压力：`stressors.cpu.workers: 2`, `stressors.cpu.load: 90`
  - 或配置内存压力：`stressors.memory.size: 80%`
  - 配置目标 Pod
  - 设置 `duration: 5m`
  - 添加实验标签和注解
  - **添加预期告警列表**：`expectedAlerts: ["HighCPUUsage", "HighMemoryUsage", "PodOOMKilled", "CPUThrottlingHigh"]`

- [ ] 4.5 创建 cascade-failure 实验模板（deploy/chaos/cascade-failure.yaml）
  - 创建多个 Chaos 资源在单个文件中
  - 组合多个故障（如 PodKill + NetworkDelay + CPUStress）
  - 按顺序或同时执行
  - 设置各自的 `duration`
  - 添加实验标签和注解
  - **添加预期告警列表**：`expectedAlerts: ["CascadeFailureDetected", "ServiceUnavailable", "SystemDegraded", "CircuitBreakerCascade"]`

## 5. 可观测性集成

- [ ] 5.1 配置 Prometheus 抓取 Chaos Mesh 控制器指标
  - 添加 Chaos Mesh controller 到 Prometheus scrape config
  - 配置 scrape interval: 15s
  - 配置 metrics path: `/metrics`
  - 验证指标可查询（`chaos_mesh_controller_*`）

- [ ] 5.2 更新 kube-prometheus-stack-values.yaml 添加 Chaos Mesh 抓取配置
  - 在 `additionalScrapeConfigs` 中添加 Chaos Mesh
  - 配置 ServiceMonitor 或 PodSelector
  - 验证 Prometheus target 状态

- [ ] 5.3 创建混沌实验监控的 Grafana 大盘
  - 设计大盘布局（Pod 状态、错误率、延迟、链路、日志、告警）
  - 添加实验时间轴（标注混沌实验的开始和结束）
  - 添加以下面板：
    - Pod 状态（Running/Ready/Pending/Failed）
    - 服务 QPS（对比基线和实验期间）
    - 错误率（5xx、4xx）
    - P50/P95/P99 延迟
    - 链路查询（Tempo）
    - 日志搜索（Loki）
    - 实验状态（Chaos Mesh 指标）
    - **告警面板**（触发的告警、告警响应时间、告警恢复时间）
  - 添加变量选择器（命名空间、服务、实验类型）
  - 导出大盘 JSON

- [ ] 5.4 将混沌大盘添加到 Grafana 大盘 configmap
  - 编辑 `deploy/monitoring/dashboards/grafana-dashboards-configmap.yaml`
  - 添加新的 dashboard JSON
  - 验证 Grafana sidecar 重载大盘

- [ ] 5.5 配置混沌实验标签和注解用于可观测性关联
  - 在实验 YAML 中添加标准标签：
    - `chaos.mes.org/type: pod-failure`
    - `chaos.mes.org/namespace: online-boutique`
    - `chaos.mes.org/target-service: <service-name>`
  - 添加注解：
    - `chaos.mes.org/description: "Pod failure experiment"`
    - `chaos.mes.org/observability: "enable"`
    - `chaos.mes.org/expected-alerts: "PodNotReady,ServiceUnavailable"`
  - 配置 Prometheus relabeling 使用这些标签

## 6. 告警验证

- [ ] 6.1 建立告警验证工作流程
  - 定义告警验证流程：准备 → 执行 → 观察 → 分析
  - 创建告警验证检查清单
  - 定义告警验证模板

- [ ] 6.2 创建告警验证报告模板
  - 设计报告结构（实验信息、预期告警、实际告警、验证结果、改进建议）
  - 创建报告模板文件（docs/chaos/alert-validation-report-template.md）
  - 定义报告中的评估标准（覆盖率、响应时间、准确性）

- [ ] 6.3 为每个实验类型定义预期告警列表
  - Pod 故障：PodNotReady, ServiceUnavailable
  - 网络延迟：HighLatency, High5xxRate
  - 依赖故障：ServiceUnavailable, DependencyErrorRateHigh, CircuitBreakerOpen
  - 资源耗尽：HighCPUUsage, HighMemoryUsage, PodOOMKilled, CPUThrottlingHigh
  - 级联故障：CascadeFailureDetected, ServiceUnavailable, SystemDegraded, CircuitBreakerCascade

- [ ] 6.4 创建告警验证 Grafana 大盘
  - 设计大盘布局（告警覆盖率、响应时间、告警触发时间轴）
  - 添加以下面板：
    - 告警覆盖率（预期告警数 vs 实际触发告警数）
    - 告警响应时间（故障时间到告警触发时间的差值）
    - 告警恢复时间（告警触发到告警恢复的时间）
    - 告警触发时间轴（对比故障时间和告警时间）
    - 告警缺失列表（预期但未触发的告警）
    - 告警误报列表（未预期但触发的告警）
  - 添加变量选择器（实验类型、服务）
  - 导出大盘 JSON

- [ ] 6.5 训练运维人员识别告警缺失和误报
  - 创建告警验证培训材料
  - 举例说明常见告警缺失场景
  - 举例说明常见告警误报场景
  - 培训如何根据告警验证结果改进告警规则

## 7. 文档

- [ ] 7.1 创建混沌实验运行手册（docs/chaos/runbook.md）
  - 文档结构：
    - 实验概述
    - 前置条件（告警覆盖度检查）
    - 执行步骤
    - 观察指标（参考设计文档）
    - 验证点（参考设计文档）
    - **自我恢复能力验证**
    - **告警验证**
    - 故障排除
    - 回滚步骤
  - 为每种实验类型创建独立章节

- [ ] 7.2 记录每种实验类型及其预期行为
  - Pod 故障：Pod 终止 → Kubernetes 重建 → 服务恢复
  - 网络延迟：延迟注入 → 超时/重试/熔断 → 移除延迟 → 恢复
  - 依赖故障：服务不可用 → 降级/熔断 → 恢复服务 → 流量恢复
  - 资源耗尽：CPU/内存压力 → 节流/OOM → 移除压力 → 恢复
  - 级联故障：多个故障 → 隔离/熔断 → 移除故障 → 恢复

- [ ] 7.3 创建告警覆盖度检查指南（docs/chaos/alert-coverage-check-guide.md）
  - 告警覆盖度检查的目的和重要性
  - 关键告警场景清单
  - 告警覆盖度检查流程
  - 告警覆盖率阈值定义
  - 如何补充缺失的告警规则
  - 告警覆盖度报告解读

- [ ] 7.4 创建告警验证指南（docs/chaos/alert-validation-guide.md）
  - 告警验证的目的和重要性
  - 告警验证流程
  - 如何识别告警缺失
  - 如何识别告警误报
  - 如何评估告警响应时间
  - 如何改进告警规则
  - 告警验证报告模板

- [ ] 7.5 创建自我恢复能力验证指南（docs/chaos/self-healing-validation-guide.md）
  - 自我恢复能力的定义和重要性
  - Kubernetes 自我恢复机制（Pod 重启、健康检查、资源限制）
  - 自我恢复能力验证方法
  - 验证指标（恢复时间、恢复成功率、资源泄漏检测）
  - 验收标准
  - 常见问题和解决方案

- [ ] 7.6 创建混沌实验故障排除指南
  - 常见问题和解决方案：
    - 实验被拒绝（命名空间/资源黑名单）
    - 告警覆盖度不足
    - Pod 无法恢复（资源不足、镜像拉取失败）
    - 告警不触发（告警规则缺失、阈值不合理）
    - 告警不恢复（告警规则配置错误）
    - 自我恢复失败（资源限制、健康检查配置问题）
    - 观察数据缺失（Prometheus 抓取失败、Grafana 大盘未更新）
    - 实验无法中止（CRD 删除、资源清理）

- [ ] 7.7 记录 Chaos Mesh CLI 和 Web UI 使用方法
  - CLI 命令：
    - `kubectl apply -f experiment.yaml`
    - `kubectl get podchaos`
    - `kubectl delete podchaos <name>`
    - `kubectl describe podchaos <name>`
  - Web UI 使用：
    - 访问 dashboard URL
    - 创建实验
    - 查看实验状态
    - 中止实验
    - 查看实验历史

- [ ] 7.8 将混沌实验工作流程添加到项目 README
  - 添加 Chaos Engineering 章节
  - 链接到告警覆盖度检查指南、运行手册、告警验证指南、自我恢复能力验证指南和故障排除指南
  - 说明实验目的和最佳实践
  - 添加 Claude Code Skills 使用说明

## 8. Claude Code Skills 开发

- [ ] 8.1 创建 `/chaos-check-alerts` skill
  - 创建 `.claude/skills/chaos-check-alerts.md`
  - 实现告警覆盖度检查逻辑
  - 扫描 Prometheus 告警规则
  - 对比关键场景清单
  - 生成覆盖度报告
  - 实现阻塞机制（覆盖率 < 80% 或关键场景缺失时阻塞）
  - 验证：能正确检查覆盖度并给出建议

- [ ] 8.2 创建 `/chaos-inject-pod` skill
  - 创建 `.claude/skills/chaos-inject-pod.md`
  - 实现告警覆盖度检查调用
  - 实现目标 Pod 选择逻辑（指定服务或随机）
  - 实现基准指标记录
  - 实现 PodKill 故障注入
  - 实现实验状态显示
  - 验证：能成功触发 Pod 故障并监控

- [ ] 8.3 创建 `/chaos-inject-network` skill
  - 创建 `.claude/skills/chaos-inject-network.md`
  - 实现告警覆盖度检查调用
  - 实现目标服务检查
  - 实现基准指标记录（P95 延迟、错误率）
  - 实现 NetworkDelay 故障注入
  - 实现实验状态显示
  - 验证：能成功触发网络延迟并监控

- [ ] 8.4 创建 `/chaos-inject-dependency` skill
  - 创建 `.claude/skills/chaos-inject-dependency.md`
  - 实现告警覆盖度检查调用
  - 实现服务和依赖检查
  - 实现基准指标记录（上游错误率、熔断器状态）
  - 实现依赖故障注入（网络隔离或 HTTP 故障）
  - 实现实验状态显示
  - 验证：能成功触发依赖故障并监控

- [ ] 8.5 创建 `/chaos-inject-resource` skill
  - 创建 `.claude/skills/chaos-inject-resource.md`
  - 实现告警覆盖度检查调用
  - 实现资源告警检查（如 PodOOMKilled）
  - 实现目标服务检查
  - 实现基准指标记录（CPU/Memory 使用率、QPS）
  - 实现 StressChaos 故障注入
  - 实现实验状态显示
  - 验证：能成功触发资源压力并监控

- [ ] 8.6 创建 `/chaos-inject-cascade` skill
  - 创建 `.claude/skills/chaos-inject-cascade.md`
  - 实现告警覆盖度检查调用
  - 实现级联故障配置加载
  - 实现基准指标记录
  - 实现多故障注入逻辑（按配置注入多个故障）
  - 实现实验状态显示
  - 验证：能成功触发级联故障并监控

- [ ] 8.7 创建 `/chaos-monitor` skill
  - 创建 `.claude/skills/chaos-monitor.md`
  - 实现运行中实验查询
  - 实现实时指标获取（Pod 状态、错误率、延迟、告警状态）
  - 实现 Grafana 大盘链接生成
  - 实现实验状态显示
  - 验证：能正确显示实时状态和指标

- [ ] 8.8 创建 `/chaos-validate-alerts` skill
  - 创建 `.claude/skills/chaos-validate-alerts.md`
  - 实现实验信息获取
  - 实验期间告警查询
  - 实现预期告警和实际告警对比
  - 实现告警响应时间计算
  - 实现告警验证报告生成
  - 验证：能正确验证告警触发并生成报告

- [ ] 8.9 创建 `/chaos-validate-self-heal` skill
  - 创建 `.claude/skills/chaos-validate-self-heal.md`
  - 实现实验信息获取
  - 实现恢复后指标查询
  - 实现资源泄漏检测（连接、文件描述符、内存）
  - 实现恢复时间计算
  - 实现自我恢复验证报告生成
  - 验证：能正确验证自我恢复并生成报告

- [ ] 8.10 创建 `/chaos-report` skill
  - 创建 `.claude/skills/chaos-report.md`
  - 实现实验信息获取
  - 实现观察数据整合（指标、链路、日志）
  - 实现告警验证结果整合
  - 实现自我恢复验证结果整合
  - 实现完整实验报告生成
  - 实现 Runbook 更新
  - 验证：能生成完整的实验报告

- [ ] 8.11 创建 `/chaos-abort` skill
  - 创建 `.claude/skills/chaos-abort.md`
  - 实现运行中实验查询
  - 实现实验中止（删除 Chaos Mesh CRD）
  - 实现资源清理验证
  - 实现中止结果显示
  - 验证：能成功中止实验并清理资源

- [ ] 8.12 Skills 集成测试
  - **测试 1**: 使用 `/chaos-check-alerts` 检查告警覆盖度
    - 验证：能正确检查并生成报告
  - **测试 2**: 使用 `/chaos-inject-pod` 触发 Pod 故障
    - 验证：能成功触发并监控
    - 使用 `/chaos-monitor` 监控
    - 使用 `/chaos-abort` 中止
  - **测试 3**: 使用 `/chaos-inject-network` 触发网络延迟
    - 验证：能成功触发并监控
    - 使用 `/chaos-monitor` 监控
    - 实验完成后使用 `/chaos-validate-alerts` 验证告警
    - 使用 `/chaos-validate-self-heal` 验证自我恢复
    - 使用 `/chaos-report` 生成报告
  - **测试 4**: 使用 `/chaos-inject-dependency` 触发依赖故障
    - 验证：能成功触发并监控
    - 完整验证流程（告警、自我恢复、报告）
  - **测试 5**: 使用 `/chaos-inject-resource` 触发资源耗尽
    - 验证：能成功触发并监控
    - 完整验证流程
  - **测试 6**: 使用 `/chaos-inject-cascade` 触发级联故障
    - 验证：能成功触发并监控
    - 完整验证流程
  - **验收标准**:
    - [ ] 所有 skills 都能正常工作
    - [ ] 所有故障类型都可以通过 skills 触发
    - [ ] 所有验证流程都能通过 skills 完成
    - [ ] 实验报告能正确生成
    - [ ] Runbook 能正确更新

## 9. Skills 功能验证测试

- [ ] 9.1 验证 `/chaos-check-alerts` skill
  - **执行**: 运行 `/chaos-check-alerts online-boutique`
  - **验证**:
    - [ ] 能正确扫描告警规则
    - [ ] 能准确对比关键场景清单
    - [ ] 能计算正确的覆盖率
    - [ ] 能生成可读的检查报告
    - [ ] 能正确判断是否允许执行实验
  - **验收标准**: 全部通过

- [ ] 9.2 验证 `/chaos-inject-pod` skill
  - **执行**: 运行 `/chaos-inject-pod frontend 2m`
  - **验证**:
    - [ ] 能正确执行告警覆盖度检查
    - [ ] 能正确选择目标 Pod
    - [ ] 能成功应用 PodKill 故障
    - [ ] 能记录基准指标
    - [ ] 能显示实验状态和观察指标
    - [ ] 能提供下一步操作指引
  - **使用 `/chaos-monitor` 监控**: 验证能正确显示实时状态
  - **使用 `/chaos-abort` 中止**: 验证能成功中止实验
  - **验收标准**: 全部通过

- [ ] 9.3 验证 `/chaos-inject-network` skill
  - **执行**: 运行 `/chaos-inject-network recommendationservice 500ms 3m`
  - **验证**:
    - [ ] 能正确执行告警覆盖度检查
    - [ ] 能成功应用网络延迟故障
    - [ ] 能记录基准指标
    - [ ] 能显示实验状态和观察指标
    - [ ] 能提供下一步操作指引
  - **使用 `/chaos-monitor` 监控**: 验证能正确显示实时状态
  - **实验完成后使用 `/chaos-validate-alerts`**: 验证告警触发
  - **使用 `/chaos-validate-self-heal`**: 验证自我恢复
  - **使用 `/chaos-report`**: 生成报告
  - **验收标准**: 全部通过

- [ ] 9.4 验证 `/chaos-inject-dependency` skill
  - **执行**: 运行 `/chaos-inject-dependency frontend adservice 3m`
  - **验证**:
    - [ ] 能正确执行告警覆盖度检查
    - [ ] 能成功应用依赖故障
    - [ ] 能记录基准指标
    - [ ] 能显示实验状态和观察指标
    - [ ] 能提供下一步操作指引
  - **完整验证流程**: 监控 → 告警验证 → 自我恢复验证 → 报告
  - **验收标准**: 全部通过

- [ ] 9.5 验证 `/chaos-inject-resource` skill
  - **执行**: 运行 `/chaos-inject-resource checkoutservice memory 80 5m`
  - **验证**:
    - [ ] 能正确执行告警覆盖度检查
    - [ ] 能检查资源告警是否存在
    - [ ] 能成功应用资源压力故障
    - [ ] 能记录基准指标
    - [ ] 能显示实验状态和观察指标
    - [ ] 能提供下一步操作指引
  - **完整验证流程**: 监控 → 告警验证 → 自我恢复验证 → 报告
  - **验收标准**: 全部通过

- [ ] 9.6 验证 `/chaos-inject-cascade` skill
  - **执行**: 运行 `/chaos-inject-cascade default`
  - **验证**:
    - [ ] 能正确执行告警覆盖度检查
    - [ ] 能加载级联故障配置
    - [ ] 能成功注入多个故障
    - [ ] 能记录基准指标
    - [ ] 能显示实验状态和观察指标
    - [ ] 能提供下一步操作指引
  - **完整验证流程**: 监控 → 告警验证 → 自我恢复验证 → 报告
  - **验收标准**: 全部通过

- [ ] 9.7 验证 `/chaos-monitor` skill
  - **执行**: 在实验运行时使用 `/chaos-monitor`
  - **验证**:
    - [ ] 能正确查询运行中的实验
    - [ ] 能获取实时关键指标
    - [ ] 能显示告警状态
    - [ ] 能提供 Grafana 大盘链接
    - [ ] 能提供下一步操作指引
  - **验收标准**: 全部通过

- [ ] 9.8 验证 `/chaos-validate-alerts` skill
  - **执行**: 实验完成后使用 `/chaos-validate-alerts`
  - **验证**:
    - [ ] 能正确获取实验信息
    - [ ] 能查询实验期间的告警
    - [ ] 能准确对比预期和实际告警
    - [ ] 能计算告警响应时间
    - [ ] 能生成可读的验证报告
    - [ ] 能提供改进建议
  - **验收标准**: 全部通过

- [ ] 9.9 验证 `/chaos-validate-self-heal` skill
  - **执行**: 实验完成后使用 `/chaos-validate-self-heal`
  - **验证**:
    - [ ] 能正确获取实验信息
    - [ ] 能查询恢复后的指标
    - [ ] 能检测资源泄漏
    - [ ] 能计算恢复时间
    - [ ] 能生成可读的验证报告
    - [ ] 能提供改进建议
  - **验收标准**: 全部通过

- [ ] 9.10 验证 `/chaos-report` skill
  - **执行**: 实验完成后使用 `/chaos-report`
  - **验证**:
    - [ ] 能正确获取实验信息
    - [ ] 能整合所有观察数据
    - [ ] 能包含告警验证结果
    - [ ] 能包含自我恢复验证结果
    - [ ] 能生成可读的完整报告
    - [ ] 能提供改进建议
    - [ ] 能更新 Runbook
  - **验收标准**: 全部通过

- [ ] 9.11 验证 `/chaos-abort` skill
  - **执行**: 在实验运行时使用 `/chaos-abort`
  - **验证**:
    - [ ] 能正确获取运行中的实验
    - [ ] 能成功中止实验
    - [ ] 能验证资源清理完成
    - [ ] 能显示中止结果
    - [ ] 能提供下一步操作指引
  - **验收标准**: 全部通过

## 10. 完整流程端到端测试

- [ ] 10.1 Pod 故障完整流程测试
  - **步骤**:
    1. 使用 `/chaos-check-alerts` 检查覆盖度
    2. 使用 `/chaos-inject-pod` 触发实验
    3. 使用 `/chaos-monitor` 监控实验
    4. 使用 `/chaos-validate-alerts` 验证告警
    5. 使用 `/chaos-validate-self-heal` 验证自我恢复
    6. 使用 `/chaos-report` 生成报告
  - **验收标准**: 所有步骤都能通过 skills 完成，报告完整

- [ ] 10.2 网络延迟完整流程测试
  - **步骤**:
    1. 使用 `/chaos-check-alerts` 检查覆盖度
    2. 使用 `/chaos-inject-network` 触发实验
    3. 使用 `/chaos-monitor` 监控实验
    4. 使用 `/chaos-validate-alerts` 验证告警
    5. 使用 `/chaos-validate-self-heal` 验证自我恢复
    6. 使用 `/chaos-report` 生成报告
  - **验收标准**: 所有步骤都能通过 skills 完成，报告完整

- [ ] 10.3 依赖故障完整流程测试
  - **步骤**:
    1. 使用 `/chaos-check-alerts` 检查覆盖度
    2. 使用 `/chaos-inject-dependency` 触发实验
    3. 使用 `/chaos-monitor` 监控实验
    4. 使用 `/chaos-validate-alerts` 验证告警
    5. 使用 `/chaos-validate-self-heal` 验证自我恢复
    6. 使用 `/chaos-report` 生成报告
  - **验收标准**: 所有步骤都能通过 skills 完成，报告完整

- [ ] 10.4 资源耗尽完整流程测试
  - **步骤**:
    1. 使用 `/chaos-check-alerts` 检查覆盖度
    2. 使用 `/chaos-inject-resource` 触发实验
    3. 使用 `/chaos-monitor` 监控实验
    4. 使用 `/chaos-validate-alerts` 验证告警
    5. 使用 `/chaos-validate-self-heal` 验证自我恢复
    6. 使用 `/chaos-report` 生成报告
  - **验收标准**: 所有步骤都能通过 skills 完成，报告完整

- [ ] 10.5 级联故障完整流程测试
  - **步骤**:
    1. 使用 `/chaos-check-alerts` 检查覆盖度
    2. 使用 `/chaos-inject-cascade` 触发实验
    3. 使用 `/chaos-monitor` 监控实验
    4. 使用 `/chaos-validate-alerts` 验证告警
    5. 使用 `/chaos-validate-self-heal` 验证自我恢复
    6. 使用 `/chaos-report` 生成报告
  - **验收标准**: 所有步骤都能通过 skills 完成，报告完整

## 11. 测试和验证

- [ ] 9.1 在开发/测试环境测试 pod-failure 实验
  - **前置检查**: 运行告警覆盖度检查，确保告警覆盖充分
  - **执行**: 应用 pod-failure 实验
  - **观察**: Pod 重建时间、Service endpoints 更新、错误率 spike、告警触发
  - **验证**: 参考 Pod 故障注入全流程验收标准
  - **自我恢复能力验证**:
    - [ ] Pod 自动重建并在 60s 内 Ready
    - [ ] Service 自动更新 endpoints
    - [ ] 流量自动切换到健康 Pod
    - [ ] 无资源泄漏（连接、文件描述符）
    - [ ] 无需人工干预完全恢复
  - **告警验证**:
    - [ ] PodNotReady 告警在 30s 内触发
    - [ ] 告警标签正确
    - [ ] PodReady 后告警在 60s 内恢复
    - [ ] 无预期外的告警误报
  - **验收标准**:
    - [ ] Pod 在 60s 内恢复 Ready
    - [ ] Service endpoints 在 30s 内更新
    - [ ] 错误率 spike 不超过 10%
    - [ ] 5 分钟内 QPS 恢复到基准的 90% 以上
    - [ ] 无持久化资源泄漏
    - [ ] **自我恢复验收标准**: 全部通过
    - [ ] **告警验收标准**: 全部通过

- [ ] 8.2 在开发/测试环境测试 network-latency 实验
  - **前置检查**: 运行告警覆盖度检查，确保告警覆盖充分
  - **执行**: 应用 network-latency 实验（500ms 延迟）
  - **观察**: P95 延迟、超时次数、重试次数、熔断状态、告警触发
  - **验证**: 参考网络延迟注入全流程验收标准
  - **自我恢复能力验证**:
    - [ ] 延迟移除后应用性能自动恢复
    - [ ] 连接池无泄漏
    - [ ] 无慢恢复现象
    - [ ] 重试机制自动恢复
  - **告警验证**:
    - [ ] HighLatency 告警在 P95 超过阈值后触发
    - [ ] High5xxRate 告警在错误率超过阈值后触发
    - [ ] 延迟恢复后告警及时恢复
    - [ ] 告警标签准确
  - **验收标准**:
    - [ ] P95 延迟 spike 符合注入量 + 处理时间
    - [ ] 超时仅在延迟超过配置阈值时发生
    - [ ] 重试次数符合配置策略
    - [ ] 移除延迟后无"慢恢复"现象
    - [ ] 无级联故障
    - [ ] **自我恢复验收标准**: 全部通过
    - [ ] **告警验收标准**: 全部通过

- [ ] 8.3 在开发/测试环境测试 dependency-failure 实验
  - **前置检查**: 运行告警覆盖度检查，确保告警覆盖充分
  - **执行**: 应用 dependency-failure 实验（如 adservice 不可用）
  - **观察**: 上游错误率、熔断器状态、降级命中、缓存命中率、告警触发
  - **验证**: 参考服务依赖故障注入全流程验收标准
  - **自我恢复能力验证**:
    - [ ] 熔断器自动打开和关闭
    - [ ] 依赖恢复后流量自动恢复
    - [ ] 无惊群效应
    - [ ] 缓存自动预热
  - **告警验证**:
    - [ ] ServiceUnavailable 告警及时触发
    - [ ] DependencyErrorRateHigh 告警准确触发
    - [ ] CircuitBreakerOpen 告警在熔断器打开时触发
    - [ ] 服务恢复后告警及时恢复
  - **验收标准**:
    - [ ] 依赖故障不导致级联故障
    - [ ] 熔断器正确打开和恢复
    - [ ] 降级机制有效，用户体验保持可用
    - [ ] 无重试风暴
    - [ ] 恢复后流量平滑过渡
    - [ ] **自我恢复验收标准**: 全部通过
    - [ ] **告警验收标准**: 全部通过

- [ ] 8.4 验证可观测性集成（指标、链路、日志、告警）
  - **验证 Prometheus**: 指标正常抓取，查询无错误
  - **验证 Grafana**: 大盘正常加载，实验时间轴正确显示，告警面板正确显示
  - **验证 Tempo**: 链路可查询，故障 span 可见
  - **验证 Loki**: 日志正常聚合，错误日志可搜索
  - **验证 AlertManager**: 告警正确触发和恢复
  - **验收标准**:
    - [ ] 所有观察指标可查询
    - [ ] 实验全流程数据完整记录
    - [ ] 大盘准确反映实验影响
    - [ ] 告警数据完整记录

- [ ] 8.5 验证告警验证流程
  - **执行**: 运行混沌实验并生成告警验证报告
  - **观察**: 预期告警和实际告警的对比
  - **验证**: 告警验证报告的准确性和完整性
  - **验收标准**:
    - [ ] 告警验证报告准确反映告警触发情况
    - [ ] 能够识别告警缺失场景
    - [ ] 能够识别告警误报场景
    - [ ] 能够评估告警响应时间
    - [ ] 报告提供可操作的改进建议

- [ ] 8.6 验证自我恢复能力
  - **执行**: 运行混沌实验并移除故障
  - **观察**: 系统自动恢复过程
  - **验证**: 自我恢复能力验证检查清单
  - **验收标准**:
    - [ ] Pod 崩溃后自动重建
    - [ ] 健康检查失败后自动重启
    - [ ] 资源限制触发后自动重建（OOM 后）
    - [ ] 服务无资源泄漏（连接、文件描述符、内存）
    - [ ] 恢复时间符合预期
    - [ ] 无需人工干预完全恢复

- [ ] 8.7 验证告警覆盖度检查流程
  - **执行**: 运行告警覆盖度检查
  - **观察**: 覆盖度报告生成和阻塞机制
  - **验证**: 覆盖度检查的准确性和完整性
  - **验收标准**:
    - [ ] 覆盖度报告准确反映告警覆盖情况
    - [ ] 能够识别缺失的告警规则
    - [ ] 能够计算正确的覆盖率
    - [ ] 覆盖度不足时正确阻塞实验
    - [ ] 报告提供可操作的改进建议

- [ ] 8.8 测试手动实验中止和自动清理
  - **执行**: 运行混沌实验，中途中止
  - **观察**: 实验中止后故障是否移除
  - **验证**: 资源清理情况
  - **验收标准**:
    - [ ] 手动中止后故障立即移除
    - [ ] 实验到期后自动清理
    - [ ] 无残留资源
    - [ ] 系统自动恢复

- [ ] 8.9 验证防护机制（命名空间限制、资源限制）
  - **执行**: 尝试在禁止命名空间创建实验
  - **执行**: 尝试创建超限参数的实验
  - **观察**: 是否被拒绝
  - **验收标准**:
    - [ ] 非 online-boutique 命名空间实验被拒绝
    - [ ] monitoring/kube-system 实验被拒绝
    - [ ] 超限参数被拒绝
    - [ ] 错误消息清晰明确