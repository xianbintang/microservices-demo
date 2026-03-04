# 中止混沌实验 skill

中止正在运行的混沌实验，立即移除故障。

## 核心原则

**告警规则必须代码固化** - 所有告警规则必须存储在代码仓库中（`deploy/monitoring/alerting/`），禁止使用临时 `kubectl apply` 命令创建告警规则。

## 用法

```
/chaos-abort [experiment-id]
```

### 参数

- `experiment-id`: 可选，指定实验 ID（默认：中止所有运行中的实验）

## 执行流程

1. 获取运行中的实验列表
2. 确认中止操作
3. 删除 Chaos Mesh CRD
4. 等待故障移除
5. 验证资源清理完成
6. 显示中止结果

## 实验 ID 约定

实验 ID 使用手动命名格式：`<type>-<service>-YYYYMMDD-HHMMSS`，与注入时保持一致。

## 输出示例

```
中止混沌实验
============
找到运行中的实验: 1

实验 1: pod-failure-frontend-20260301-100000 (PodChaos)
状态: Running (已运行 90s / 2m)
目标服务: frontend

正在中止...
1. 删除 PodChaos CRD... ✅
   kubectl delete podchaos pod-failure-frontend-20260301-100000 -n chaos-mesh
2. 等待故障移除... ✅
3. 验证资源清理... ✅
   kubectl get podchaos,networkchaos,stresschaos -n chaos-mesh
   → No resources found

中止完成:
- 实验已中止
- 故障已移除
- 资源已清理
- 系统正在恢复

下一步:
- 使用 /chaos-monitor 监控恢复状态
- 使用 /chaos-validate-self-heal 验证自我恢复
- 使用 /chaos-report 生成部分实验报告
```

## 验收标准

- [x] 能正确获取运行中的实验（`kubectl get podchaos,networkchaos,stresschaos -n chaos-mesh`）
- [x] 能成功中止实验（delete CRD，CRD 在 chaos-mesh namespace）
- [x] 能验证资源清理完成（已验证：CRD 删除后 No resources found）
- [x] 能显示中止结果
- [x] 能提供下一步操作指引
