# 告警验证 skill

验证混沌实验期间告警是否正确触发，生成告警验证报告。

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
- PodNotReady (Critical)
- ServiceUnavailable (Warning)

实际触发的告警:
1. PodNotReady
   - 触发时间: 10:00:05 (故障后 5s)
   - 恢复时间: 10:01:00
   - 持续时长: 55s
   - 响应时间: 5s ✅ (≤30s)
   - 严重级别: Critical ✅
   - 标签: namespace=online-boutique, service=frontend ✅

验证结果:
✅ PodNotReady: 5s 内触发，符合预期
❌ ServiceUnavailable: 未触发 (预期但未触发)

告警响应时间分析:
| 告警名称 | 预期响应时间 | 实际响应时间 | 评价 |
|---------|-------------|-------------|------|
| PodNotReady | ≤30s | 5s | ✅ 优秀 |

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

- [ ] 能正确获取实验信息
- [ ] 能查询实验期间的告警
- [ ] 能准确对比预期和实际告警
- [ ] 能计算告警响应时间
- [ ] 能生成可读的验证报告
- [ ] 能提供改进建议
