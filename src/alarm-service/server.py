#!/usr/bin/env python3
"""
alarm-service — 报警消息中转与监听服务

功能：
  1. POST /webhook/grafana  — 接收 OnCall Outgoing Webhook，通过飞书 App Bot 发送卡片消息
  2. 飞书长连接 (WebSocket) — 接收卡片交互回调 (card.action.trigger)，执行 ACK/Silence/Resolve
  3. 飞书长连接 (WebSocket) — 接收群消息事件 (im.message.receive_v1)，自动回复
  4. GET  /health           — 健康检查

架构：
  Grafana 告警规则 → OnCall → Escalation Chain → Outgoing Webhook → alarm-service → 飞书 App Bot 卡片消息
  飞书卡片按钮点击 → 飞书 WebSocket 长连接 → alarm-service → OnCall API（ACK/Silence/Resolve）

依赖：lark-oapi (飞书 SDK，用于 WebSocket 长连接)、feishu_api.py (发消息)
"""

import base64
import json
import logging
import mimetypes
import os
import re
import sys
import threading
import time
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

try:
    import feishu_api
except ImportError:
    _PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
    _FEISHU_API_DIR = _PROJECT_ROOT / ".trae" / "skills" / "feishu-messenger"
    if str(_FEISHU_API_DIR) not in sys.path:
        sys.path.insert(0, str(_FEISHU_API_DIR))
    import feishu_api

import lark_oapi as lark
from lark_oapi.event.callback.model.p2_card_action_trigger import (
    P2CardActionTrigger,
    P2CardActionTriggerResponse,
)

import problem_manager as pm

