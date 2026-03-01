## 1. Chaos Mesh 部署设置

- [ ] 1.1 将 Chaos Mesh Helm 仓库添加到部署脚本
  - 编辑 `Makefile` 或部署脚本，添加 Chaos Mesh repo
  - 使用官方 Helm repo: `https://charts.chaos-mesh.org`
  - 验证 repo 可访问

- [ ] 1.2 创建 `deploy/monitoring/chaos-mesh-values.yaml` 并配置设置
  - 配置 `imagePullSecrets`（如需要）
  - 设置 `clusterScoped: false`（可选，限制在特定命名空间）
  - 配置控制器副本数为 2（高可用）
  - 配置 webhook 副本数为 2
  - 启用 Web UI（dashboard）

- [ ] 1.3 为 Chaos Mesh 镜像配置 `imagePullSecrets`（如需要）
  - 在 values.yaml 中配置 `imagePullSecrets`
  - 验证镜像可拉取
  - 如使用私有镜像，提前准备好 secret

- [ ] 1.4 使用 `helm upgrade --install` 将 Chaos Mesh 部署到 monitoring 命名空间
  - 执行 helm install 命令
  - 验证所有 Pod 正常启动
  - 验证 CRD 已安装（`kubectl get crd | grep chaos`）

- [ ] 1.5 验证 Chaos Mesh 控制器和 webhook Pod 健康状态
  - 检查 `chaos-controller-manager` Pod Ready
  - 检查 `chaos-daemon` Pod 在每个节点运行
  - 检查 `chaos-dashboard` Pod Ready（如启用）
  - 验证 webhook 正常工作（创建测试 CRD）

## 2. Chaos Mesh 配置

- [ ] 2.1 配置 Chaos Mesh 命名空间白名单（仅 online-boutique）
  - 在 values.yaml 或 ConfigMap 中配置 `namespace: online-boutique`
  - 验证其他命名空间的实验被拒绝
  - 测试：尝试在 monitoring 命名空间创建实验，应被拒绝

- [ ] 2.2 配置 Chaos Mesh 资源黑名单（monitoring、kube-system）
  - 在 admission webhook 中配置资源黑名单
  - 防止对监控组件注入故障
  - 防止对 kube-system 注入故障
  - 测试：尝试对 Prometheus Pod 创建实验，应被拒绝

- [ ] 2.3 为故障注入设置安全默认限制（最大时长、强度）
  - 设置 `duration` 最大值（如 10 分钟）
  - 设置网络延迟最大值（如 2000ms）
  - 设置 CPU 压力最大值（如 90%）
  - 设置内存压力最大值（如 80%）
  - 验证超过限制的配置被拒绝

- [ ] 2.4 配置准入 Webhook 进行实验验证
  - 启用 validation webhook
  - 配置验证规则（命名空间、资源、参数范围）
  - 测试验证逻辑

- [ ] 2.5 验证 Chaos Mesh CRD 已安装且功能正常
  - 列出所有 CRD：`PodChaos`, `NetworkChaos`, `StressChaos`, `IOChaos`, `KernelChaos`, `TimeChaos`, `HTTPChaos`, `PhysicalMachineChaos`
  - 创建测试实验验证功能
  - 验证实验可以正常创建和删除

## 3. 预定义混沌实验

- [ ] 3.1 创建 pod-failure 实验模板（deploy/chaos/pod-failure.yaml）
  - 配置 `PodChaos` 资源
  - 设置 `action: pod-kill`
  - 配置目标命名空间: `online-boutique`
  - 配置目标 selector（可指定服务或随机）
  - 设置 `duration: 2m`
  - 添加实验标签和注解（用于可观测性关联）
  - 添加 `mode: one`（每次终止一个 Pod）或 `mode: all`（终止所有 Pod）

- [ ] 3.2 创建 network-latency 实验模板（deploy/chaos/network-latency.yaml）
  - 配置 `NetworkChaos` 资源
  - 设置 `action: delay`
  - 配置 `delay.latency: 500ms`, `delay.jitter: 50ms`
  - 配置 `direction: to` 或 `both`
  - 配置目标服务（如 recommendationservice）
  - 可选：添加 `loss: 5`（5% 丢包）
  - 添加实验标签和注解

- [ ] 3.3 创建 dependency-failure 实验模板（deploy/chaos/dependency-failure.yaml）
  - 配置 `PodNetworkChaos` 或 `HTTPChaos`
  - 选择依赖服务（如 adservice）
  - 配置网络隔离（`action: partition`）或 HTTP 500
  - 设置 `duration: 3m`
  - 配置上游服务观察点（如 frontend）
  - 添加实验标签和注解

