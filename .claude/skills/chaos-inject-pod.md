---
description: 触发 Pod 故障注入实验，终止指定服务或随机 Pod
---

# Pod 故障注入

## 功能

触发 Pod 故障注入实验，终止指定服务或随机 Pod，验证系统自愈能力和告警触发。

## 用法

```
/chaos-inject-pod [service] [duration]
```

## 参数

- `service`: 可选，目标服务名称（如 `frontend`、`adservice`），不指定则随机选择
- `duration`: 可选，实验时长（默认：2m），格式：数字+s/m/h

## 执行步骤

1. **前置检查**
   - 运行告警覆盖度检查
   - 验证目标服务存在
   - 检查当前是否有运行中的实验

2. **记录基准指标**
   - Pod 状态和 restart_count
   - Service endpoints
   - 服务 QPS
   - 错误率
   - P95/P99 延迟

3. **应用故障注入**
   - 选择目标 Pod
   - 应用 PodKill 故障
   - 记录实验开始时间

4. **观察阶段**
   - 监控 Pod 重建过程
   - 监控 Service endpoints 更新
   - 监控错误率 spike
   - 监控告警触发

## 预期告警

- PodNotReady (Critical)
- ServiceUnavailable (Warning)

## 验收标准

- Pod 在 60s 内恢复 Ready
- Service endpoints 在 30s 内更新
- 错误率 spike 不超过 10%
- 5 分钟内 QPS 恢复到基准的 90% 以上
- 无持久化资源泄漏

## 下一步操作

- `/chaos-monitor` - 监控实验状态
- `/chaos-validate-alerts` - 验证告警触发
- `/chaos-validate-self-heal` - 验证自我恢复
- `/chaos-report` - 生成实验报告
- `/chaos-abort` - 中止实验

## 实现说明

本 skill 执行以下操作：
1. 调用 `/chaos-check-alerts` 进行前置检查
2. 创建实验 ID：`pod-failure-YYYYMMDD-HHMMSS`
3. 使用 `kubectl apply -f deploy/chaos/pod-failure.yaml` 应用故障
4. 输出实验状态和观察指标

## 输出示例

```
Pod 故障注入实验
================
实验 ID: pod-failure-20240101-100000
目标服务: frontend (随机选择)
目标 Pod: frontend-7d9f5c6f8d-x2k4p
实验时长: 2m
预期告警: PodNotReady, ServiceUnavailable

前置检查:
✅ 告警覆盖度: 87% (允许执行)

执行步骤:
1. 记录基准指标... ✅
2. 应用 PodKill 故障... ✅
3. Pod 正在重建...

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