## 为什么

Online Boutique 微服务演示配有完整的可观测性栈，但缺乏系统化的弹性测试。混沌工程将有助于验证故障条件下的系统弹性，在生产事故发生前发现薄弱环节，并建立对微服务架构的信心。

## 变更内容

- 在 `monitoring` 命名空间部署 Chaos Mesh（或 Chaos Monkey）以提供故障注入能力
- 添加常见故障场景的混沌实验：
  - Pod 故障和重启
  - 网络延迟和丢包
  - 服务依赖故障（如 `adservice`、`recommendationservice`）
  - 资源耗尽（CPU、内存）
- 将混沌实验与可观测性栈集成（Grafana 大盘、告警）
- 记录混沌实验工作流程和运行手册
- 添加混沌实验防护机制，防止破坏性测试

## 能力

### 新增能力

- `chaos-injection`: 用于测试弹性的故障注入能力
- `chaos-experiments`: 针对Online Boutique的预定义混沌实验场景
- `chaos-guardrails`: 混沌实验的安全机制和防护
- `chaos-integration`: 与可观测性栈集成以监控混沌运行

### 修改的能力

- 无（无现有规格需求变更）

## 影响

- **基础设施**: 通过 Helm chart 在 `monitoring` 命名空间添加 Chaos Mesh 部署
- **可观测性**: 用于混沌实验结果和实验期间系统健康的新 Grafana 大盘
- **告警**: 调整 AlertManager 规则以减少计划内混沌实验期间的告警噪音
- **开发**: 用于 Chaos Mesh 配置的新 Helm values 文件
- **文档**: 混沌实验运行手册和故障排除指南
- **依赖**: Chaos Mesh Helm chart