- [ ] 3.4 创建 resource-exhaustion 实验模板（deploy/chaos/resource-exhaustion.yaml）
  - 配置 `StressChaos` 资源
  - 配置 CPU 压力：`stressors.cpu.workers: 2`, `stressors.cpu.load: 90`
  - 或配置内存压力：`stressors.memory.size: 80%`
  - 配置目标 Pod
  - 设置 `duration: 5m`
  - 添加实验标签和注解

- [ ] 3.5 创建 cascade-failure 实验模板（deploy/chaos/cascade-failure.yaml）
  - 创建多个 Chaos 资源在单个文件中
  - 组合多个故障（如 PodKill + NetworkDelay + CPUStress）
  - 按顺序或同时执行
  - 设置各自的 `duration`
  - 添加实验标签和注解

## 4. 可观测性集成

- [ ] 4.1 配置 Prometheus 抓取 Chaos Mesh 控制器指标
  - 添加 Chaos Mesh controller 到 Prometheus scrape config
  - 配置 scrape interval: 15s
  - 配置 metrics path: `/metrics`
  - 验证指标可查询（`chaos_mesh_controller_*`）

- [ ] 4.2 更新 kube-prometheus-stack-values.yaml 添加 Chaos Mesh 抓取配置
  - 在 `additionalScrapeConfigs` 中添加 Chaos Mesh
  - 配置 ServiceMonitor 或 PodSelector
  - 验证 Prometheus target 状态

- [ ] 4.3 创建混沌实验监控的 Grafana 大盘
  - 设计大盘布局（Pod 状态、错误率、延迟、链路、日志）
  - 添加实验时间轴（标注混沌实验的开始和结束）
  - 添加以下面板：
    - Pod 状态（Running/Ready/Pending/Failed）
    - 服务 QPS（对比基线和实验期间）
    - 错误率（5xx、4xx）
    - P50/P95/P99 延迟
    - 链路查询（Tempo）
    - 日志搜索（Loki）
    - 实验状态（Chaos Mesh 指标）
  - 添加变量选择器（命名空间、服务、实验类型）
  - 导出大盘 JSON

- [ ] 4.4 将混沌大盘添加到 Grafana 大盘 configmap
  - 编辑 `deploy/monitoring/dashboards/grafana-dashboards-configmap.yaml`
  - 添加新的 dashboard JSON
  - 验证 Grafana sidecar 重载大盘

- [ ] 4.5 配置混沌实验标签和注解用于可观测性关联
  - 在实验 YAML 中添加标准标签：
    - `chaos.mes.org/type: pod-failure`
    - `chaos.mes.org/namespace: online-boutique`
    - `chaos.mes.org/target-service: <service-name>`
  - 添加注解：
    - `chaos.mes.org/description: "Pod failure experiment"`
    - `chaos.mes.org/observability: "enable"`
  - 配置 Prometheus relabeling 使用这些标签

## 5. 告警管理

- [ ] 5.1 为混沌实验创建 AlertManager 抑制规则
  - 在 AlertManager 配置中添加 `inhibit_rules`
  - 配置规则：当 `chaos: "enabled"` 标签存在时抑制非关键告警
  - 配置源匹配器：`alertname=~"HighLatency|ErrorRateHigh"`
  - 配置目标匹配器：`chaos="enabled"`

- [ ] 5.2 配置计划内混沌期间的非关键告警抑制
  - 列出非关键告警（HighLatency, ErrorRateSpike 等）
  - 配置抑制持续时间
  - 配置告警分组

- [ ] 5.3 确保关键告警（服务宕机）绕过抑制
  - 列出关键告警（ServiceDown, PodNotReady 等）
  - 配置例外规则：即使 `chaos: "enabled"` 仍然告警
  - 验证关键告警能正常触发

- [ ] 5.4 使用混沌实验标签更新 AlertManager 配置
  - 在实验 YAML 中添加 `chaos: "enabled"` 标签到受影响的 Pod
  - 配置 AlertManager 读取此标签
  - 测试抑制规则

## 6. 文档

- [ ] 6.1 创建混沌实验运行手册（docs/chaos/runbook.md）
  - 文档结构：
    - 实验概述
    - 前置条件
    - 执行步骤
    - 观察指标（参考设计文档）
    - 验证点（参考设计文档）
    - 故障排除
    - 回滚步骤
  - 为每种实验类型创建独立章节