PORT = int(os.environ.get("ALARM_SERVICE_PORT", "9095"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

GRAFANA_URL = os.environ.get("GRAFANA_URL", "http://grafana:3000")
GRAFANA_PUBLIC_URL = os.environ.get("GRAFANA_PUBLIC_URL", "http://47.83.217.162:3000")
GRAFANA_USER = os.environ.get("GRAFANA_USER", "admin")
GRAFANA_PASSWORD = os.environ.get("GRAFANA_PASSWORD", "admin")

FEISHU_APP_ID = os.environ.get("app_id", "")
FEISHU_APP_SECRET = os.environ.get("app_secret", "")

# --- 日志 ---
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("alarm-service")

# --- 机器人自身 open_id（启动时自动获取，用于判断消息是否 @了机器人）---
_BOT_OPEN_ID: str = ""


def _fetch_bot_open_id() -> str:
    """
    通过飞书 API 获取机器人自身的 open_id。
    接口: GET /open-apis/bot/v3/info/
    需要 tenant_access_token，由 feishu_api.get_token() 提供。
    失败时返回空字符串并打印警告日志（不影响主流程启动）。
    """
    try:
        token = feishu_api.get_token()
        url = "https://open.feishu.cn/open-apis/bot/v3/info/"
        req = urllib.request.Request(url, method="GET", headers={
            "Authorization": f"Bearer {token}",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        if data.get("code") != 0:
            logger.warning("获取机器人信息失败: code=%s, msg=%s", data.get("code"), data.get("msg"))
            return ""
        open_id = data.get("bot", {}).get("open_id", "")
        if open_id:
            logger.info("获取机器人 open_id 成功: %s", open_id[:12] + "***")
        else:
            logger.warning("机器人信息中无 open_id，@检测将不可用")
        return open_id
    except Exception as e:
        logger.warning("获取机器人 open_id 异常（不影响主流程）: %s", e)
        return ""


# --- 告警消息缓存（message_id -> alert 信息映射）---
_alert_message_cache: dict[str, dict] = {}
_CACHE_MAX_SIZE = 1000


def _cache_alert_message(message_id: str, alert_info: dict):
    if len(_alert_message_cache) >= _CACHE_MAX_SIZE:
        oldest_key = next(iter(_alert_message_cache))
        del _alert_message_cache[oldest_key]
    _alert_message_cache[message_id] = alert_info


# ============================================================
# OnCall API 工具函数
# ============================================================

def _format_delay(seconds: int) -> str:
    """将秒数转换为人类可读的时间文本"""
    if seconds >= 3600:
        return f"{seconds // 3600}h"
    return f"{seconds // 60}min"


def _oncall_api(method: str, path: str, body: dict = None) -> dict:
    """
    通过 Grafana plugin proxy 调用 OnCall API。
    path 示例: "alertgroups/XXXX/acknowledge/"
    """
    url = f"{GRAFANA_URL}/api/plugins/grafana-oncall-app/resources/{path}"
    credentials = base64.b64encode(f"{GRAFANA_USER}:{GRAFANA_PASSWORD}".encode()).decode()
    headers = {
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode() if body else None

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp_body = resp.read().decode("utf-8")
            return json.loads(resp_body) if resp_body.strip() else {}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        logger.error(
            "OnCall API 调用失败: method=%s, path=%s, status=%d, body=%s",
            method, path, e.code, error_body[:500]
        )
        raise
    except Exception as e:
        logger.error("OnCall API 请求异常: method=%s, path=%s, error=%s", method, path, e)
        raise


# ============================================================
# 飞书卡片构建
# ============================================================

def _severity_color(status: str, severity: str = "") -> str:
    if status == "resolved":
        return "green"
    if severity == "critical":
        return "red"
    return "orange"


def _severity_emoji(status: str, severity: str = "") -> str:
    if status == "resolved":
        return "✅"
    if severity == "critical":
        return "🔴"
    return "🟡"


SILENCE_PRESETS = [
    {"label": "30m", "seconds": 1800},
    {"label": "2h", "seconds": 7200},
]


def build_alert_card(alert: dict, common_labels: dict = None,
                     alert_group_id: str = "", oncall_meta: dict = None) -> dict:
    """
    将单条告警构建为飞书交互卡片 JSON。
    卡片包含：告警基本信息、Alert Group ID、查看详情链接、ACK / Silence / Resolve 操作按钮。
    """
    status = alert.get("status", "firing")
    labels = alert.get("labels", {})
    annotations = alert.get("annotations", {})

    alert_name = labels.get("alertname", "Unknown Alert")
    severity = labels.get("severity", "warning")
    service = labels.get("service_name", labels.get("service", "unknown"))
    summary = annotations.get("summary", "")
    description = annotations.get("description", "")

    status_text = "已恢复" if status == "resolved" else "告警触发"
    emoji = _severity_emoji(status, severity)
    color = _severity_color(status, severity)

    header = {
        "template": color,
        "title": {"tag": "plain_text", "content": f"{emoji} [{status_text}] {alert_name}"},
    }

    elements = []

    # 基本信息：两列布局
    info_fields = []
    if service and service != "unknown":
        info_fields.append(f"**服务**: {service}")
    if severity:
        info_fields.append(f"**级别**: {severity}")

    time_str = alert.get("startsAt", "")
    if status == "resolved":
        time_str = alert.get("endsAt", time_str)
    if time_str:
        display_time = time_str.replace("T", " ").split(".")[0].replace("Z", " UTC")
        info_fields.append(f"**时间**: {display_time}")

    if alert_group_id:
        info_fields.append(f"**Alert Group**: `{alert_group_id}`")

    # 每行两个字段
    for i in range(0, len(info_fields), 2):
        cols = []
        for field_text in info_fields[i:i + 2]:
            cols.append({
                "tag": "column", "width": "weighted", "weight": 1,
                "elements": [{"tag": "markdown", "content": field_text}],
            })
        elements.append({"tag": "column_set", "flex_mode": "bisect", "columns": cols})

    elements.append({"tag": "hr"})

    if summary:
        elements.append({"tag": "markdown", "content": f"**摘要**: {summary}"})
    if description:
        elements.append({"tag": "markdown", "content": f"**详情**: {description}"})

    extra_labels = {k: v for k, v in labels.items()
                    if k not in ("alertname", "severity", "service_name", "service", "grafana_folder")}
    if extra_labels:
        label_text = " | ".join(f"`{k}={v}`" for k, v in extra_labels.items())
        elements.append({"tag": "markdown", "content": f"**标签**: {label_text}"})

    elements.append({"tag": "hr"})

    # 操作按钮行 1：查看详情 / ACK / Resolve
    # 必须使用 behaviors 字段，因为飞书后台订阅的是新版 card.action.trigger 回调
    # value 字段会走旧版 card.action.trigger_v1，不会推送到长连接
    actions_row = []

    if alert_group_id:
        detail_url = (
            f"{GRAFANA_PUBLIC_URL}/a/grafana-oncall-app/alert-groups/{alert_group_id}"
        )
        actions_row.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "📋 查看详情"},
            "type": "primary",
            "behaviors": [{"type": "open_url", "default_url": detail_url}],
        })

    if status != "resolved" and alert_group_id:
        actions_row.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "✅ ACK"},
            "type": "default",
            "behaviors": [{"type": "callback", "value": {"action": "acknowledge", "alert_group_id": alert_group_id}}],
        })
        actions_row.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "🔇 Resolve"},
            "type": "danger",
            "behaviors": [{"type": "callback", "value": {"action": "resolve", "alert_group_id": alert_group_id}}],
        })

    if actions_row:
        elements.append({"tag": "action", "actions": actions_row})

    # 操作按钮行 2：Silence 预设时间按钮
    if status != "resolved" and alert_group_id:
        silence_row = []
        for preset in SILENCE_PRESETS:
            silence_row.append({
                "tag": "button",
                "text": {"tag": "plain_text", "content": f"⏸️ Silence {preset['label']}"},
                "type": "default",
                "behaviors": [{"type": "callback", "value": {
                    "action": "silence",
                    "alert_group_id": alert_group_id,
                    "delay": preset["seconds"],
                }}],
            })
        elements.append({"tag": "action", "actions": silence_row})

    card = {
        "config": {"update_multi": True, "wide_screen_mode": True},
        "header": header,
        "elements": elements,
    }
    return card


