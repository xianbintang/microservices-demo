# 资源耗尽注入 skill

触发资源耗尽注入实验，对目标 Pod 应用 CPU 或内存压力。

## 核心原则

**告警规则必须代码固化** - 所有告警规则必须存储在代码仓库中（`deploy/monitoring/alerting/`），禁止使用临时 `kubectl apply` 命令创建告警规则。

## 用法

```
/chaos-inject-resource [service] [type] [value] [duration]
```

### 参数

- `service`: 目标服务名称（如 `checkoutservice`）
- `type`: 资源类型（cpu 或 memory）
- `value`: 压力值（如 80 表示 80%）
- `duration`: 可选，实验时长（默认：5m），格式：数字+s/m/h

## 前置要求

StressChaos 通过 chaos-daemon 的 gRPC 接口注入，需要：
- `SECURITY_MODE=true` 在 chaos-controller-manager deployment 中
- chaos-daemon mTLS 证书配置正确

如果遇到 `error reading server preface: EOF`，请检查 chaos-controller-manager 的环境变量是否包含 `SECURITY_MODE`，详见故障排除指南。

## 实验 ID 约定

实验 ID 使用手动命名格式：`<type>-<service>-YYYYMMDD-HHMMSS`，例如：`stress-cpu-checkoutservice-20260301-100000`。无系统自动追踪，在 kubectl label 和报告中一致使用该格式。

## 执行流程

1. 运行告警覆盖度检查
2. 检查目标服务是否存在
3. 记录基准指标（CPU 使用率、内存使用率）
4. 应用 StressChaos 故障
5. 记录实验开始时间
6. 显示实验状态和观察指标

## 预期告警

- ChaosHighCPUUsage (Warning) - CPU 核心数 > 0.5 cores 持续 1m
- ChaosHighMemoryUsage (Warning) - 内存 > 400MiB 持续 1m
- ChaosOOMKilled (Critical) - 容器被 OOM 终止
- ChaosCPUThrottling (Warning) - CPU 节流 > 50% 持续 1m

## 输出示例

```
资源耗尽注入实验
================
实验 ID: stress-cpu-checkoutservice-20260301-100000
目标服务: checkoutservice
资源类型: CPU
压力值: 80%
实验时长: 5m
预期告警: ChaosHighCPUUsage, ChaosCPUThrottling

前置检查:
✅ 告警覆盖度: 100% (允许执行)

执行步骤:
1. 记录基准指标... ✅
   - CPU 使用: 0.001-0.01 cores
   - 内存使用: ~20MiB
2. 应用 StressChaos 故障... ✅
   kubectl apply -f - <<EOF
   apiVersion: chaos-mesh.org/v1alpha1
   kind: StressChaos
   metadata:
     name: stress-cpu-checkoutservice-20260301-100000
     namespace: chaos-mesh
   spec:
     mode: one
     selector:
       namespaces: [online-boutique]
       labelSelectors: {app: checkoutservice}
     stressors:
       cpu:
         workers: 2
         load: 80
     duration: "5m"
   EOF
   kubectl get stresschaos -n chaos-mesh  # 确认状态为 Injected
3. CPU 压力已注入 (checkoutservice CPU 升至 ~0.1 cores)...

观察指标:
- CPU 使用率: 监控中 (预期: 0.1+ cores)
- 内存使用率: 监控中
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
- [x] 能成功应用 StressChaos 故障（已验证：checkoutservice CPU 从 0.001 升至 0.103 cores）
- [x] 能记录基准指标
- [x] 能显示实验状态和观察指标
- [x] 能提供下一步操作指引

## 相关文档

- [混沌实验运行手册](../../docs/chaos/runbook.md)
- [故障排除指南](../../docs/chaos/troubleshooting.md)
