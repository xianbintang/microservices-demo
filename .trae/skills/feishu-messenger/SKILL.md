---
name: "feishu-messenger"
description: "Send, reply, edit Feishu/Lark messages with auto-auth. Invoke when user wants to send messages, reply, urgent notify, or interact with Feishu chats. Supports sending approval cards for dangerous operations that require user confirmation before execution."
---

# Feishu Messenger Skill

飞书消息交互 Skill，封装了飞书开放平台 IM 相关 API，支持挂载到任意 Agent 使用。

## 移植到其他项目

只需两步：

1. **复制 Skill 目录**到目标项目：
```bash
cp -r .trae/skills/feishu-messenger <目标项目>/.trae/skills/
```

2. **在目标项目根目录创建 `.env`**，配置飞书应用凭证：
```
app_id=cli_xxxxxxxxxxxx
app_secret=xxxxxxxxxxxxxxxx
feishu_chat_id=oc_xxxxxxxxxxxx
```

> Skill 会从自身目录开始向上逐级搜索 `.env` 文件，所以 `.env` 放在项目根目录即可。
> Token 自动获取并缓存在 Skill 目录内的 `.token_cache.json`，有效期 2 小时，到期自动刷新。

### 默认群聊 ID 约定

`.env` 中的 `feishu_chat_id` 配置了默认的飞书群聊 ID。**优先级规则：**

1. **用户/调用方明确指定 chat_id** → 使用指定值
2. **未指定 chat_id** → 自动从 `.env` 的 `feishu_chat_id` 读取

这意味着：
- CLI 命令中所有需要 `chat_id` 的参数均可**省略**，省略时自动使用默认值
- Python 函数中 `chat_id` 参数可传 `None`，自动回退到默认值
- Agent 在对话中如果用户未指定群聊，应自动使用此默认群聊

## 目录结构

```
.trae/skills/feishu-messenger/
├── SKILL.md              # 本文件：Skill 描述与使用指南
├── feishu_api.py          # 核心引擎：鉴权 + API 封装 + CLI
└── .token_cache.json      # 自动生成：token 缓存（无需手动管理）
```

## 核心能力

执行引擎为本目录下的 `feishu_api.py`，提供以下能力：

| 能力 | 函数 | CLI 命令 | 说明 |
|------|------|---------|------|
| 发送文本消息 | `send_text(chat_id, text)` | `send [chat_id] <text>` | 向群聊发送纯文本 |
| 发送卡片消息 | `send_card(chat_id, card_dict)` | `send_card [chat_id] <card_json>` | 发送交互式卡片（JSON） |
| 发送 @人消息 | `send_at_message(chat_id, open_id, text)` | `at [chat_id] <open_id> <text>` | @某人/机器人 发送富文本 |
| 回复消息 | `reply_text(message_id, text)` | `reply <mid> <text>` | 普通回复 |
| 话题回复 | `reply_in_thread(message_id, text)` | `reply_thread <mid> <text>` | 以话题（thread）形式回复 |
| 回复+@人 | `reply_at_message(mid, oid, text)` | `reply_at <mid> <oid> <text>` | 回复消息并 @某人 |
| 话题回复+@人 | `reply_at_message(mid, oid, text, in_thread=True)` | `reply_thread_at <mid> <oid> <text>` | 话题回复并 @某人 |
| 编辑卡片 | `update_card(message_id, card_dict)` | `update_card <mid> <card_json>` | 全量替换卡片内容（仅限自己发的卡片） |
| 应用内加急 | `urgent_app(mid, [open_ids])` | `urgent_app <mid> <oid>` | 飞书 App 内加急通知 |
| 短信加急 | `urgent_sms(mid, [open_ids])` | `urgent_sms <mid> <oid>` | 发送短信加急 |
| 电话加急 | `urgent_phone(mid, [open_ids])` | `urgent_phone <mid> <oid>` | 拨打电话加急 |
| 获取历史消息 | `get_chat_history(chat_id)` | `history [chat_id]` | 获取会话聊天记录（自动分页） |
| 获取群成员 | `get_chat_members(chat_id)` | `members [chat_id]` | 列出群内所有人类成员 |
| 按名字找人 | `find_member_by_name(chat_id, name)` | `find_member [chat_id] <name>` | 在群成员中模糊搜索 |
| 获取单条消息 | `get_message(message_id)` | `get_message <mid>` | 获取消息详情 |
| 获取默认群聊 | `get_default_chat_id()` | — | 从 .env 读取默认群聊 ID |
| 获取 Token | `get_token()` | `token` | 手动获取当前 token |
| **发送审批卡片（一站式）** | `send_approval_and_wait(title, desc, ...)` | `send_approval [chat_id] <title> <desc> [risk] [timeout]` | **发送审批卡片并阻塞等待用户确认/拒绝** |
| 发送审批卡片（仅发送） | `send_approval_card(title, desc, ...)` | `send_approval_only [chat_id] <title> <desc> [risk]` | 仅发送审批卡片，不等待结果 |
| 审批回调处理 | `handle_approval_callback(action, id, oid)` | `approval_result <id> <confirm\|reject>` | 手动写入审批结果 |
| 等待审批结果 | `wait_approval(approval_id, ...)` | — | 轮询等待审批结果（配合 send_approval_card 使用） |