# ============================================================
# Grafana Webhook 处理
# ============================================================

def _normalize_oncall_payload(payload: dict) -> dict:
    """
    将 OnCall Outgoing Webhook 的 payload 转换为标准格式，并保留 OnCall 元信息。

    返回的 dict 中注入 _oncall_meta 字段，包含 alert_group_id 等信息，
    供 build_alert_card 使用。
    """
    alert_payload = payload.get("alert_payload", {})
    alert_group = payload.get("alert_group", {})
    oncall_event = payload.get("event", {})
    alert_group_id = payload.get("alert_group_id", "")

    oncall_meta = {
        "event_type": oncall_event.get("type", ""),
        "integration": payload.get("integration", {}),
        "alert_group_id": alert_group_id,
    }

    if isinstance(alert_payload, dict) and "alerts" in alert_payload:
        logger.info(
            "OnCall payload 包含原始 Grafana alerts 数据: alert_count=%d, alert_group_id=%s",
            len(alert_payload.get("alerts", [])), alert_group_id,
        )
        alert_payload["_oncall_meta"] = oncall_meta
        return alert_payload

    ag_state = alert_group.get("state", "firing")
    status = "resolved" if ag_state == "resolved" else "firing"

    alert_entry = {
        "status": status,
        "labels": alert_payload.get("labels", {}) if isinstance(alert_payload, dict) else {},
        "annotations": alert_payload.get("annotations", {}) if isinstance(alert_payload, dict) else {},
        "startsAt": alert_group.get("created_at", ""),
        "endsAt": alert_group.get("resolved_at", ""),
        "generatorURL": alert_group.get("alert_group_url", ""),
    }

    if isinstance(alert_payload, dict):
        for key in ("startsAt", "endsAt", "generatorURL", "silenceURL", "dashboardURL", "panelURL"):
            if key in alert_payload and alert_payload[key]:
                alert_entry[key] = alert_payload[key]

    logger.info(
        "OnCall payload 转换为标准格式: status=%s, alert_name=%s, alert_group_id=%s",
        status, alert_entry["labels"].get("alertname", "unknown"), alert_group_id,
    )

    return {
        "status": status,
        "alerts": [alert_entry],
        "commonLabels": alert_entry["labels"],
        "groupKey": alert_group_id,
        "_oncall_meta": oncall_meta,
    }


def handle_grafana_webhook(payload: dict) -> dict:
    """
    处理告警 Webhook 请求。

    支持两种 payload 格式：
    1. OnCall Outgoing Webhook（包含 alert_payload 和 alert_group 字段）
    2. Grafana Alerting 直接 Webhook（包含 alerts 数组）
    """
    alert_group_id = ""
    oncall_meta = {}

    if "alert_payload" in payload and "alert_group" in payload:
        logger.info(
            "检测到 OnCall Outgoing Webhook payload: event_type=%s, alert_group_id=%s",
            payload.get("event", {}).get("type", ""),
            payload.get("alert_group_id", ""),
        )
        alert_group_id = payload.get("alert_group_id", "")
        payload = _normalize_oncall_payload(payload)
        oncall_meta = payload.get("_oncall_meta", {})

    alerts = payload.get("alerts", [])
    status = payload.get("status", "unknown")
    common_labels = payload.get("commonLabels", {})
    group_key = payload.get("groupKey", "")

    logger.info(
        "处理告警: status=%s, alerts=%d, groupKey=%s, alert_group_id=%s",
        status, len(alerts), group_key, alert_group_id,
    )

    results = []
    for alert in alerts:
        try:
            card = build_alert_card(
                alert, common_labels,
                alert_group_id=alert_group_id,
                oncall_meta=oncall_meta,
            )
            resp = feishu_api.send_card(card=card)
            message_id = resp.get("data", {}).get("message_id", "")

            alert_info = {
                "alert_name": alert.get("labels", {}).get("alertname", ""),
                "status": alert.get("status", ""),
                "labels": alert.get("labels", {}),
                "annotations": alert.get("annotations", {}),
                "alert_group_id": alert_group_id,
                "received_at": time.time(),
            }
            if message_id:
                _cache_alert_message(message_id, alert_info)

            logger.info(
                "飞书卡片已发送: alert=%s, status=%s, message_id=%s, alert_group_id=%s",
                alert_info["alert_name"], alert_info["status"], message_id, alert_group_id,
            )

            # 卡片发送成功后，在话题中自动回复确认语
            if message_id and status != "resolved":
                try:
                    thread_text = (
                        f"🤖 值班虚拟员工已收到告警，正在待命中。\n"
                        f"如需协助请在此话题中回复。"
                    )
                    thread_resp = feishu_api.reply_in_thread(message_id, thread_text)
                    thread_msg_id = thread_resp.get("data", {}).get("message_id", "")
                    logger.info(
                        "已话题回复告警卡片: card_msg=%s, thread_msg=%s",
                        message_id, thread_msg_id,
                    )
                except Exception as te:
                    logger.error(
                        "话题回复告警卡片失败: message_id=%s, error=%s",
                        message_id, te, exc_info=True,
                    )

            results.append({"alert": alert_info["alert_name"], "message_id": message_id, "ok": True})

        except Exception as e:
            alert_name = alert.get("labels", {}).get("alertname", "unknown")
            logger.error("发送飞书卡片失败: alert=%s, error=%s", alert_name, e, exc_info=True)
            results.append({"alert": alert_name, "ok": False, "error": str(e)})

    return {"received": len(alerts), "results": results}


