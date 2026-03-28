#!/usr/bin/env python3
"""
飞书消息 API 统一封装库（feishu_api.py）

本模块是 feishu-messenger Skill 的核心执行引擎，封装了以下能力：
  1. 鉴权：自动获取/缓存/刷新 tenant_access_token
  2. 发送消息：文本、富文本（@人）、卡片
  3. 回复消息：普通回复、话题回复
  4. 编辑卡片：更新已发送的卡片消息内容
  5. 加急通知：应用内加急、短信加急、电话加急
  6. 获取历史消息：按会话获取聊天记录（自动分页）
  7. 获取群成员：列出群内所有人类成员

鉴权说明：
  - 需要在项目根目录的 .env 文件中配置 app_id 和 app_secret
  - token 自动缓存到 .token_cache.json，有效期 2 小时
  - 剩余有效期不足 10 分钟时自动刷新

使用方式：
  直接在终端用 python3 feishu_api.py <command> [args] 调用
  或在 Python 代码中 import 使用

依赖：仅使用 Python 标准库，无需安装第三方包
"""

import json
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path


# ============================================================
# 配置与路径
# ============================================================

# Skill 自身目录（所有缓存文件都放在这里，保持自包含）
_SKILL_DIR = Path(__file__).resolve().parent

# token 缓存文件放在 Skill 目录内，移植时跟着走
_CACHE_PATH = _SKILL_DIR / ".token_cache.json"

# token 剩余有效期低于此值（秒）时触发刷新
_REFRESH_THRESHOLD = 600

# .env 中默认群聊 ID 的变量名
_DEFAULT_CHAT_ID_KEY = "feishu_chat_id"


def _find_env_file() -> Path:
    """
    从 Skill 目录开始，逐级向上搜索 .env 文件，直到文件系统根目录。
    这样无论 Skill 被放在项目的哪个层级都能找到项目根目录的 .env。
    也支持 .env 直接放在 Skill 目录内（优先级最高）。
    """
    current = _SKILL_DIR
    while True:
        candidate = current / ".env"
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            # 已到文件系统根目录，停止搜索
            return None
        current = parent


# ============================================================
# 内部工具函数
# ============================================================

def _load_env() -> dict:
    """
    读取配置，返回 key-value 字典。

    优先从 .env 文件读取（本地开发场景）；
    如果找不到 .env 文件，则从 os.environ 读取（Docker 容器场景，
    由 docker-compose env_file 或 environment 注入）。
    """
    import os as _os
    env_path = _find_env_file()
    if env_path:
        env_vars = {}
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    env_vars[key.strip()] = value.strip()
        return env_vars
    # .env 文件不存在时，从系统环境变量读取（兼容容器部署场景）
    return dict(_os.environ)