> `[chat_id]` 表示可选参数，省略时自动使用 `.env` 中的 `feishu_chat_id`。

## 使用方式

### 方式一：命令行调用（推荐 Agent 使用）

```bash
SKILL_PATH=".trae/skills/feishu-messenger/feishu_api.py"

# 发送文本消息到群聊（省略 chat_id，自动使用 .env 中的 feishu_chat_id）
python3 $SKILL_PATH send "你好，这是一条测试消息"

# 发送文本消息到指定群聊（明确指定 chat_id 优先）
python3 $SKILL_PATH send oc_xxxxx "你好，这是一条测试消息"

# 发送卡片消息（省略 chat_id）
python3 $SKILL_PATH send_card '{"header":{"template":"red","title":{"tag":"plain_text","content":"报警通知"}},"elements":[{"tag":"div","text":{"tag":"lark_md","content":"**服务:** my-service"}}]}'

# 在话题中回复
python3 $SKILL_PATH reply_thread om_xxxxx "收到，马上处理"

# 回复消息并 @某人
python3 $SKILL_PATH reply_at om_xxxxx ou_xxxxx "请处理这个问题"

# 话题回复并 @某人
python3 $SKILL_PATH reply_thread_at om_xxxxx ou_xxxxx "已加急你来处理"

# @某人发新消息（省略 chat_id）
python3 $SKILL_PATH at ou_xxxxx "请查看这个问题"

# 编辑已发送的卡片
python3 $SKILL_PATH update_card om_xxxxx '{"header":{"template":"green","title":{"tag":"plain_text","content":"已恢复"}},"elements":[{"tag":"div","text":{"tag":"lark_md","content":"服务已恢复正常"}}]}'

# 电话加急
python3 $SKILL_PATH urgent_phone om_xxxxx ou_xxxxx

# 获取群成员（省略 chat_id）
python3 $SKILL_PATH members

# 按名字找人（省略 chat_id）
python3 $SKILL_PATH find_member "张三"

# 获取单条消息详情
python3 $SKILL_PATH get_message om_xxxxx

# 获取历史消息（省略 chat_id）
python3 $SKILL_PATH history

# 获取当前 token
python3 $SKILL_PATH token

# 发送审批卡片并等待用户确认（阻塞直到用户操作或超时）
python3 $SKILL_PATH send_approval "重启 payment-service" "将重启 3 个副本" high 300

# 仅发送审批卡片（不等待，返回 approval_id）
python3 $SKILL_PATH send_approval_only "清理缓存" "清理 Redis 过期数据" low

# 手动写入审批结果（测试/调试用）
python3 $SKILL_PATH approval_result <approval_id> confirm
```

### 方式二：Python 代码调用

```python
import sys
sys.path.insert(0, ".trae/skills/feishu-messenger")
from feishu_api import (
    send_text, send_card, send_at_message,
    reply_text, reply_in_thread, reply_at_message,
    update_card,
    urgent_app, urgent_phone, urgent_sms,
    get_chat_history, get_chat_members, find_member_by_name,
    get_message, get_token, get_default_chat_id,
)

# 发送文本（省略 chat_id，自动使用 .env 默认值）
result = send_text(text="你好")
message_id = result["data"]["message_id"]

# 发送到指定群聊（明确传入 chat_id 优先）
result = send_text("oc_xxxxx", "你好")

# 话题回复
reply_in_thread(message_id, "这是话题回复")

# 话题回复并 @某人
reply_at_message(message_id, "ou_xxxxx", "请处理", in_thread=True)

# 找人并电话加急（省略 chat_id）
member = find_member_by_name(name="张三")
if member:
    urgent_phone(message_id, [member["member_id"]])
```

### 方式三：发送卡片 + 编辑卡片