# ============================================================
# 飞书长连接回调处理（卡片交互 + 群消息）
# ============================================================

def _do_card_action_trigger(data: P2CardActionTrigger) -> P2CardActionTriggerResponse:
    """
    飞书卡片交互回调处理函数（通过 WebSocket 长连接接收）。
    处理 ACK / Silence / Resolve 按钮点击。
    同时兼容 value（JSON 1.0）和 behaviors（JSON 2.0）两种回调模式。
    """
    event = data.event
    action = event.action if event else None
    if not action:
        logger.warning("卡片回调 event 或 action 为空")
        return P2CardActionTriggerResponse({"toast": {"type": "error", "content": "无效的操作"}})

    tag = action.tag or ""
    open_id = event.operator.open_id if event.operator else "unknown"

    value = action.value or {}

    logger.info(
        "卡片回调原始数据: tag=%s, value=%s, option=%s, user=%s",
        tag, json.dumps(value, ensure_ascii=False), getattr(action, 'option', ''), open_id,
    )

    action_type = value.get("action", "")
    alert_group_id = value.get("alert_group_id", "")

    # ---- 审批卡片回调（approval_confirm / approval_reject）----
    approval_id = value.get("approval_id", "")
    if action_type in ("approval_confirm", "approval_reject") and approval_id:
        toast_text = feishu_api.handle_approval_callback(action_type, approval_id, open_id)
        logger.info(
            "审批卡片回调: action=%s, approval_id=%s, operator=%s",
            action_type, approval_id, open_id,
        )
        return P2CardActionTriggerResponse(
            {"toast": {"type": "success" if "批准" in toast_text else "info", "content": toast_text}}
        )

    if not alert_group_id:
        logger.warning("卡片回调缺少 alert_group_id: tag=%s, value=%s", tag, value)
        return P2CardActionTriggerResponse({"toast": {"type": "error", "content": "缺少告警 ID"}})

    logger.info(
        "飞书卡片操作: action=%s, alert_group_id=%s, user=%s, tag=%s",
        action_type, alert_group_id, open_id, tag,
    )

    try:
        if action_type == "acknowledge":
            _oncall_api("POST", f"alertgroups/{alert_group_id}/acknowledge/")
            logger.info("ACK 成功: alert_group_id=%s, operator=%s", alert_group_id, open_id)
            return P2CardActionTriggerResponse(
                {"toast": {"type": "success", "content": "✅ ACK 成功"}}
            )

        elif action_type == "resolve":
            _oncall_api("POST", f"alertgroups/{alert_group_id}/resolve/")
            logger.info("Resolve 成功: alert_group_id=%s, operator=%s", alert_group_id, open_id)
            return P2CardActionTriggerResponse(
                {"toast": {"type": "success", "content": "✅ Resolve 成功"}}
            )

        elif action_type == "silence":
            # Silence 按钮：delay 直接从 value 中获取
            delay = int(value.get("delay", 1800))
            _oncall_api("POST", f"alertgroups/{alert_group_id}/silence/", {"delay": delay})
            delay_text = _format_delay(delay)
            logger.info("Silence 成功: alert_group_id=%s, delay=%s, operator=%s",
                        alert_group_id, delay_text, open_id)
            return P2CardActionTriggerResponse(
                {"toast": {"type": "success", "content": f"✅ Silence {delay_text}"}}
            )

        else:
            logger.warning("未知操作类型: %s", action_type)
            return P2CardActionTriggerResponse(
                {"toast": {"type": "error", "content": f"未知操作: {action_type}"}}
            )

    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        logger.error(
            "OnCall 操作失败: action=%s, alert_group_id=%s, status=%d, body=%s",
            action_type, alert_group_id, e.code, error_body[:300],
        )
        return P2CardActionTriggerResponse(
            {"toast": {"type": "error", "content": f"操作失败: HTTP {e.code}"}}
        )
    except Exception as e:
        logger.error("OnCall 操作异常: action=%s, error=%s", action_type, e, exc_info=True)
        return P2CardActionTriggerResponse(
            {"toast": {"type": "error", "content": f"操作异常: {e}"}}
        )


