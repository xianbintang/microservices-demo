---
name: grafana
description: Grafana 统一操作接口（通过 REST API），支持数据查询、Dashboard 管理、告警管理、故障排查。用法：/grafana <action> [args...]
license: MIT
compatibility:
  claude_code: ">=1.0"
metadata:
  author: zxx
  version: 2.0.0
  generatedBy: claude-sonnet-4-6
---

# Grafana 统一操作 Skill

通过 Grafana REST API 实现所有操作，不依赖 MCP，兼容 Openclaw。

## 认证配置

认证信息已硬编码在 `lib/auth.sh` 中，开箱即用。

**如需修改**，编辑 `lib/auth.sh` 文件。

## 用法

```bash
/grafana <action> [args...]
```

## 可用 Actions

### 数据查询

#### test-connection - 测试连接

```bash
/grafana test-connection
```

**示例：**
```bash
/grafana test-connection
# 输出: ✅ Grafana 11.2.0 OK
```

---

#### list-datasources - 列出数据源

```bash
/grafana list-datasources [--type <prometheus|loki|tempo>]
```

**参数：**
- `--type`: 过滤数据源类型（可选）

**示例：**
```bash
/grafana list-datasources
# 输出:
# Loki (uid=loki, type=loki)
# Prometheus (uid=prometheus, type=prometheus)
# Tempo (uid=tempo, type=tempo)

/grafana list-datasources --type prometheus
# 输出:
# Prometheus (uid=prometheus, type=prometheus)
```

---

#### query-prometheus - 查询 Prometheus 指标

```bash
/grafana query-prometheus <expr> [--datasource <uid>] [--start <time>] [--end <time>] [--step <seconds>]
```

**参数：**
- `expr`: PromQL 表达式（必需）
- `--datasource`: 数据源 UID（可选，默认自动选择）
- `--start`: 开始时间，如 `now-1h`（可选，默认最近 1 小时）
- `--end`: 结束时间（可选，默认 now）
- `--step`: 步长秒数（可选，默认 60）

**示例：**
```bash
/grafana query-prometheus 'up{job="prometheus"}'

/grafana query-prometheus 'rate(http_requests_total[5m])' --start now-2h

/grafana query-prometheus 'container_cpu_usage_seconds_total{namespace="online-boutique"}' --step 30
```

---

### Dashboard 管理

#### search-dashboards - 搜索 Dashboard

```bash
/grafana search-dashboards <query> [--limit <n>]
```

**参数：**
- `query`: 搜索关键词（必需）
- `--limit`: 返回数量限制（可选，默认 50）

**示例：**
```bash
/grafana search-dashboards boutique

/grafana search-dashboards redis --limit 10
```

---

### 告警管理

#### list-alerts - 列出告警规则

```bash
/grafana list-alerts
```

**示例：**
```bash
/grafana list-alerts
# 输出:
# High CPU Usage (uid=alert-123, state=firing)
# Low Memory (uid=alert-456, state=inactive)
```

---

### 注解管理

#### create-annotation - 创建注解

```bash
/grafana create-annotation --text <text> [--dashboard <uid>] [--tags <tags>]
```

**参数：**
- `--text`: 注解文本（必需）
- `--dashboard`: Dashboard UID（可选）
- `--tags`: 标签列表，逗号分隔（可选）

**示例：**
```bash
/grafana create-annotation --text "Deployed v1.2.3" --tags deploy,release

/grafana create-annotation --text "CPU spike" --dashboard fffrl21oam2gwa --tags incident
```

---

## 执行逻辑

当调用 `/grafana <action>` 时：

1. 从 `$ARGUMENTS` 提取 action
2. 调用对应的脚本：`.claude/skills/grafana/scripts/<action>.sh`
3. 脚本自动加载 `lib/auth.sh` 获取认证信息
4. 执行 curl 调用 Grafana REST API
5. 用 Python 格式化输出

## 目录结构

```
.claude/skills/grafana/
├── SKILL.md              # 本文档
├── lib/
│   └── auth.sh          # 认证配置（硬编码 Token）
└── scripts/
    ├── test-connection.sh
    ├── list-datasources.sh
    ├── query-prometheus.sh
    ├── search-dashboards.sh
    └── ... (其他脚本)
```

## 完整示例

```bash
# 1. 测试连接
/grafana test-connection

# 2. 查看数据源
/grafana list-datasources

# 3. 查询 CPU 使用率
/grafana query-prometheus 'rate(container_cpu_usage_seconds_total[5m])'

# 4. 搜索 Dashboard
/grafana search-dashboards boutique

# 5. 创建注解
/grafana create-annotation --text "Deployed v1.2.3" --tags deploy

# 6. 列出告警
/grafana list-alerts
```

## 错误处理

- 连接失败：检查 Grafana 服务状态
- 认证失败：检查 Token 是否有效
- 参数缺失：返回用法说明

## 扩展开发

如需添加新功能：

1. 创建脚本：`scripts/<new-action>.sh`
2. 引用认证：`source "$SCRIPT_DIR/../lib/auth.sh"`
3. 实现 API 调用
4. 更新本文档添加用法说明
