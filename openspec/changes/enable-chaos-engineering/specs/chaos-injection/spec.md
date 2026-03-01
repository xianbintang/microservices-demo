## ADDED Requirements

### Requirement: Fault injection capabilities
系统 SHALL 提供故障注入能力用于测试微服务弹性，包括 Pod 故障、网络中断和资源限制。

#### Scenario: Pod kill injection
- **当** 混沌实验针对特定 Pod 进行终止操作
- **则** 指定的 Pod 被终止，Kubernetes 根据副本数重建它

#### Scenario: Network latency injection
- **当** 混沌实验对服务应用网络延迟
- **则** 该服务的入站/出站流量按配置产生延迟（如 100ms、500ms）

#### Scenario: Packet loss injection
- **当** 混沌实验对网络流量应用丢包
- **则** 按配置的百分比（如 10%、50%）丢弃数据包

#### Scenario: CPU stress injection
- **当** 混沌实验对 Pod 应用 CPU 压力
- **则** 该 Pod 按配置的百分比和时长承受 CPU 负载

#### Scenario: Memory stress injection
- **当** 混沌实验对 Pod 应用内存压力
- **则** 该 Pod 按配置的大小和时长消耗内存

### Requirement: Chaos experiment lifecycle
系统 SHALL 支持混沌实验的完整生命周期，包括创建、执行、监控和恢复。

#### Scenario: Create chaos experiment
- **当** 运维人员创建混沌实验清单
- **则** 混沌控制器验证并应用实验配置

#### Scenario: Execute chaos experiment
- **当** 混沌实验启动
- **则** 对目标资源应用故障注入，持续指定时长

#### Scenario: Monitor chaos experiment
- **当** 混沌实验运行中
- **则** 捕获系统指标和链路以评估影响

#### Scenario: Recover from chaos experiment
- **当** 混沌实验完成或被中止
- **则** 移除注入的故障，受影响资源恢复正常状态