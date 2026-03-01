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

## 执行流程

1. 运行告警覆盖度检查
2. 检查目标服务是否存在
3. 记录基准指标（P95 延迟、错误率）
4. 应用 NetworkDelay 故障
5. 记录实验开始时间
6. 显示实验状态和观察指标

## 输出示例

```
网络延迟注入实验
================
实验 ID: network-latency-20240101-100000
目标服务: recommendationservice
延迟量: 500ms
实验时长: 3m
预期告警: HighLatency, High5xxRate

前置检查:
✅ 告警覆盖度: 87% (允许执行)

执行步骤:
1. 记录基准指标... ✅
   - P95 延迟: 120ms
   - 错误率: 0.1%
2. 应用 NetworkDelay 故障... ✅
3. 延迟已注入，流量正在经过...

观察指标:
- P95 延迟: 监控中 (预期: ~620ms)
- 错误率: 监控中
- 告警触发: 等待中...

下一步:
- 使用 /chaos-monitor 监控实验状态
- 使用 /chaos-validate-alerts 验证告警触发
- 使用 /chaos-report 生成实验报告
- 使用 /chaos-abort 中止实验
```

## 验收标准

- [ ] 能正确执行告警覆盖度检查
- [ ] 能成功应用网络延迟故障
- [ ] 能记录基准指标
- [ ] 能显示实验状态和观察指标
- [ ] 能提供下一步操作指引