def _is_bot_mentioned(message) -> bool:
    """
    检查消息是否 @了机器人。
    MentionEvent.id 类型是 UserId 对象（含 open_id/user_id/union_id），
    需要用 mention.id.open_id 与 _BOT_OPEN_ID 比对。
    如果 _BOT_OPEN_ID 未获取到（为空），则回退为不匹配，避免误触发。
    """
    global _BOT_OPEN_ID
    if not _BOT_OPEN_ID:
        logger.debug("_BOT_OPEN_ID 为空，跳过 @检测")
        return False

    mentions = getattr(message, 'mentions', None)
    if not mentions:
        logger.debug("消息无 mentions 字段，message_id=%s", getattr(message, 'message_id', '?'))
        return False

    for mention in mentions:
        user_id_obj = getattr(mention, 'id', None)
        if user_id_obj is None:
            continue
        mention_open_id = getattr(user_id_obj, 'open_id', None)
        mention_key = getattr(mention, 'key', None)
        mention_name = getattr(mention, 'name', None)
        logger.info(
            "@检测: mention.open_id=%s, mention.key=%s, mention.name=%s, bot_open_id=%s, match=%s",
            mention_open_id, mention_key, mention_name, _BOT_OPEN_ID,
            mention_open_id == _BOT_OPEN_ID if mention_open_id else False
        )
        if mention_open_id and mention_open_id == _BOT_OPEN_ID:
            return True

    return False


def _strip_mention_placeholders(text: str) -> str:
    """
    去除消息文本中的 @_user_N 占位符（如 "@_user_1"），只保留用户真正输入的内容。
    飞书消息中 @人 会以 @_user_1 这样的占位符出现在 text 里。
    """
    import re
    return re.sub(r'@_user_\d+\s*', '', text).strip()