def _load_cache() -> dict:
    if not _CACHE_PATH.exists():
        return {}
    try:
        with open(_CACHE_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save_cache(cache: dict) -> None:
    with open(_CACHE_PATH, "w") as f:
        json.dump(cache, f, indent=2)


def get_default_chat_id() -> str:
    """
    从 .env 中读取默认群聊 ID（feishu_chat_id）。
    当调用方未明确指定 chat_id 时，自动使用此值作为兜底。

    返回: chat_id 字符串
    异常: RuntimeError 当 .env 中未配置 feishu_chat_id 时抛出
    """
    env = _load_env()
    chat_id = env.get(_DEFAULT_CHAT_ID_KEY, "")
    if not chat_id:
        raise RuntimeError(
            f".env 中未配置 {_DEFAULT_CHAT_ID_KEY}。\n"
            f"请在 .env 中添加：\n  {_DEFAULT_CHAT_ID_KEY}=oc_xxxxxxxxxxxx\n"
            "或在调用时明确指定 chat_id 参数。"
        )
    return chat_id


def _resolve_chat_id(chat_id: str = None) -> str:
    """
    解析最终使用的 chat_id：
      - 调用方明确传入 → 使用传入值
      - 未传入（None / 空字符串）→ 从 .env 的 feishu_chat_id 读取
    """
    if chat_id:
        return chat_id
    return get_default_chat_id()


def _is_token_valid(cache: dict) -> bool:
    token = cache.get("tenant_access_token", "")
    fetched_at = cache.get("fetched_at", 0)
    expire = cache.get("expire", 0)
    if not token or not fetched_at:
        return False
    remaining = fetched_at + expire - int(time.time())
    return remaining > _REFRESH_THRESHOLD


def _api_request(token: str, method: str, url: str, payload: dict = None) -> dict:
    """
    通用飞书 API 请求。

    参数:
        token: Bearer Token（tenant_access_token）
        method: HTTP 方法（GET / POST / PATCH / PUT / DELETE）
        url: 完整请求 URL
        payload: 请求体（POST/PATCH/PUT 时使用）
    返回:
        API 响应体 dict
    异常:
        RuntimeError: 当 HTTP 请求失败或网络不可达时抛出
    """
    data = json.dumps(payload).encode("utf-8") if payload else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json; charset=utf-8")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else ""
        try:
            return json.loads(error_body)
        except json.JSONDecodeError:
            raise RuntimeError(f"HTTP {e.code}: {error_body}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"网络请求失败: {e.reason}")


# ============================================================
# 鉴权：自动获取 / 缓存 / 刷新 token
# ============================================================

def get_token() -> str:
    """
    获取可用的 tenant_access_token。
    优先使用本地缓存，即将过期时自动刷新。

    .env 配置要求：
      app_id=cli_xxxx
      app_secret=xxxx

    返回: token 字符串
    """
    cache = _load_cache()
    if _is_token_valid(cache):
        return cache["tenant_access_token"]

    env = _load_env()
    app_id = env.get("app_id", "")
    app_secret = env.get("app_secret", "")

    if not app_id or not app_secret:
        bearer = env.get("BearerToken", "")
        if bearer:
            return bearer
        raise RuntimeError(
            ".env 中未找到 app_id/app_secret，也没有 BearerToken。\n"
            "请在 .env 中配置：\n  app_id=cli_xxxx\n  app_secret=xxxx"
        )

    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    req_data = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode("utf-8")
    req = urllib.request.Request(url, data=req_data, method="POST")
    req.add_header("Content-Type", "application/json; charset=utf-8")

    try:
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else ""
        raise RuntimeError(f"获取 token 失败: HTTP {e.code} - {error_body}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"网络请求失败: {e.reason}")

    if body.get("code", -1) != 0:
        raise RuntimeError(f"获取 token 失败: code={body.get('code')}, msg={body.get('msg')}")

    token = body["tenant_access_token"]
    new_cache = {
        "tenant_access_token": token,
        "expire": body.get("expire", 7200),
        "fetched_at": int(time.time()),
    }
    _save_cache(new_cache)
    print(f"[feishu_api] token 已刷新，有效期 {new_cache['expire']}s")
    return token


# ============================================================
# 1. 发送消息
# ============================================================

def send_message(chat_id: str = None, content: str = None, msg_type: str = "text") -> dict:
    """
    向群聊或单聊发送消息。

    参数:
        chat_id:  群聊/单聊 ID（oc_xxx）；为 None 时自动从 .env 的 feishu_chat_id 读取
        content:  消息内容。
                  - msg_type="text" 时传纯文本字符串，如 "你好"
                  - msg_type="interactive" 时传卡片 JSON dict
                  - msg_type="post" 时传富文本 dict
        msg_type: 消息类型，可选 text / interactive / post / image / file
    返回:
        API 响应 dict（含 data.message_id）
    """
    chat_id = _resolve_chat_id(chat_id)
    token = get_token()
    url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"

    if msg_type == "text" and isinstance(content, str):
        content_str = json.dumps({"text": content})
    elif isinstance(content, dict):
        content_str = json.dumps(content, ensure_ascii=False)
    else:
        content_str = content

    payload = {
        "receive_id": chat_id,
        "msg_type": msg_type,
        "content": content_str,
    }
    result = _api_request(token, "POST", url, payload)
    if result.get("code") != 0:
        raise RuntimeError(f"发送消息失败: code={result.get('code')}, msg={result.get('msg')}")
    return result


def send_text(chat_id: str = None, text: str = None) -> dict:
    """发送纯文本消息（快捷方式）。chat_id 为 None 时使用 .env 默认值。"""
    return send_message(chat_id, text, "text")


def send_card(chat_id: str = None, card: dict = None) -> dict:
    """
    发送卡片消息（快捷方式）。
    card 为卡片 JSON dict，需包含 header 和 elements。
    chat_id 为 None 时使用 .env 默认值。
    """
    return send_message(chat_id, card, "interactive")


def send_at_message(chat_id: str = None, user_open_id: str = None, text: str = None) -> dict:
    """
    发送 @某人 的富文本消息。

    参数:
        chat_id:       群聊 ID；为 None 时使用 .env 默认值
        user_open_id:  被 @ 的用户/机器人的 open_id
        text:          @ 之后的文本内容
    """
    post_content = {
        "zh_cn": {
            "content": [
                [
                    {"tag": "at", "user_id": user_open_id},
                    {"tag": "text", "text": f" {text}"}
                ]
            ]
        }
    }
    return send_message(chat_id, post_content, "post")


# ============================================================
# 2. 回复消息
# ============================================================

def reply_message(message_id: str, content: str, msg_type: str = "text",
                  reply_in_thread: bool = False) -> dict:
    """
    回复指定消息。

    参数:
        message_id:      待回复的消息 ID（om_xxx）
        content:         回复内容（规则同 send_message）
        msg_type:        消息类型
        reply_in_thread: True=以话题形式回复
    返回:
        API 响应 dict
    """
    token = get_token()
    url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply"

    if msg_type == "text" and isinstance(content, str):
        content_str = json.dumps({"text": content})
    elif isinstance(content, dict):
        content_str = json.dumps(content, ensure_ascii=False)
    else:
        content_str = content

    payload = {
        "content": content_str,
        "msg_type": msg_type,
        "reply_in_thread": reply_in_thread,
    }
    result = _api_request(token, "POST", url, payload)
    if result.get("code") != 0:
        raise RuntimeError(f"回复消息失败: code={result.get('code')}, msg={result.get('msg')}")
    return result


def reply_text(message_id: str, text: str, reply_in_thread: bool = False) -> dict:
    """回复纯文本（快捷方式）。"""
    return reply_message(message_id, text, "text", reply_in_thread)


def reply_in_thread(message_id: str, text: str) -> dict:
    """以话题形式回复纯文本（快捷方式）。"""
    return reply_message(message_id, text, "text", reply_in_thread=True)


def reply_at_message(message_id: str, user_open_id: str, text: str,
                     in_thread: bool = False) -> dict:
    """
    回复指定消息并 @某人。

    使用富文本（post）格式，在回复内容中 @ 指定用户。

    参数:
        message_id:    待回复的消息 ID（om_xxx）
        user_open_id:  被 @ 的用户 open_id（ou_xxx）
        text:          @ 之后的文本内容
        in_thread:     True=以话题形式回复
    返回:
        API 响应 dict
    """
    post_content = {
        "zh_cn": {
            "content": [
                [
                    {"tag": "at", "user_id": user_open_id},
                    {"tag": "text", "text": f" {text}"}
                ]
            ]
        }
    }
    return reply_message(message_id, post_content, "post", reply_in_thread=in_thread)


# ============================================================
# 3. 编辑卡片
# ============================================================

def update_card(message_id: str, card: dict) -> dict:
    """
    更新已发送的卡片消息内容（全量替换）。

    注意：
      - 只能编辑自己发送的卡片（同一个 app_id）
      - 卡片 config 中需要 "update_multi": true
      - 仅支持 14 天内的消息

    参数:
        message_id: 卡片消息 ID
        card:       新的完整卡片 JSON dict
    """
    token = get_token()
    url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}"

    if "config" not in card:
        card["config"] = {}
    card["config"]["update_multi"] = True

    payload = {"content": json.dumps(card, ensure_ascii=False)}
    result = _api_request(token, "PATCH", url, payload)
    if result.get("code") != 0:
        raise RuntimeError(f"编辑卡片失败: code={result.get('code')}, msg={result.get('msg')}")
    return result


# ============================================================
# 4. 加急通知
# ============================================================

def urgent_app(message_id: str, user_open_ids: list) -> dict:
    """
    对指定消息进行应用内加急。

    参数:
        message_id:     消息 ID（必须是本应用发送的消息）
        user_open_ids:  目标用户 open_id 列表
    """
    token = get_token()
    url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/urgent_app?user_id_type=open_id"
    payload = {"user_id_list": user_open_ids}
    result = _api_request(token, "PATCH", url, payload)
    if result.get("code") != 0:
        raise RuntimeError(f"应用内加急失败: code={result.get('code')}, msg={result.get('msg')}")
    return result


def urgent_sms(message_id: str, user_open_ids: list) -> dict:
    """对指定消息进行短信加急。"""
    token = get_token()
    url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/urgent_sms?user_id_type=open_id"
    payload = {"user_id_list": user_open_ids}
    result = _api_request(token, "PATCH", url, payload)
    if result.get("code") != 0:
        raise RuntimeError(f"短信加急失败: code={result.get('code')}, msg={result.get('msg')}")
    return result


def urgent_phone(message_id: str, user_open_ids: list) -> dict:
    """对指定消息进行电话加急。"""
    token = get_token()
    url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/urgent_phone?user_id_type=open_id"
    payload = {"user_id_list": user_open_ids}
    result = _api_request(token, "PATCH", url, payload)
    if result.get("code") != 0:
        raise RuntimeError(f"电话加急失败: code={result.get('code')}, msg={result.get('msg')}")
    return result


# ============================================================
# 5. 获取历史消息
# ============================================================

def get_chat_history(chat_id: str = None, page_size: int = 50, start_time: str = None,
                     end_time: str = None, max_pages: int = 100) -> list:
    """
    获取会话（群聊/单聊）的历史消息，自动分页。

    参数:
        chat_id:    会话 ID；为 None 时使用 .env 默认值
        page_size:  每页消息数（1~50）
        start_time: 起始时间（秒级时间戳字符串），可选
        end_time:   结束时间（秒级时间戳字符串），可选
        max_pages:  最大分页数（防止无限循环）
    返回:
        消息列表 [dict, ...]
    """
    chat_id = _resolve_chat_id(chat_id)
    token = get_token()
    all_messages = []
    page_token = None

    for _ in range(max_pages):
        params = {
            "container_id_type": "chat",
            "container_id": chat_id,
            "page_size": str(page_size),
            "sort_type": "ByCreateTimeAsc",
        }
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time
        if page_token:
            params["page_token"] = page_token

        url = f"https://open.feishu.cn/open-apis/im/v1/messages?{urllib.parse.urlencode(params)}"
        result = _api_request(token, "GET", url)

        if result.get("code") != 0:
            raise RuntimeError(f"获取历史消息失败: code={result.get('code')}, msg={result.get('msg')}")

        data = result.get("data", {})
        items = data.get("items", [])
        all_messages.extend(items)

        if not data.get("has_more") or not data.get("page_token"):
            break
        page_token = data["page_token"]

    return all_messages


# ============================================================
# 6. 获取群成员
# ============================================================

def get_chat_members(chat_id: str = None) -> list:
    """
    获取群成员列表（自动分页）。

    参数:
        chat_id: 群聊 ID；为 None 时使用 .env 默认值
    返回:
        成员列表 [{"member_id": "ou_xxx", "name": "张三", ...}, ...]
    """
    chat_id = _resolve_chat_id(chat_id)
    token = get_token()
    all_members = []
    page_token = None

    while True:
        params = {"member_id_type": "open_id", "page_size": "100"}
        if page_token:
            params["page_token"] = page_token
        url = f"https://open.feishu.cn/open-apis/im/v1/chats/{chat_id}/members?{urllib.parse.urlencode(params)}"
        result = _api_request(token, "GET", url)

        if result.get("code") != 0:
            raise RuntimeError(f"获取群成员失败: code={result.get('code')}, msg={result.get('msg')}")

        data = result.get("data", {})
        items = data.get("items", [])
        all_members.extend(items)

        if not data.get("has_more"):
            break
        page_token = data.get("page_token")

    return all_members


def find_member_by_name(chat_id: str = None, name: str = None) -> dict:
    """
    在群成员中按名字查找用户。

    参数:
        chat_id: 群聊 ID；为 None 时使用 .env 默认值
        name:    用户姓名（支持模糊匹配）
    返回:
        匹配的成员 dict，未找到返回 None
    """
    members = get_chat_members(chat_id)
    for m in members:
        if name in m.get("name", ""):
            return m
    return None


# ============================================================
# 7. 获取单条消息
# ============================================================

def get_message(message_id: str) -> dict:
    """
    获取单条消息详情。

    参数:
        message_id: 消息 ID
    返回:
        消息详情 dict
    """
    token = get_token()
    url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}"
    result = _api_request(token, "GET", url)
    if result.get("code") != 0:
        raise RuntimeError(f"获取消息失败: code={result.get('code')}, msg={result.get('msg')}")
    items = result.get("data", {}).get("items", [])
    if not items:
        raise RuntimeError(f"未获取到消息: {message_id}")
    return items[0]


# ============================================================
# CLI 入口：支持命令行直接调用
# ============================================================

def _cli():
    """命令行入口，支持以下命令：

    注意：所有需要 <chat_id> 的命令，chat_id 均可省略，省略时自动使用 .env 中的 feishu_chat_id。

    python3 feishu_api.py token
    python3 feishu_api.py send [chat_id] <text>
    python3 feishu_api.py send_card [chat_id] <card_json>
    python3 feishu_api.py reply <message_id> <text>
    python3 feishu_api.py reply_thread <message_id> <text>
    python3 feishu_api.py reply_at <message_id> <open_id> <text>
    python3 feishu_api.py reply_thread_at <message_id> <open_id> <text>
    python3 feishu_api.py update_card <message_id> <card_json>
    python3 feishu_api.py at [chat_id] <open_id> <text>
    python3 feishu_api.py urgent_app <message_id> <open_id>
    python3 feishu_api.py urgent_phone <message_id> <open_id>
    python3 feishu_api.py urgent_sms <message_id> <open_id>
    python3 feishu_api.py history [chat_id]
    python3 feishu_api.py members [chat_id]
    python3 feishu_api.py find_member [chat_id] <name>
    python3 feishu_api.py get_message <message_id>
    """
    all_commands = [
        "token", "send", "send_card", "reply", "reply_thread",
        "reply_at", "reply_thread_at", "update_card", "at",
        "urgent_app", "urgent_phone", "urgent_sms",
        "history", "members", "find_member", "get_message",
    ]

    if len(sys.argv) < 2:
        print("用法: python3 feishu_api.py <command> [args]")
        print(f"可用命令: {', '.join(all_commands)}")
        print("提示: 需要 chat_id 的命令可省略该参数，将自动使用 .env 中的 feishu_chat_id")
        return

    cmd = sys.argv[1]

    def _is_chat_id(s: str) -> bool:
        """判断参数是否为群聊 ID（以 oc_ 开头）"""
        return s.startswith("oc_")

    try:
        if cmd == "token":
            print(get_token())

        elif cmd == "send" and len(sys.argv) >= 3:
            if len(sys.argv) >= 4 and _is_chat_id(sys.argv[2]):
                chat_id, text = sys.argv[2], " ".join(sys.argv[3:])
            else:
                chat_id, text = None, " ".join(sys.argv[2:])
            r = send_text(chat_id, text)
            print(f"[OK] message_id={r['data']['message_id']}")

        elif cmd == "send_card" and len(sys.argv) >= 3:
            if len(sys.argv) >= 4 and _is_chat_id(sys.argv[2]):
                chat_id, card_json_str = sys.argv[2], " ".join(sys.argv[3:])
            else:
                chat_id, card_json_str = None, " ".join(sys.argv[2:])
            card = json.loads(card_json_str)
            r = send_card(chat_id, card)
            print(f"[OK] message_id={r['data']['message_id']}")

        elif cmd == "reply" and len(sys.argv) >= 4:
            mid, text = sys.argv[2], " ".join(sys.argv[3:])
            r = reply_text(mid, text)
            print(f"[OK] message_id={r['data']['message_id']}")

        elif cmd == "reply_thread" and len(sys.argv) >= 4:
            mid, text = sys.argv[2], " ".join(sys.argv[3:])
            r = reply_in_thread(mid, text)
            print(f"[OK] message_id={r['data']['message_id']}")

        elif cmd == "reply_at" and len(sys.argv) >= 5:
            mid, oid, text = sys.argv[2], sys.argv[3], " ".join(sys.argv[4:])
            r = reply_at_message(mid, oid, text, in_thread=False)
            print(f"[OK] message_id={r['data']['message_id']}")

        elif cmd == "reply_thread_at" and len(sys.argv) >= 5:
            mid, oid, text = sys.argv[2], sys.argv[3], " ".join(sys.argv[4:])
            r = reply_at_message(mid, oid, text, in_thread=True)
            print(f"[OK] message_id={r['data']['message_id']}")

        elif cmd == "update_card" and len(sys.argv) >= 4:
            mid, card_json_str = sys.argv[2], " ".join(sys.argv[3:])
            card = json.loads(card_json_str)
            r = update_card(mid, card)
            print(f"[OK] 卡片已更新")

        elif cmd == "at" and len(sys.argv) >= 4:
            if len(sys.argv) >= 5 and _is_chat_id(sys.argv[2]):
                chat_id, oid, text = sys.argv[2], sys.argv[3], " ".join(sys.argv[4:])
            else:
                chat_id, oid, text = None, sys.argv[2], " ".join(sys.argv[3:])
            r = send_at_message(chat_id, oid, text)
            print(f"[OK] message_id={r['data']['message_id']}")

        elif cmd == "urgent_app" and len(sys.argv) >= 4:
            mid, oid = sys.argv[2], sys.argv[3]
            r = urgent_app(mid, [oid])
            print(f"[OK] 应用内加急已发送")

        elif cmd == "urgent_phone" and len(sys.argv) >= 4:
            mid, oid = sys.argv[2], sys.argv[3]
            r = urgent_phone(mid, [oid])
            print(f"[OK] 电话加急已发送")

        elif cmd == "urgent_sms" and len(sys.argv) >= 4:
            mid, oid = sys.argv[2], sys.argv[3]
            r = urgent_sms(mid, [oid])
            print(f"[OK] 短信加急已发送")

        elif cmd == "history":
            chat_id = sys.argv[2] if len(sys.argv) >= 3 and _is_chat_id(sys.argv[2]) else None
            msgs = get_chat_history(chat_id)
            print(f"共 {len(msgs)} 条消息")
            for m in msgs[-10:]:
                sender = m.get("sender", {}).get("id", "?")
                mtype = m.get("msg_type", "?")
                print(f"  [{sender}] ({mtype}) {m.get('message_id', '')}")

        elif cmd == "members":
            chat_id = sys.argv[2] if len(sys.argv) >= 3 and _is_chat_id(sys.argv[2]) else None
            members = get_chat_members(chat_id)
            print(f"共 {len(members)} 个成员")
            for m in members:
                print(f"  {m.get('name', '')} | {m.get('member_id', '')}")

        elif cmd == "find_member" and len(sys.argv) >= 3:
            if len(sys.argv) >= 4 and _is_chat_id(sys.argv[2]):
                chat_id, name = sys.argv[2], sys.argv[3]
            else:
                chat_id, name = None, sys.argv[2]
            member = find_member_by_name(chat_id, name)
            if member:
                print(f"[OK] {member.get('name', '')} | {member.get('member_id', '')}")
            else:
                print(f"[NOT FOUND] 未找到匹配「{name}」的成员")

        elif cmd == "get_message" and len(sys.argv) >= 3:
            mid = sys.argv[2]
            msg = get_message(mid)
            print(json.dumps(msg, indent=2, ensure_ascii=False))

        else:
            print(f"未知命令或参数不足: {cmd}")
            print(f"可用命令: {', '.join(all_commands)}")
            print("运行 python3 feishu_api.py 查看帮助")

    except json.JSONDecodeError as e:
        print(f"[ERROR] JSON 解析失败: {e}")
    except RuntimeError as e:
        print(f"[ERROR] {e}")
    except Exception as e:
        print(f"[ERROR] 未预期的错误: {type(e).__name__}: {e}")


if __name__ == "__main__":
    _cli()
