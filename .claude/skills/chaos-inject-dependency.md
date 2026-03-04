# 依赖故障注入 skill

触发服务依赖故障注入实验，模拟依赖服务不可用。

## 核心原则

**告警规则必须代码固化** - 所有告警规则必须存储在代码仓库中（`deploy/monitoring/alerting/`），禁止使用临时 `kubectl apply` 命令创建告警规则。

## 用法

```
/chaos-inject-dependency [service] [dependency] [duration]
```

### 参数

- `service`: 上游服务名称（如 `cartservice`）
- `dependency`: 依赖服务名称（如 `redis`）
- `duration`: 可选，实验时长（默认：3m），格式：数字+s/m/h

## 实现说明

依赖故障通过 NetworkChaos partition 模式实现：隔离依赖方（而非上游服务）的网络，使上游服务无法访问依赖。

**重要**: Online Boutique 未实现熔断器（Circuit Breaker），`CircuitBreakerOpen` 告警在实际中不会触发。实际可观察到的告警为：
- `ChaosHighErrorRate` (Critical) - 上游服务错误率 > 10%
- `ChaosPodRestart` (Warning) - 如依赖不可用导致 Pod 崩溃重启

**Redis 位置**: `redis-cart` 运行在 `online-boutique` namespace，与业务服务同 namespace，selector 使用 `app: redis-cart`。

## 实验 ID 约定

实验 ID 使用手动命名格式：`<type>-<service>-YYYYMMDD-HHMMSS`，例如：`dependency-cartservice-redis-20260301-100000`。无系统自动追踪，在 kubectl label 和报告中一致使用该格式。

## 执行流程

1. 运行告警覆盖度检查
2. 确认依赖服务位置和标签
3. 记录基准指标（上游错误率、依赖响应时间）
4. 应用 NetworkChaos partition 故障（目标为依赖方）
5. 记录实验开始时间
6. 显示实验状态和观察指标

## 预期告警

- ChaosHighErrorRate (Critical) - 上游服务错误率 > 10%
- ChaosPodRestart (Warning) - 依赖不可用导致 Pod 重启

## 输出示例

```
依赖故障注入实验
================
实验 ID: dependency-cartservice-redis-20260301-100000
上游服务: cartservice
依赖服务: redis-cart (namespace: online-boutique)
实验时长: 3m
预期告警: ChaosHighErrorRate, ChaosPodRestart

前置检查:
✅ 告警覆盖度: 100% (允许执行)
✅ redis-cart 在 online-boutique namespace 运行正常

执行步骤:
1. 记录基准指标... ✅
   - 错误率: 0%
   - cartservice 请求: 正常
2. 应用 NetworkChaos partition... ✅
   kubectl apply -f - <<EOF
   apiVersion: chaos-mesh.org/v1alpha1
   kind: NetworkChaos
   metadata:
     name: dependency-cartservice-redis-20260301-100000
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
   kubectl get networkchaos -n chaos-mesh  # 确认状态为 Injected
3. redis-cart 网络已隔离，cartservice 无法访问 Redis...

观察指标:
- cartservice 错误率: 监控中 (预期: 升高)
- Pod 状态: 监控中
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
- [x] 能成功应用 NetworkChaos partition 故障（已验证：redis-cart partition 成功 Injected）
- [x] 能记录基准指标
- [x] 能显示实验状态和观察指标
- [x] 能提供下一步操作指引

## 相关文档

- [混沌实验运行手册](../../docs/chaos/runbook.md)
- [故障排除指南](../../docs/chaos/troubleshooting.md)
