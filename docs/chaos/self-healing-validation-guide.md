# 自我恢复能力验证指南

## 自我恢复能力的定义和重要性

自我恢复能力是指系统在故障发生后自动恢复正常功能的能力。良好的自我恢复能力可以：

1. **减少人工干预**: 系统自动处理故障，减少运维工作量
2. **提高系统可用性**: 快速恢复服务，减少停机时间
3. **增强系统弹性**: 提高系统对故障的容错能力
4. **防止级联故障**: 及时隔离和恢复，防止故障扩散

## Kubernetes 自我恢复机制

| 机制 | 触发条件 | 恢复行为 | 验证指标 |
|------|---------|---------|---------|
| Pod 自动重启 | Pod 崩溃或被终止 | Deployment/StatefulSet 自动重建 Pod | restart_count, pod_age |
| 健康检查 | liveness probe 失败 | 重启 Pod | liveness_probe_failures |
| 就绪检查 | readiness probe 失败 | 从 Service endpoints 移除 Pod | ready_replicas, available_replicas |
| 资源限制 | OOM 或 CPU 节流 | OOM Kill 或性能降级 | oom_killed, cpu_throttling |
| 节点故障 | Node NotReady | Pod 调度到其他节点 | node_ready, pod_node |

## 自我恢复能力验证方法

### 1. 故障注入前（Pre-Chaos）

记录当前状态作为基线：

```bash
# 记录 Pod 状态
kubectl get pods -n online-boutique

# 记录 Service endpoints
kubectl get endpoints -n online-boutique

# 记录活跃连接数
# 需要应用暴露连接指标

# 记录资源使用
kubectl top pods -n online-boutique
```

### 2. 故障注入中（During Chaos）

监控系统如何应对故障：

```bash
# 监控 Pod 状态变化
kubectl get pods -n online-boutique -w

# 监控 Service endpoints 更新
kubectl get endpoints -n online-boutique -w

# 监控资源使用变化
kubectl top pods -n online-boutique --watch
```

### 3. 故障移除后（Post-Chaos）

验证系统自动恢复：

```bash
# 验证 Pod 自动恢复 Ready
kubectl get pods -n online-boutique

# 验证 Service endpoints 更新
kubectl get endpoints -n online-boutique

# 检测资源泄漏
# 需要应用暴露资源泄漏指标
```

### 4. 分析阶段（Analysis）

计算恢复时间并评估：

```bash
# 计算恢复时间
# 恢复时间 = 故障移除时间 - 系统恢复时间

# 检查资源泄漏
# 连接泄漏、内存泄漏等
```

## 验证指标

| 指标类型 | 具体指标 | 验收标准 | 工具 |
|---------|---------|---------|------|
| Pod 恢复时间 | Pod 终止到 Ready 的时间 | ≤ 60s | Prometheus/K8s |
| Service 更新时间 | Pod Ready 到 endpoints 更新 | ≤ 30s | Prometheus/K8s |
| 连接重建时间 | 连接中断到重建成功 | ≤ 30s | Prometheus/Tempo |
| 资源泄漏 | 连接泄漏、内存泄漏 | 0 | Prometheus |
| 重启成功率 | 重启后恢复 Ready 的比例 | 100% | Prometheus |
| 资源使用恢复 | CPU/Memory 使用率恢复正常时间 | ≤ 5min | Prometheus |

## 验收标准

每个混沌实验都应通过以下自我恢复验收标准：

- [ ] Pod 在预期时间内自动恢复 Ready
- [ ] Service endpoints 在预期时间内更新
- [ ] 连接自动重建，无连接泄漏
- [ ] 资源使用在预期时间内恢复正常
- [ ] 无资源泄漏（连接、文件描述符、内存）
- [ ] 无需人工干预完全恢复

## 自我恢复能力验证报告模板

```markdown
# 自我恢复能力验证报告 - [实验名称]

## 实验信息
- 实验类型: [Pod故障 / 网络延迟 / 依赖故障 / 资源耗尽 / 级联故障]
- 目标服务: [service-name]
- 故障开始时间: [timestamp]
- 故障结束时间: [timestamp]

## 自我恢复验证

### 1. Pod 自动重启 ✅
- 故障类型: PodKill
- Pod 重建时间: 45s (预期 ≤60s) ✅
- Ready 状态: 已达到 ✅
- 评价: 通过 ✅

### 2. 健康检查 ✅
- liveness probe: 正常触发重启 ✅
- readiness probe: 正确标记 NotReady → Ready ✅
- 评价: 通过 ✅

### 3. Service 发现更新 ✅
- endpoints 更新时间: 20s (预期 ≤30s) ✅
- 流量切换: 自动切换到健康 Pod ✅
- 评价: 通过 ✅

### 4. 连接重建 ✅
- 连接泄漏: 0 (预期 0) ✅
- 连接重建时间: 15s (预期 ≤30s) ✅
- 评价: 通过 ✅

### 5. 资源使用恢复 ✅
- CPU 使用率恢复正常时间: 2min (预期 ≤5min) ✅
- Memory 使用率恢复正常时间: 1min (预期 ≤5min) ✅
- 评价: 通过 ✅

## 恢复时间分析
| 指标 | 实际值 | 预期值 | 评价 |
|------|--------|--------|------|
| Pod 恢复时间 | 45s | ≤60s | ✅ 优秀 |
| Service 更新时间 | 20s | ≤30s | ✅ 优秀 |
| 连接重建时间 | 15s | ≤30s | ✅ 优秀 |
| 完全恢复时间 | 3min | ≤5min | ✅ 优秀 |

## 资源泄漏检测
- 连接泄漏: 0 ✅
- 文件描述符泄漏: 0 ✅
- 内存泄漏: 0 ✅
- 评价: 无资源泄漏 ✅

## 问题识别
- 无

## 改进建议
- 无

## 总结
- 自我恢复能力: 优秀
- 恢复时间: 符合预期
- 资源泄漏: 无
- 整体评价: 通过 ✅
```

## 常见自我恢复问题

| 问题 | 表现 | 根本原因 | 解决方案 |
|------|------|---------|---------|
| Pod 无法恢复 | Pod 持续 CrashLoopBackOff | 应用启动失败、资源不足 | 检查应用日志、调整资源配置 |
| 健康检查失败 | liveness/readiness probe 持续失败 | probe 配置不合理、应用不响应 | 调整 probe 超时和间隔 |
| 连接泄漏 | 连接数持续增长 | 连接未正确关闭 | 检查应用代码，添加连接池 |
| 慢恢复 | 恢复时间过长 | 应用冷启动、依赖服务慢 | 优化应用启动、添加预热 |
| 资源未释放 | CPU/Memory 持续高 | 资源未正确释放 | 检查应用代码，添加资源清理 |

## 最佳实践

1. **优化健康检查配置**
   - liveness probe: 检测应用是否存活
   - readiness probe: 检查应用是否就绪
   - 合理设置超时和间隔

2. **配置合理的资源限制**
   - requests: 保证最小资源
   - limits: 防止资源耗尽
   - 使用 QoS 类隔离

3. **实现优雅终止**
   - 处理 SIGTERM 信号
   - 完成正在处理的请求
   - 关闭连接和释放资源

4. **实现连接池管理**
   - 使用连接池复用连接
   - 设置合理的连接池大小
   - 实现连接超时和重试

5. **监控恢复过程**
   - 记录恢复时间
   - 监控资源使用
   - 检测资源泄漏

## 相关文档

- [混沌实验运行手册](./runbook.md)
- [告警验证指南](./alert-validation-guide.md)
- [故障排除指南](./troubleshooting.md)
