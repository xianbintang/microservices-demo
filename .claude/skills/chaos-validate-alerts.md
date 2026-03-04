# 告警验证 skill

验证混沌实验期间告警是否正确触发，生成告警验证报告。

## 核心原则

**告警规则必须代码固化** - 所有告警规则必须存储在代码仓库中（`deploy/monitoring/alerting/`），禁止使用临时 `kubectl apply` 命令创建告警规则。告警验证报告中的改进建议应明确指向需要修改的代码文件路径。

## 用法

```
/chaos-validate-alerts [experiment-id]
```

### 参数

- `experiment-id`: 可选，指定实验 ID（默认：验证最近完成的实验）

## 输出示例

```
告警验证报告
============
实验 ID: pod-failure-20240101-100000
实验类型: Pod 故障
目标服务: frontend

预期告警:
- ChaosPodNotReady (Critical)
- ChaosServiceDown (Critical)

实际触发的告警:
1. ChaosPodNotReady
   - 触发时间: 10:00:05 (故障后 5s)
   - 恢复时间: 10:01:00
   - 持续时长: 55s
   - 响应时间: 5s ✅ (≤30s)
   - 严重级别: Critical ✅
   - 标签: namespace=online-boutique, pod=frontend-xxx ✅

验证结果:
✅ ChaosPodNotReady: 5s 内触发，符合预期
❌ ChaosServiceDown: 未触发（单副本快速重建，不满足"无就绪 Pod"条件）

告警响应时间分析:
| 告警名称 | 预期响应时间 | 实际响应时间 | 评价 |
|---------|-------------|-------------|------|
| ChaosPodNotReady | ≤30s | 5s | ✅ 优秀 |

覆盖率: 50% (1/2) ⚠️

问题识别:
❌ ServiceUnavailable 告警未触发，可能是:
   - 告警规则缺失
   - 告警阈值不合理
   - 服务未完全不可用

改进建议:
1. 检查 ServiceUnavailable 告警规则是否存在
2. 考虑调整告警阈值（如可用副本数 < 2 时触发）
3. 或从预期告警列表中移除（如果服务有多副本）

整体评价: 部分 ⚠️
```

## 验收标准

- [x] 能正确获取实验信息
- [x] 能查询实验期间的告警（通过 Alertmanager API 查询 Chaos* 标签告警）
- [x] 能准确对比预期和实际告警（已验证：ChaosPodNotReady 触发，ChaosServiceDown 未触发）
- [x] 能计算告警响应时间
- [x] 能生成可读的验证报告
- [x] 能提供改进建议（指向代码路径 deploy/monitoring/alerting/）
