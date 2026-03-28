---
name: "grafana-oncall-alertgroup"
description: "Manage Grafana OnCall AlertGroups: list, view details, ACK, resolve, silence, unack, unsilence. Invoke when user wants to operate on OnCall alert groups."
---

# Grafana OnCall AlertGroup Skill

Grafana OnCall AlertGroup 操作 Skill，通过 Grafana Plugin Proxy 调用 OnCall API，支持对 AlertGroup 进行查看、确认、解决、静默等操作。

## 移植到其他项目

只需两步：

1. **复制 Skill 目录**到目标项目：
```bash
cp -r .trae/skills/grafana-oncall-alertgroup <目标项目>/.trae/skills/
```

2. **在目标项目根目录 `.env` 中配置 Grafana 凭证**：
```
GRAFANA_URL=http://grafana:3000
GRAFANA_USER=admin
GRAFANA_PASSWORD=admin
```

> Skill 会从自身目录开始向上逐级搜索 `.env` 文件，所以 `.env` 放在项目根目录即可。

## 目录结构

```
.trae/skills/grafana-oncall-alertgroup/
├── SKILL.md          # 本文件：Skill 描述与使用指南
└── oncall_api.py     # 核心引擎：OnCall API 封装 + CLI
```

## 核心能力

执行引擎为本目录下的 `oncall_api.py`，提供以下能力：

| 能力 | 函数 | CLI 命令 | 说明 |
|------|------|---------|------|
| 列出 AlertGroup | `list_alert_groups(status, limit)` | `list [status] [limit]` | 列出 AlertGroup，可按状态筛选 |
| 查看详情 | `get_alert_group(id)` | `get <id>` | 查看 AlertGroup 完整详情 |
| ACK（确认） | `acknowledge(id)` | `ack <id>` | 确认 AlertGroup |
| 取消 ACK | `unacknowledge(id)` | `unack <id>` | 取消已确认状态 |
| Resolve（解决） | `resolve(id)` | `resolve <id>` | 解决 AlertGroup |
| 取消 Resolve | `unresolve(id)` | `unresolve <id>` | 重新打开已解决的 AlertGroup |
| Silence（静默） | `silence(id, delay)` | `silence <id> [delay]` | 静默 AlertGroup（默认 30 分钟） |
| 取消静默 | `unsilence(id)` | `unsilence <id>` | 取消静默状态 |
| 添加 Note | `add_resolution_note(id, text)` | `note <id> <text>` | 为 AlertGroup 添加 Resolution Note |
| 查看 Notes | `list_resolution_notes(id)` | `notes <id>` | 查看 AlertGroup 的所有 Resolution Notes |

### AlertGroup 状态说明

| 状态 | 含义 |
|------|------|
| `new` | 新产生的告警，尚未处理 |
| `acknowledged` | 已确认（ACK），表示有人在关注 |
| `silenced` | 已静默，在指定时长内不会升级通知 |
| `resolved` | 已解决 |

## 使用方式

### 方式一：命令行调用（推荐 Agent 使用）

```bash
SKILL_PATH=".trae/skills/grafana-oncall-alertgroup/oncall_api.py"

# 列出所有 AlertGroup
python3 $SKILL_PATH list

# 列出指定状态的 AlertGroup（new / acknowledged / resolved / silenced）
python3 $SKILL_PATH list new
python3 $SKILL_PATH list acknowledged

# 列出指定状态并限制数量
python3 $SKILL_PATH list new 10

# 查看 AlertGroup 详情
python3 $SKILL_PATH get I1234567890

# ACK（确认）
python3 $SKILL_PATH ack I1234567890

# 取消 ACK
python3 $SKILL_PATH unack I1234567890

# Resolve（解决）
python3 $SKILL_PATH resolve I1234567890

# 取消 Resolve（重新打开）
python3 $SKILL_PATH unresolve I1234567890

# Silence（静默），默认 30 分钟
python3 $SKILL_PATH silence I1234567890

# Silence 自定义时长（支持 m/h/d 后缀）
python3 $SKILL_PATH silence I1234567890 1h
python3 $SKILL_PATH silence I1234567890 30m
python3 $SKILL_PATH silence I1234567890 1d
python3 $SKILL_PATH silence I1234567890 3600   # 纯数字为秒

# 取消静默
python3 $SKILL_PATH unsilence I1234567890

# 添加 Resolution Note
python3 $SKILL_PATH note I1234567890 "已确认是配置变更导致，正在回滚"

# 查看 Resolution Notes
python3 $SKILL_PATH notes I1234567890

# 查看帮助
python3 $SKILL_PATH help
```

