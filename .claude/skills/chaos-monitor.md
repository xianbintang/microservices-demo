---
description: 监控正在运行的混沌实验，显示实时状态和关键指标
---

# 混沌实验监控

## 用法

```
/chaos-monitor [experiment-id]
```

## 参数

- `experiment-id`: 可选，指定实验 ID（默认：显示所有运行中的实验）

## 显示信息

- 实验状态（Running/Paused/Completed）
- 已运行时长 / 总时长
- Pod 状态
- Service endpoints
- 错误率
- P95/P99 延迟
- 告警状态

## Grafana 大盘链接

```
http://localhost:3000/d/chaos-experiment?var-experiment=<experiment-id>
```