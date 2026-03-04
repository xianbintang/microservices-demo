# Pod 故障注入 skill

触发 Pod 故障注入实验，终止指定服务或随机 Pod。

## 核心原则

**告警规则必须代码固化** - 所有告警规则必须存储在代码仓库中（`deploy/monitoring/alerting/`），禁止使用临时 `kubectl apply` 命令创建告警规则。

## 用法

```
/chaos-inject-pod [service] [duration]
```

### 参数

- `service`: 可选，目标服务名称（如 `frontend`、`adservice`），不指定则随机选择
- `duration`: 可选，实验时长（默认：2m），格式：数字+s/m/h

## 执行流程

1. 运行告警覆盖度检查
2. 选择目标 Pod（指定服务或随机）
3. 记录基准指标
4. 应用 PodKill 故障
5. 记录实验开始时间
6. 显示实验状态和观察指标

## 实验 ID 约定

实验 ID 使用手动命名格式：`<type>-<service>-YYYYMMDD-HHMMSS`，例如：`pod-failure-frontend-20260301-100000`。无系统自动追踪，在 kubectl label 和报告中一致使用该格式。

## 输出示例

```
Pod 故障注入实验
================
实验 ID: pod-failure-frontend-20260301-100000
目标服务: frontend (随机选择)
目标 Pod: frontend-7d9f5c6f8d-x2k4p
实验时长: 2m
预期告警: ChaosPodNotReady, ChaosServiceDown

前置检查:
✅ 告警覆盖度: 100% (允许执行)

执行步骤:
1. 记录基准指标... ✅
   kubectl apply -f - <<EOF
   apiVersion: chaos-mesh.org/v1alpha1
   kind: PodChaos
   metadata:
     name: pod-failure-frontend-20260301-100000
     namespace: chaos-mesh
   spec:
     action: pod-kill
     mode: one
     selector:
       namespaces: [online-boutique]
       labelSelectors: {app: frontend}
     duration: "2m"
   EOF
2. 应用 PodKill 故障... ✅
   kubectl get podchaos -n chaos-mesh  # 确认 CRD 已创建
3. Pod 正在重建 (约 6-30s)...

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

## 验收标准

- [x] 能正确执行告警覆盖度检查
- [x] 能正确选择目标 Pod
- [x] 能成功应用 PodKill 故障（已验证：frontend Pod 在 6s 内被重建）
- [x] 能记录基准指标
- [x] 能显示实验状态和观察指标
- [x] 能提供下一步操作指引

## 相关文档

- [混沌实验运行手册](../../docs/chaos/runbook.md)
- [故障排除指南](../../docs/chaos/troubleshooting.md)