```python
from feishu_api import send_card, update_card

card = {
    "config": {"update_multi": True},
    "header": {
        "template": "red",
        "title": {"tag": "plain_text", "content": "报警通知"}
    },
    "elements": [
        {"tag": "div", "text": {"tag": "lark_md", "content": "**服务:** my-service\n**状态:** 异常"}},
        {"tag": "hr"},
        {"tag": "note", "elements": [{"tag": "plain_text", "content": "来自监控系统"}]}
    ]
}

# 发送卡片（省略 chat_id，自动使用 .env 默认值）
result = send_card(card=card)
msg_id = result["data"]["message_id"]

# 稍后编辑：在底部追加操作记录
card["elements"].insert(-1, {
    "tag": "div",
    "text": {"tag": "plain_text", "content": "[2026-03-28 13:11] 张三 确认了报警"}
})
update_card(msg_id, card)
```

### 方式四：审批卡片（危险操作确认）

当 Agent 需要执行危险操作（如重启服务、删除数据、修改配置等）时，应先发送审批卡片到飞书群让用户确认。

**一站式用法（推荐，CLI 命令）：**

```bash
SKILL_PATH=".trae/skills/feishu-messenger/feishu_api.py"

# 发送审批卡片并阻塞等待用户操作（默认超时 300 秒）
# 返回: [APPROVED] / [REJECTED] / [TIMEOUT]
python3 $SKILL_PATH send_approval "重启 payment-service" "将重启生产环境 payment-service 的 3 个副本，预计服务中断约 30 秒" high 300

# 低风险操作示例
python3 $SKILL_PATH send_approval "清理过期缓存" "将清理 Redis 中超过 7 天的过期 session 缓存" low
```

**一站式用法（Python）：**

```python
from feishu_api import send_approval_and_wait

result = send_approval_and_wait(
    title="重启 payment-service",
    description="将重启生产环境 payment-service 的 3 个副本，预计服务中断约 30 秒",
    risk_level="high",   # high / medium / low
    timeout=300,          # 等待超时秒数
)

if result["approved"]:
    print("用户已批准，继续执行操作...")
elif result["timed_out"]:
    print("超时未响应，操作已取消")
else:
    print("用户已拒绝，操作已取消")
```

**分步用法（仅发送卡片，稍后查询结果）：**

```python
from feishu_api import send_approval_card, wait_approval

# 步骤 1：发送审批卡片
send_result = send_approval_card(
    title="删除旧数据",
    description="将删除 orders 表中 2024 年之前的归档数据（约 500 万行）",
    risk_level="high",
)
approval_id = send_result["approval_id"]
message_id = send_result["message_id"]

# 步骤 2：等待审批结果
result = wait_approval(
    approval_id,
    timeout=600,
    message_id=message_id,
    title="删除旧数据",
    description="将删除 orders 表中 2024 年之前的归档数据",
)
```

**审批卡片特性：**

- 卡片包含：操作标题、操作详情说明、风险等级标识、「✅ 确认执行」和「❌ 拒绝」按钮
- 用户点击按钮后，卡片自动更新为审批结果状态（绿色=已批准，红色=已拒绝）
- 超时未操作自动标记为拒绝，卡片更新显示"系统超时"
- 审批结果包含操作人 open_id，可用于审计追踪
- 风险等级影响卡片颜色：high=红色、medium=橙色、low=蓝色

## 鉴权机制

本 Skill **内置了完整的鉴权逻辑**，Agent 无需关心 token 管理：

1. 首次调用时，自动用 `.env` 中的 `app_id` + `app_secret` 获取 `tenant_access_token`
2. Token 缓存到 Skill 目录内的 `.token_cache.json`，后续调用直接使用缓存
3. Token 剩余有效期不足 10 分钟时自动刷新
4. 所有 API 函数内部自动调用 `get_token()`，完全透明
5. `.env` 查找逻辑：从 Skill 目录逐级向上搜索直到项目根目录

## 权限要求

飞书应用需要开启以下权限（按需开通）：

| 权限 | 用途 |
|------|------|
| `im:message` / `im:message:send_as_bot` | 发送消息 |
| `im:message.group_msg` | 获取群组历史消息 |
| `im:chat:readonly` / `im:chat.member:read` | 获取群成员 |
| `im:message.urgent` | 应用内加急 |
| `im:message.urgent:phone` | 电话加急 |
| `im:message.urgent:sms` | 短信加急 |

## 注意事项

- **编辑卡片**：只能编辑自己应用发送的卡片，且卡片 `config` 中必须有 `"update_multi": true`
- **加急通知**：只能加急自己应用发送的消息
- **频率限制**：同一用户 5 QPS，同一群组 5 QPS（群内所有机器人共享）
- **零依赖**：仅使用 Python 标准库，无需安装第三方包
- **自包含**：Skill 目录内包含所有运行时文件（代码 + token 缓存），仅 `.env` 放在项目根目录
