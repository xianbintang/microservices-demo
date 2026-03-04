# 级联故障注入 skill

触发级联故障注入实验，同时注入多个故障。

## 核心原则

**告警规则必须代码固化** - 所有告警规则必须存储在代码仓库中（`deploy/monitoring/alerting/`），禁止使用临时 `kubectl apply` 命令创建告警规则。

## 用法

```
/chaos-inject-cascade [config]
```

### 参数

- `config`: 级联故障配置名称（如 `default`），默认配置见 `deploy/chaos/cascade-failure.yaml`

## 默认配置说明

`default` 配置（`deploy/chaos/cascade-failure.yaml`）包含 3 个同时触发的故障：

1. **adservice** - PodChaos pod-kill（持续 2m）
2. **recommendationservice** - NetworkChaos delay 500ms（持续 3m）
3. **checkoutservice** - StressChaos memory 512MiB（持续 4m）

**kind 环境注意**：NetworkChaos 对 recommendationservice 的延迟注入可能失败（ipset 限制），但 PodChaos 和 StressChaos 均已验证可正常注入。执行时若 NetworkChaos 失败，实验整体仍有效（另两个故障正常运行）。

## 实验 ID 约定

实验 ID 使用手动命名格式：`<type>-<config>-YYYYMMDD-HHMMSS`，例如：`cascade-default-20260301-100000`。无系统自动追踪，在 kubectl label 和报告中一致使用该格式。

## 执行流程

1. 运行告警覆盖度检查
2. 加载配置文件（`deploy/chaos/cascade-failure.yaml`）
3. 记录基准指标
4. 同时应用所有 Chaos CRD
5. 记录实验开始时间
6. 显示实验状态和观察指标

## 预期告警

- ChaosPodNotReady (Critical) - adservice Pod 被 kill 后未就绪
- ChaosServiceDown (Critical) - adservice 无就绪 Pod
- ChaosHighMemoryUsage (Warning) - checkoutservice 内存压力
- ChaosHighLatency (Warning) - 若 NetworkChaos 注入成功

## 输出示例

```
级联故障注入实验
================
实验 ID: cascade-default-20260301-100000
配置: default (deploy/chaos/cascade-failure.yaml)
故障数量: 3
实验时长: 最长 4m
预期告警: ChaosPodNotReady, ChaosServiceDown, ChaosHighMemoryUsage

前置检查:
✅ 告警覆盖度: 100% (允许执行)
⚠️  kind 环境: NetworkChaos (故障2) 可能因 ipset 限制失败，不影响其他故障

执行步骤:
1. 记录基准指标... ✅
2. 应用级联故障... ✅
   kubectl apply -f deploy/chaos/cascade-failure.yaml
   kubectl get podchaos,networkchaos,stresschaos -n chaos-mesh
3. 故障已注入，开始观察...

各故障状态:
- cascade-pod-failure-adservice: Injected ✅ (adservice Pod 被 kill)
- cascade-network-latency-recommendation: NotInjected ⚠️ (kind ipset 限制)
- cascade-memory-stress-checkout: Injected ✅ (checkoutservice 内存压力)

观察指标:
- adservice Pod 状态: 监控中
- checkoutservice 内存: 监控中
- 错误率: 监控中
- 告警触发: 等待中...

下一步:
- 使用 /chaos-monitor 监控实验状态
- 使用 /chaos-validate-alerts 验证告警触发
- 使用 /chaos-validate-self-heal 验证自我恢复
- 使用 /chaos-report 生成实验报告
- 使用 /chaos-abort 中止实验
```

## 验收标准

- [x] 能正确执行告警覆盖度检查
- [x] 能读取并应用默认配置文件（`deploy/chaos/cascade-failure.yaml`）
- [x] 能同时创建多个 Chaos CRD（已验证：PodChaos + StressChaos 均 Injected）
- [x] 能识别并报告 kind 环境下 NetworkChaos 失败的情况
- [x] 能记录基准指标
- [x] 能显示实验状态和观察指标
- [x] 能提供下一步操作指引

## 相关文档

- [混沌实验运行手册](../../docs/chaos/runbook.md)
- [故障排除指南](../../docs/chaos/troubleshooting.md)
