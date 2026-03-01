# 关键告警场景清单

## 概述

本文档定义了混沌工程实验需要的关键告警场景。在执行混沌实验前，应确保这些场景都有相应的告警规则覆盖。

## 告警场景分类

### 1. Pod 状态告警
| 场景 | 严重级 | 说明 |
|------|--------|------|
| KubePodCrashLooping | critical | Pod 处于 CrashLoopBackOff 状态 |
| KubePodNotReady | warning | Pod 处于 NotReady 状态超过 5 分钟 |

### 2. 服务可用性告警
| 场景 | 严重级 | 说明 |
|------|--------|------|
| TargetDown | critical | Service/Target 无可用 endpoint |
| KubeletDown | critical | Kubelet 服务不可用 |
| KubeAPIDown | critical | Kubernetes API 服务器不可用 |

### 3. 性能指标告警
| 场景 | 严重级 | 说明 |
|------|--------|------|
| KubeletPodStartUpLatencyHigh | warning | Pod 启动延迟高 |
| KubeClientErrors | warning | Kube 客户端错误率高 |

### 4. 资源使用告警
| 场景 | 严重级 | 说明 |
|------|--------|------|
| CPUThrottlingHigh | warning | CPU 节流频率高 |
| NodeCPUHighUsage | warning | 节点 CPU 使用率高 |
| NodeMemoryHighUtilization | warning | 节点内存使用率高 |

### 5. 依赖服务告警
| 场景 | 严重级 | 说明 |
|------|--------|------|
| KubeAggregatedAPIErrors | warning | 聚合 API 错误率高 |
| PrometheusErrorSendingAlertsToAnyAlertmanager | warning | 告警发送失败 |

### 6. 熔断器告警
| 场景 | 严重级 | 说明 |
|------|--------|------|
| KubePdbNotEnoughHealthyPods | warning | PDB 健康 Pod 不足 |

## Online Boutique 特定告警

以下服务是 Online Boutique 的关键服务，建议有独立告警：
- frontend
- checkoutservice
- cartservice
- productcatalogservice
- currencyservice
- recommendationservice