### 方式二：Python 代码调用

```python
import sys
sys.path.insert(0, ".trae/skills/grafana-oncall-alertgroup")
from oncall_api import (
    list_alert_groups, get_alert_group,
    acknowledge, unacknowledge,
    resolve, unresolve,
    silence, unsilence,
    add_resolution_note, list_resolution_notes,
)

# 列出所有 new 状态的 AlertGroup
result = list_alert_groups(status="new")
for ag in result.get("results", []):
    print(ag["id"], ag.get("title", ""))

# 查看详情
detail = get_alert_group("I1234567890")

# ACK
acknowledge("I1234567890")

# 取消 ACK
unacknowledge("I1234567890")

# Resolve
resolve("I1234567890")

# Silence 1 小时
silence("I1234567890", delay=3600)

# 取消静默
unsilence("I1234567890")

# 添加 Resolution Note
add_resolution_note("I1234567890", "已确认是配置变更导致，正在回滚")

# 查看 Resolution Notes
notes = list_resolution_notes("I1234567890")
for n in notes:
    print(n["created_at"], n["author"]["username"], n["text"])
```

## 典型工作流

### 1. 查看 → ACK → 处理 → Resolve

```bash
SKILL_PATH=".trae/skills/grafana-oncall-alertgroup/oncall_api.py"

# 第一步：查看当前新告警
python3 $SKILL_PATH list new

# 第二步：查看某个告警详情
python3 $SKILL_PATH get I1234567890

# 第三步：确认正在处理
python3 $SKILL_PATH ack I1234567890

# 第四步：问题解决后标记为 Resolved
python3 $SKILL_PATH resolve I1234567890
```

### 2. 临时静默非紧急告警

```bash
# 静默 1 小时，稍后再处理
python3 $SKILL_PATH silence I1234567890 1h

# 提前恢复通知
python3 $SKILL_PATH unsilence I1234567890
```

## 认证机制

本 Skill 通过 **Grafana Plugin Proxy** 间接调用 OnCall API：

1. 使用 Grafana 的 Basic Auth（用户名 + 密码）进行认证
2. 请求路径为 `{GRAFANA_URL}/api/plugins/grafana-oncall-app/resources/{oncall_api_path}`
3. Grafana 会自动代理请求到 OnCall 后端
4. 无需直接访问 OnCall API 端口或配置 OnCall API Token

## 环境配置

在项目 `.env` 文件中配置以下变量：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `GRAFANA_URL` | `http://grafana:3000` | Grafana 服务地址 |
| `GRAFANA_USER` | `admin` | Grafana 用户名 |
| `GRAFANA_PASSWORD` | `admin` | Grafana 密码 |

## 注意事项

- **零依赖**：仅使用 Python 标准库，无需安装第三方包
- **自包含**：Skill 目录内包含所有运行时文件
- **幂等操作**：重复 ACK/Resolve 不会报错，API 会忽略重复操作
- **状态流转**：只有合法的状态转换才会生效（例如不能 Unack 一个未 Ack 的 AlertGroup）
- **静默时长**：Silence 需要指定时长，超时后会自动恢复通知升级
- **错误处理**：所有 API 错误会包含 HTTP 状态码和响应体，便于排查