def _do_message_receive(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
    """
    飞书群消息事件处理函数（通过 WebSocket 长连接接收）。

    回复策略：
      1. 在告警卡片话题中的回复（parent_id 命中缓存）→ 不需要 @，直接回复
      2. 普通群消息 → 只有明确 @机器人 时才回复
      3. 机器人自身发的消息 → 忽略
    """
    event = data.event
    if not event or not event.message:
        return

    message = event.message
    sender = event.sender

    message_id = message.message_id or ""
    chat_id = message.chat_id or ""
    msg_type = message.message_type or ""
    content_str = message.content or "{}"

    sender_type = sender.sender_type if sender else ""
    sender_id = sender.sender_id.open_id if sender and sender.sender_id else "unknown"

    if sender_type == "app":
        logger.debug("忽略机器人自身消息: message_id=%s", message_id)
        return

    logger.info(
        "收到群消息: chat_id=%s, message_id=%s, type=%s, sender=%s",
        chat_id, message_id, msg_type, sender_id
    )

    try:
        content = json.loads(content_str)
        text = content.get("text", "").strip()
    except (json.JSONDecodeError, AttributeError):
        text = ""

    if not text:
        return

    parent_id = message.parent_id or ""
    alert_context = _alert_message_cache.get(parent_id)
    bot_mentioned = _is_bot_mentioned(message)

    if not bot_mentioned:
        logger.debug("消息未@机器人，忽略: message_id=%s", message_id)
        return

    clean_text = _strip_mention_placeholders(text)

    if alert_context:
        reply_text = (
            f"📋 已收到你对告警 **{alert_context['alert_name']}** 的回复。\n"
            f"告警状态: {alert_context['status']}\n"
            f"你的消息: {clean_text}\n\n"
            f"（值班虚拟员工已记录，后续将自动分析并给出处置建议）"
        )
    else:
        reply_text = (
            f"👋 已收到消息: {clean_text}\n\n"
            f"（值班虚拟员工在线，如需处理告警请直接回复告警卡片消息）"
        )

    try:
        resp = feishu_api.reply_in_thread(message_id, reply_text)
        reply_msg_id = resp.get("data", {}).get("message_id", "")
        logger.info("已话题回复消息: original=%s, reply=%s", message_id, reply_msg_id)
    except Exception as e:
        logger.error("话题回复消息失败: message_id=%s, error=%s", message_id, e, exc_info=True)


def _do_card_action_trigger_v1(data):
    """
    飞书卡片交互回调处理函数（旧版 card.action.trigger_v1）。
    当按钮使用 value 字段（JSON 1.0）时，飞书可能通过此事件发送回调。
    将数据转发给新版处理函数。
    """
    logger.info("收到旧版卡片回调 card.action.trigger_v1: %s", type(data).__name__)

    try:
        raw = data.raw if hasattr(data, 'raw') else None
        event_data = data.event if hasattr(data, 'event') else None

        if raw:
            logger.info("旧版回调原始数据(raw): %s", json.dumps(raw, ensure_ascii=False)[:500] if isinstance(raw, dict) else str(raw)[:500])

        if event_data:
            raw_event = event_data.__dict__ if hasattr(event_data, '__dict__') else str(event_data)
            logger.info("旧版回调事件数据(event): %s", str(raw_event)[:500])

        action = event_data.action if event_data and hasattr(event_data, 'action') else None
        if action:
            value = action.value if hasattr(action, 'value') and action.value else {}
            tag = action.tag if hasattr(action, 'tag') else ""
            open_id = "unknown"
            if event_data and hasattr(event_data, 'operator') and event_data.operator:
                open_id = event_data.operator.open_id if hasattr(event_data.operator, 'open_id') else "unknown"

            logger.info(
                "旧版回调解析: tag=%s, value=%s, user=%s",
                tag, json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else str(value), open_id,
            )

            action_type = value.get("action", "") if isinstance(value, dict) else ""
            alert_group_id = value.get("alert_group_id", "") if isinstance(value, dict) else ""

            if action_type and alert_group_id:
                logger.info("旧版回调转发: action=%s, alert_group_id=%s", action_type, alert_group_id)
                return _do_card_action_trigger(data)

    except Exception as e:
        logger.error("旧版回调处理异常: %s", e, exc_info=True)


def _patch_ws_client_for_card_callback(cli):
    """
    Monkey-patch lark-oapi ws.Client._handle_data_frame，
    修复 MessageType.CARD 消息被丢弃的 bug。

    SDK 原始代码中 _handle_data_frame 对 MessageType.CARD 直接 return，
    导致卡片交互回调（card.action.trigger）无法到达 event_handler。
    补丁让 CARD 消息与 EVENT 消息走相同的 do_without_validation 路径。
    """
    import http as _http
    import time as _time
    import base64 as _b64
    import lark_oapi.ws.client as _ws_mod

    _MessageType = _ws_mod.MessageType
    _UTF8 = "utf-8"

    async def _patched_handle_data_frame(frame):
        hs = frame.headers
        msg_id = _ws_mod._get_by_key(hs, _ws_mod.HEADER_MESSAGE_ID)
        trace_id = _ws_mod._get_by_key(hs, _ws_mod.HEADER_TRACE_ID)
        sum_ = _ws_mod._get_by_key(hs, _ws_mod.HEADER_SUM)
        seq = _ws_mod._get_by_key(hs, _ws_mod.HEADER_SEQ)
        type_ = _ws_mod._get_by_key(hs, _ws_mod.HEADER_TYPE)

        pl = frame.payload
        if int(sum_) > 1:
            pl = cli._combine(msg_id, int(sum_), int(seq), pl)
            if pl is None:
                return

        message_type = _MessageType(type_)

        resp = _ws_mod.Response(code=_http.HTTPStatus.OK)
        try:
            start = int(round(_time.time() * 1000))
            if message_type == _MessageType.EVENT:
                result = cli._event_handler.do_without_validation(pl)
            elif message_type == _MessageType.CARD:
                # --- 补丁核心：CARD 也走 event_handler ---
                logger.info(
                    "收到卡片交互回调(CARD): msg_id=%s, trace_id=%s",
                    msg_id, trace_id,
                )
                result = cli._event_handler.do_without_validation(pl)
            else:
                return
            end = int(round(_time.time() * 1000))

            header = hs.add()
            header.key = _ws_mod.HEADER_BIZ_RT
            header.value = str(end - start)
            if result is not None:
                resp.data = _b64.b64encode(
                    _ws_mod.JSON.marshal(result).encode(_UTF8)
                )
        except Exception as e:
            logger.error(
                "处理消息失败: type=%s, msg_id=%s, trace_id=%s, error=%s",
                message_type.value, msg_id, trace_id, e, exc_info=True,
            )
            resp = _ws_mod.Response(code=_http.HTTPStatus.INTERNAL_SERVER_ERROR)

        frame.payload = _ws_mod.JSON.marshal(resp).encode(_UTF8)
        await cli._write_message(frame.SerializeToString())

    cli._handle_data_frame = _patched_handle_data_frame
    logger.info("已 patch ws.Client._handle_data_frame 以支持 MessageType.CARD 回调")


def _start_feishu_ws_client():
    """
    启动飞书 WebSocket 长连接客户端（在后台线程中运行）。
    注册 card.action.trigger 和 im.message.receive_v1 回调。

    注意：lark-oapi SDK 的 ws.Client._handle_data_frame 对 MessageType.CARD
    直接 return 不处理，导致卡片交互回调无法到达 event_handler。
    这里通过 monkey-patch 修复此问题，让 CARD 消息也走 event_handler。
    """
    if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
        logger.warning("飞书 app_id 或 app_secret 未配置，跳过 WebSocket 长连接")
        return

    event_handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_card_action_trigger(_do_card_action_trigger)
        .register_p2_customized_event("card.action.trigger_v1", _do_card_action_trigger_v1)
        .register_p2_im_message_receive_v1(_do_message_receive)
        .build()
    )

    lark_log_level = lark.LogLevel.INFO
    if LOG_LEVEL == "DEBUG":
        lark_log_level = lark.LogLevel.DEBUG

    cli = lark.ws.Client(
        FEISHU_APP_ID,
        FEISHU_APP_SECRET,
        event_handler=event_handler,
        log_level=lark_log_level,
    )

    _patch_ws_client_for_card_callback(cli)

    logger.info("飞书 WebSocket 长连接客户端启动中... app_id=%s", FEISHU_APP_ID[:8] + "***")
    try:
        cli.start()
    except Exception as e:
        logger.error("飞书 WebSocket 长连接异常退出: %s", e, exc_info=True)