- [ ] 6.2 记录每种实验类型及其预期行为
  - Pod 故障：Pod 终止 → Kubernetes 重建 → 服务恢复
  - 网络延迟：延迟注入 → 超时/重试/熔断 → 移除延迟 → 恢复
  - 依赖故障：服务不可用 → 降级/熔断 → 恢复服务 → 流量恢复
  - 资源耗尽：CPU/内存压力 → 节流/OOM → 移除压力 → 恢复
  - 级联故障：多个故障 → 隔离/熔断 → 移除故障 → 恢复

- [ ] 6.3 创建混沌实验故障排除指南
  - 常见问题和解决方案：
    - 实验被拒绝（命名空间/资源黑名单）
    - Pod 无法恢复（资源不足、镜像拉取失败）
    - 告警不抑制（标签配置错误）
    - 观察数据缺失（Prometheus 抓取失败、Grafana 大盘未更新）
    - 实验无法中止（CRD 删除、资源清理）

- [ ] 6.4 记录 Chaos Mesh CLI 和 Web UI 使用方法
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

- [ ] 6.5 将混沌实验工作流程添加到项目 README
  - 添加 Chaos Engineering 章节
  - 链接到运行手册和故障排除指南
  - 说明实验目的和最佳实践

## 7. 测试和验证

- [ ] 7.1 在开发/测试环境测试 pod-failure 实验
  - **执行**: 应用 pod-failure 实验
  - **观察**: Pod 重建时间、Service endpoints 更新、错误率 spike
  - **验证**: 参考 Pod 故障注入全流程验收标准
  - **验收标准**:
    - [ ] Pod 在 60s 内恢复 Ready
    - [ ] Service endpoints 在 30s 内更新
    - [ ] 错误率 spike 不超过 10%
    - [ ] 5 分钟内 QPS 恢复到基准的 90% 以上
    - [ ] 无持久化资源泄漏

- [ ] 7.2 在开发/测试环境测试 network-latency 实验
  - **执行**: 应用 network-latency 实验（500ms 延迟）
  - **观察**: P95 延迟、超时次数、重试次数、熔断状态
  - **验证**: 参考网络延迟注入全流程验收标准
  - **验收标准**:
    - [ ] P95 延迟 spike 符合注入量 + 处理时间
    - [ ] 超时仅在延迟超过配置阈值时发生
    - [ ] 重试次数符合配置策略
    - [ ] 移除延迟后无"慢恢复"现象
    - [ ] 无级联故障

- [ ] 7.3 在开发/测试环境测试 dependency-failure 实验
  - **执行**: 应用 dependency-failure 实验（如 adservice 不可用）
  - **观察**: 上游错误率、熔断器状态、降级命中、缓存命中率
  - **验证**: 参考服务依赖故障注入全流程验收标准
  - **验收标准**:
    - [ ] 依赖故障不导致级联故障
    - [ ] 熔断器正确打开和恢复
    - [ ] 降级机制有效，用户体验保持可用
    - [ ] 无重试风暴
    - [ ] 恢复后流量平滑过渡

- [ ] 7.4 验证可观测性集成（指标、链路、日志）
  - **验证 Prometheus**: 指标正常抓取，查询无错误
  - **验证 Grafana**: 大盘正常加载，实验时间轴正确显示
  - **验证 Tempo**: 链路可查询，故障 span 可见
  - **验证 Loki**: 日志正常聚合，错误日志可搜索
  - **验收标准**:
    - [ ] 所有观察指标可查询
    - [ ] 实验全流程数据完整记录
    - [ ] 大盘准确反映实验影响

- [ ] 7.5 验证计划内实验期间的告警抑制
  - **执行**: 运行混沌实验并触发高延迟
  - **观察**: AlertManager 是否抑制非关键告警
  - **验证**: 关键告警仍然触发
  - **验收标准**:
    - [ ] 非关键告警被正确抑制
    - [ ] 关键告警绕过抑制
    - [ ] 移除 chaos 标签后告警恢复正常

- [ ] 7.6 测试手动实验中止和自动清理
  - **执行**: 运行混沌实验，中途中止
  - **观察**: 实验中止后故障是否移除
  - **验证**: 资源清理情况
  - **验收标准**:
    - [ ] 手动中止后故障立即移除
    - [ ] 实验到期后自动清理
    - [ ] 无残留资源
    - [ ] 系统自动恢复

- [ ] 7.7 验证防护机制（命名空间限制、资源限制）
  - **执行**: 尝试在禁止命名空间创建实验
  - **执行**: 尝试创建超限参数的实验
  - **观察**: 是否被拒绝
  - **验收标准**:
    - [ ] 非 online-boutique 命名空间实验被拒绝
    - [ ] monitoring/kube-system 实验被拒绝
    - [ ] 超限参数被拒绝
    - [ ] 错误消息清晰明确