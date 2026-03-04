# 网络延迟注入 skill

触发网络延迟注入实验，向指定服务注入网络延迟。

## 核心原则

**告警规则必须代码固化** - 所有告警规则必须存储在代码仓库中（`deploy/monitoring/alerting/`），禁止使用临时 `kubectl apply` 命令创建告警规则。

## 用法

```
/chaos-inject-network [service] [latency] [duration]
```

### 参数

- `service`: 目标服务名称（如 `recommendationservice`）
- `latency`: 可选，延迟量（默认：500ms），格式：数字+ms/s
- `duration`: 可选，实验时长（默认：3m），格式：数字+s/m/h

## kind 环境已知限制

**重要**: 在 kind 本地集群中，NetworkChaos 存在以下限制：

- **源 Pod 注入失败**：对 `recommendationservice`、`adservice` 等源 Pod 注入延迟时，chaos-daemon 会报 `unable to flush ip sets`（ipset 内核模块限制），实验进入 `NotInjected` 状态
- **目标 Pod partition 可用**：使用 `action: partition` + `direction: both` 对**被访问方**（如 `redis-cart`）做网络隔离可以成功注入（已验证）
- **替代验证方法**：对 `cartservice` 测试依赖故障时，指定 `app: redis-cart` 为目标，使用 partition 模式隔离 Redis，可触发 cartservice 错误率上升

如果需要测试延迟注入，建议在真实 Kubernetes 集群（非 kind）中执行，或改用 Pod 故障实验替代。

## 实验 ID 约定

实验 ID 使用手动命名格式：`<type>-<service>-YYYYMMDD-HHMMSS`，例如：`network-latency-recommendationservice-20260301-100000`。无系统自动追踪，在 kubectl label 和报告中一致使用该格式。

## 执行流程

1. 运行告警覆盖度检查
2. 检查目标服务是否存在
3. 检查 kind 环境限制（如适用）
4. 记录基准指标（P95 延迟、错误率）
5. 应用 NetworkChaos 故障
6. 记录实验开始时间
7. 显示实验状态和观察指标

## 输出示例

```
网络延迟注入实验
================
实验 ID: network-latency-redis-cart-20260301-100000
目标服务: redis-cart (partition 模式)
延迟量: N/A (partition 模式)
实验时长: 3m
预期告警: ChaosHighErrorRate, ChaosPodRestart

前置检查:
✅ 告警覆盖度: 100% (允许执行)
⚠️  kind 环境: 源 Pod 延迟注入不可用，使用 target partition 模式

执行步骤:
1. 记录基准指标... ✅
   - P95 延迟: 8ms
   - 错误率: 0%
2. 应用 NetworkChaos 故障... ✅
   kubectl apply -f - <<EOF
   apiVersion: chaos-mesh.org/v1alpha1
   kind: NetworkChaos
   metadata:
     name: network-latency-redis-cart-20260301-100000
     namespace: chaos-mesh
   spec:
     action: partition
     mode: one
     selector:
       namespaces: [online-boutique]
       labelSelectors: {app: redis-cart}
     direction: both
     duration: "3m"
   EOF
3. 网络隔离已注入...

观察指标:
- Pod 状态: redis-cart Running, cartservice 请求失败
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
- [x] 能检测并报告 kind 环境的 ipset 限制（源 Pod 注入失败时明确提示）
- [x] 能使用目标 Pod partition 模式作为替代验证方法（已验证：redis-cart partition 成功 Injected）
- [x] 能记录基准指标
- [x] 能显示实验状态和观察指标
- [x] 能提供下一步操作指引

## 相关文档

- [混沌实验运行手册](../../docs/chaos/runbook.md)
- [故障排除指南](../../docs/chaos/troubleshooting.md)