# ============================================================
# HTTP Server
# ============================================================

# H5 静态文件目录
STATIC_DIR = Path(__file__).parent / "static"


class AlarmServiceHandler(BaseHTTPRequestHandler):
    """HTTP 请求处理器，包含 Webhook API、Problem REST API、H5 静态文件服务。"""

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "ok", "service": "alarm-service"})

        # --- Problem REST API ---
        elif self.path == "/api/problems" or self.path.startswith("/api/problems?"):
            self._handle_get_problems()

        elif re.match(r"^/api/problems/P-\d+$", self.path):
            problem_id = self.path.split("/")[-1]
            self._handle_get_problem_detail(problem_id)

        # --- H5 静态文件服务 ---
        elif self.path.startswith("/static/"):
            self._serve_static_file()

        # --- 根路径重定向到 H5 页面 ---
        elif self.path == "/" or self.path == "/problems":
            self.send_response(302)
            self.send_header("Location", "/static/problem.html")
            self.end_headers()

        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))

        # --- Problem API: 审批动作（approve/reject） ---
        approve_match = re.match(r"^/api/problems/(P-\d+)/actions/([^/]+)/approve$", self.path)
        reject_match = re.match(r"^/api/problems/(P-\d+)/actions/([^/]+)/reject$", self.path)

        if approve_match:
            problem_id, action_id = approve_match.groups()
            operator = "user"
            if content_length > 0:
                try:
                    body = json.loads(self.rfile.read(content_length).decode("utf-8"))
                    operator = body.get("operator", "user")
                except Exception:
                    pass
            self._handle_approve_action(problem_id, action_id, operator)
            return

        if reject_match:
            problem_id, action_id = reject_match.groups()
            operator = "user"
            if content_length > 0:
                try:
                    body = json.loads(self.rfile.read(content_length).decode("utf-8"))
                    operator = body.get("operator", "user")
                except Exception:
                    pass
            self._handle_reject_action(problem_id, action_id, operator)
            return

        # --- 原有 Webhook API ---
        if content_length == 0:
            self._send_json(400, {"error": "empty body"})
            return

        try:
            body = self.rfile.read(content_length)
            payload = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error("请求体解析失败: %s", e)
            self._send_json(400, {"error": f"invalid JSON: {e}"})
            return

        if self.path == "/webhook/grafana":
            result = handle_grafana_webhook(payload)
            self._send_json(200, result)

        else:
            self._send_json(404, {"error": "not found"})

    def do_OPTIONS(self):
        """处理 CORS 预检请求。"""
        self.send_response(200)
        self._add_cors_headers()
        self.end_headers()

    # --- Problem API 处理函数 ---

    def _handle_get_problems(self):
        """GET /api/problems?status=xxx — 获取问题列表。"""
        manager = pm.get_manager()

        # 解析 query string 中的 status 参数
        status_filter = None
        if "?" in self.path:
            query = self.path.split("?", 1)[1]
            for param in query.split("&"):
                if param.startswith("status="):
                    status_filter = param.split("=", 1)[1]

        if status_filter and status_filter in pm.ALL_STATUSES:
            problems = manager.get_problems_by_status(status_filter)
        else:
            problems = manager.get_all_problems()

        result = {
            "total": len(problems),
            "problems": [p.to_dict() for p in problems],
        }
        self._send_json(200, result)

    def _handle_get_problem_detail(self, problem_id: str):
        """GET /api/problems/:id — 获取问题详情。"""
        manager = pm.get_manager()
        problem = manager.get_problem(problem_id)

        if not problem:
            self._send_json(404, {"error": f"问题 {problem_id} 不存在"})
            return

        self._send_json(200, problem.to_dict())

    def _handle_approve_action(self, problem_id: str, action_id: str, operator: str):
        """POST /api/problems/:id/actions/:actionId/approve — 审批通过。"""
        manager = pm.get_manager()
        action = manager.approve_action(problem_id, action_id, operator)

        if not action:
            self._send_json(400, {"error": "审批失败：问题或动作不存在，或动作非 pending 状态"})
            return

        problem = manager.get_problem(problem_id)
        self._send_json(200, {
            "message": f"动作「{action.description}」已批准执行",
            "action": action.to_dict(),
            "problem_status": problem.status if problem else "unknown",
        })

    def _handle_reject_action(self, problem_id: str, action_id: str, operator: str):
        """POST /api/problems/:id/actions/:actionId/reject — 取消动作。"""
        manager = pm.get_manager()
        action = manager.reject_action(problem_id, action_id, operator)

        if not action:
            self._send_json(400, {"error": "取消失败：问题或动作不存在，或动作非 pending 状态"})
            return

        problem = manager.get_problem(problem_id)
        self._send_json(200, {
            "message": f"动作「{action.description}」已取消",
            "action": action.to_dict(),
            "problem_status": problem.status if problem else "unknown",
        })

    # --- 静态文件服务 ---

    def _serve_static_file(self):
        """提供 /static/ 目录下的 H5 文件。"""
        # 去掉 /static/ 前缀，映射到文件系统
        relative_path = self.path[len("/static/"):]
        # 安全检查：防止路径穿越
        if ".." in relative_path or relative_path.startswith("/"):
            self._send_json(403, {"error": "forbidden"})
            return

        file_path = STATIC_DIR / relative_path
        if not file_path.exists() or not file_path.is_file():
            self._send_json(404, {"error": "file not found"})
            return

        content_type, _ = mimetypes.guess_type(str(file_path))
        if content_type is None:
            content_type = "application/octet-stream"

        try:
            with open(file_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self._add_cors_headers()
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            logger.error("读取静态文件失败 %s: %s", file_path, e)
            self._send_json(500, {"error": "internal server error"})

    # --- 工具方法 ---

    def _send_json(self, status_code: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._add_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _add_cors_headers(self):
        """添加 CORS 响应头，允许 H5 页面跨域调用 API。"""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, format, *args):
        """覆盖默认日志，使用 logging 模块"""
        logger.debug("%s %s", self.client_address[0], format % args)


def main():
    global _BOT_OPEN_ID
    # 启动时获取机器人自身 open_id（用于 @检测）
    _BOT_OPEN_ID = _fetch_bot_open_id()

    # 初始化 Problem Manager（加载持久化数据）
    manager = pm.get_manager()
    logger.info("Problem Manager 已初始化, 当前 %d 个问题", len(manager.get_all_problems()))

    # 在后台线程启动飞书 WebSocket 长连接（接收卡片交互 + 群消息回调）
    ws_thread = threading.Thread(target=_start_feishu_ws_client, daemon=True, name="feishu-ws")
    ws_thread.start()

    # 主线程启动 HTTP Server（接收 OnCall Outgoing Webhook）
    server = HTTPServer(("0.0.0.0", PORT), AlarmServiceHandler)
    logger.info("alarm-service 启动: port=%d", PORT)
    logger.info("  POST /webhook/grafana          — 接收 OnCall 告警 Webhook")
    logger.info("  GET  /api/problems             — Problem 列表 API")
    logger.info("  GET  /api/problems/:id         — Problem 详情 API")
    logger.info("  POST /api/problems/:id/actions/:aid/approve  — 审批通过")
    logger.info("  POST /api/problems/:id/actions/:aid/reject   — 取消动作")
    logger.info("  GET  /static/*                 — H5 静态文件")
    logger.info("  GET  /health                   — 健康检查")
    logger.info("  H5 页面: http://0.0.0.0:%d/static/problem.html", PORT)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("alarm-service 正在关闭...")
        server.shutdown()


if __name__ == "__main__":
    main()
