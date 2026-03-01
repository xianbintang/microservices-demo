---
description: 触发网络延迟注入实验，向指定服务注入网络延迟
---

# 网络延迟注入

## 功能

触发网络延迟注入实验，向指定服务注入网络延迟，验证高延迟下的超时处理、重试逻辑和用户体验降级。

## 用法

```
/chaos-inject-network [service] [latency] [duration]
```

## 参数

- `service`: 目标服务名称（如 `recommendationservice`）
- `latency`: 可选，延迟量（默认：500ms），格式：数字+ms/s
- `duration`: 可选，实验时长（默认：3m），格式：数字+s/m/h

## 预期告警

- HighLatency (Warning)
- High5xxRate (Critical)

## 验收标准

- P95 延迟 spike 符合注入量 + 处理时间
- 超时仅在延迟超过配置阈值时发生
- 重试次数符合配置策略
- 移除延迟后无"慢恢复"现象
- 无级联故障

## 下一步

- `/chaos-monitor` - 监控实验状态
- `/chaos-validate-alerts` - 验证告警触发
- `/chaos-report` - 生成实验报告
- `/chaos-abort` - 中止实验