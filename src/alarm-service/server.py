#!/usr/bin/env python3
"""
alarm-service — 报警消息中转与监听服务

功能：
  1. POST /webhook/grafana  — 接收 OnCall Outgoing Webhook / Grafana Webhook，通过飞书 App Bot 发送卡片消息
  2. POST /webhook/feishu   — 接收飞书事件订阅回调，监听群消息并自动回复
  3. GET  /health           — 健康检查

架构：
  Grafana 告警规则 → OnCall → Escalation Chain → Outgoing Webhook → alarm-service → 飞书 App Bot 卡片消息
  飞书群消息 → 飞书事件订阅 → alarm-service → 同一个 App Bot 回复消息

依赖：仅使用 Python 标准库，无需安装第三方包。
飞书 API 调用复用项目中已有的 feishu_api.py 模块。
"""

import hashlib
import hmac
import json
import logging
import os
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional

# --- 加载 feishu_api 模块 ---
# Docker 容器中 feishu_api.py 在同目录；本地开发时在 .trae/skills/feishu-messenger/
try:
    import feishu_api
except ImportError:
    _PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
    _FEISHU_API_DIR = _PROJECT_ROOT / ".trae" / "skills" / "feishu-messenger"
    if str(_FEISHU_API_DIR) not in sys.path:
        sys.path.insert(0, str(_FEISHU_API_DIR))
    import feishu_api

# --- 配置 ---
PORT = int(os.environ.get("ALARM_SERVICE_PORT", "9095"))
FEISHU_VERIFICATION_TOKEN = os.environ.get("FEISHU_VERIFICATION_TOKEN", "")
FEISHU_ENCRYPT_KEY = os.environ.get("FEISHU_ENCRYPT_KEY", "")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# --- 日志 ---
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("alarm-service")

# --- 告警消息 ID 缓存（message_id -> alert 信息映射），用于回复时关联告警上下文 ---
# 简单内存缓存，最多保留 1000 条，生产环境应换为 Redis
_alert_message_cache: dict[str, dict] = {}
_CACHE_MAX_SIZE = 1000


def _cache_alert_message(message_id: str, alert_info: dict):
    """缓存告警消息 ID 与告警详情的映射关系"""
    if len(_alert_message_cache) >= _CACHE_MAX_SIZE:
        oldest_key = next(iter(_alert_message_cache))
        del _alert_message_cache[oldest_key]
    _alert_message_cache[message_id] = alert_info


# ============================================================
# 飞书卡片构建
# ============================================================

def _severity_color(status: str, severity: str = "") -> str:
    """根据告警状态和严重程度返回卡片颜色"""
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


def build_alert_card(alert: dict, common_labels: dict = None) -> dict:
    """
    将 Grafana Alerting 的单条告警构建为飞书卡片 JSON。

    Grafana Webhook payload 格式参考：
    https://grafana.com/docs/grafana/latest/alerting/configure-notifications/manage-contact-points/integrations/webhook-notifier/
    """
    status = alert.get("status", "firing")
    labels = alert.get("labels", {})
    annotations = alert.get("annotations", {})

    alert_name = labels.get("alertname", "Unknown Alert")
    severity = labels.get("severity", "warning")
    service = labels.get("service_name", labels.get("service", "unknown"))
    summary = annotations.get("summary", "")
    description = annotations.get("description", "")
    grafana_url = alert.get("generatorURL", "")
    silence_url = alert.get("silenceURL", "")
    dashboard_url = alert.get("dashboardURL", "")
    panel_url = alert.get("panelURL", "")

    status_text = "已恢复" if status == "resolved" else "告警触发"
    emoji = _severity_emoji(status, severity)
    color = _severity_color(status, severity)

    header = {
        "template": color,
        "title": {
            "tag": "plain_text",
            "content": f"{emoji} [{status_text}] {alert_name}"
        }
    }

    elements = []

    # 基本信息区域
    info_fields = []
    if service and service != "unknown":
        info_fields.append({"tag": "markdown", "content": f"**服务**: {service}"})
    if severity:
        info_fields.append({"tag": "markdown", "content": f"**级别**: {severity}"})

    time_str = alert.get("startsAt", "")
    if status == "resolved":
        time_str = alert.get("endsAt", time_str)
    if time_str:
        display_time = time_str.replace("T", " ").split(".")[0].replace("Z", " UTC")
        info_fields.append({"tag": "markdown", "content": f"**时间**: {display_time}"})

    if info_fields:
        elements.append({
            "tag": "column_set",
            "flex_mode": "bisect",
            "columns": [
                {"tag": "column", "width": "weighted", "weight": 1, "elements": [f]} for f in info_fields[:2]
            ]
        })
        if len(info_fields) > 2:
            elements.append({
                "tag": "column_set",
                "flex_mode": "bisect",
                "columns": [
                    {"tag": "column", "width": "weighted", "weight": 1, "elements": [f]} for f in info_fields[2:]
                ]
            })

    elements.append({"tag": "hr"})

    if summary:
        elements.append({"tag": "markdown", "content": f"**摘要**: {summary}"})
    if description:
        elements.append({"tag": "markdown", "content": f"**详情**: {description}"})

    # 标签展示
    extra_labels = {k: v for k, v in labels.items()
                    if k not in ("alertname", "severity", "service_name", "service", "grafana_folder")}
    if extra_labels:
        label_text = " | ".join(f"`{k}={v}`" for k, v in extra_labels.items())
        elements.append({"tag": "markdown", "content": f"**标签**: {label_text}"})

    elements.append({"tag": "hr"})

    # 操作按钮
    actions = []
    if grafana_url:
        actions.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "查看告警"},
            "type": "primary",
            "url": grafana_url
        })
    if silence_url:
        actions.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "一键静默"},
            "type": "default",
            "url": silence_url
        })
    if dashboard_url:
        actions.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "查看面板"},
            "type": "default",
            "url": dashboard_url
        })

    if actions:
        elements.append({"tag": "action", "actions": actions})

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
    将 OnCall Outgoing Webhook 的 payload 转换为 Grafana Alerting Webhook 的标准格式。

    OnCall payload 结构：
    {
      "event": {"type": "escalation", "time": "..."},
      "alert_group": {"id": "...", "state": "firing", ...},
      "alert_group_id": "...",
      "alert_payload": { /* Grafana Alerting 原始 payload */ },
      "integration": {"id": "...", "type": "grafana_alerting", ...},
      ...
    }

    其中 alert_payload 就是 Grafana Alerting 原始发给 OnCall 的数据。
    如果 alert_payload 本身已经是标准 Grafana webhook 格式（包含 alerts 数组），则直接返回。
    否则，将 OnCall 信息包装成单条告警。
    """
    alert_payload = payload.get("alert_payload", {})
    alert_group = payload.get("alert_group", {})
    oncall_event = payload.get("event", {})

    # Grafana Alerting 类型的 Integration，alert_payload 就是原始 Grafana 数据
    if isinstance(alert_payload, dict) and "alerts" in alert_payload:
        logger.info(
            "OnCall payload 包含原始 Grafana alerts 数据，直接使用: alert_count=%d",
            len(alert_payload.get("alerts", []))
        )
        return alert_payload

    # alert_payload 是单条告警的原始数据（非数组格式）
    # 从 alert_group 中提取状态信息，构造标准格式
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

    # 如果 alert_payload 中有嵌套的 Grafana 告警信息
    if isinstance(alert_payload, dict):
        for key in ("startsAt", "endsAt", "generatorURL", "silenceURL", "dashboardURL", "panelURL"):
            if key in alert_payload and alert_payload[key]:
                alert_entry[key] = alert_payload[key]

    logger.info(
        "OnCall payload 转换为标准格式: status=%s, alert_name=%s, alert_group_id=%s",
        status,
        alert_entry["labels"].get("alertname", "unknown"),
        payload.get("alert_group_id", ""),
    )

    return {
        "status": status,
        "alerts": [alert_entry],
        "commonLabels": alert_entry["labels"],
        "groupKey": payload.get("alert_group_id", ""),
        "_oncall_meta": {
            "event_type": oncall_event.get("type", ""),
            "integration": payload.get("integration", {}),
            "alert_group_id": payload.get("alert_group_id", ""),
        },
    }


def handle_grafana_webhook(payload: dict) -> dict:
    """
    处理告警 Webhook 请求。

    支持两种 payload 格式：
    1. OnCall Outgoing Webhook（包含 alert_payload 和 alert_group 字段）
    2. Grafana Alerting 直接 Webhook（包含 alerts 数组）
    """
    # 判断是否来自 OnCall Outgoing Webhook
    if "alert_payload" in payload and "alert_group" in payload:
        logger.info(
            "检测到 OnCall Outgoing Webhook payload: event_type=%s, alert_group_id=%s",
            payload.get("event", {}).get("type", ""),
            payload.get("alert_group_id", ""),
        )
        payload = _normalize_oncall_payload(payload)

    alerts = payload.get("alerts", [])
    status = payload.get("status", "unknown")
    common_labels = payload.get("commonLabels", {})
    group_key = payload.get("groupKey", "")

    logger.info(
        "处理告警: status=%s, alerts=%d, groupKey=%s",
        status, len(alerts), group_key
    )

    results = []
    for alert in alerts:
        try:
            card = build_alert_card(alert, common_labels)
            resp = feishu_api.send_card(card=card)
            message_id = resp.get("data", {}).get("message_id", "")

            alert_info = {
                "alert_name": alert.get("labels", {}).get("alertname", ""),
                "status": alert.get("status", ""),
                "labels": alert.get("labels", {}),
                "annotations": alert.get("annotations", {}),
                "received_at": time.time(),
            }
            if message_id:
                _cache_alert_message(message_id, alert_info)

            logger.info(
                "飞书卡片已发送: alert=%s, status=%s, message_id=%s",
                alert_info["alert_name"], alert_info["status"], message_id
            )
            results.append({"alert": alert_info["alert_name"], "message_id": message_id, "ok": True})

        except Exception as e:
            alert_name = alert.get("labels", {}).get("alertname", "unknown")
            logger.error("发送飞书卡片失败: alert=%s, error=%s", alert_name, e, exc_info=True)
            results.append({"alert": alert_name, "ok": False, "error": str(e)})

    return {"received": len(alerts), "results": results}


# ============================================================
# 飞书事件订阅处理
# ============================================================

def handle_feishu_event(payload: dict) -> Optional[dict]:
    """
    处理飞书事件订阅回调。

    飞书事件订阅会先发一个 challenge 验证请求，验证通过后才会发送实际事件。
    事件类型：im.message.receive_v1（收到消息）

    返回：
      - challenge 验证时返回 {"challenge": "..."}
      - 普通事件返回 None（不需要返回 body）
    """
    # URL Verification（首次订阅验证）
    if "challenge" in payload:
        logger.info("飞书 URL 验证请求，返回 challenge")
        return {"challenge": payload["challenge"]}

    # 事件处理
    header = payload.get("header", {})
    event_type = header.get("event_type", "")
    event = payload.get("event", {})

    logger.info("收到飞书事件: type=%s, event_id=%s", event_type, header.get("event_id", ""))

    if event_type == "im.message.receive_v1":
        _handle_message_event(event)
    else:
        logger.debug("忽略未处理的事件类型: %s", event_type)

    return None


def _handle_message_event(event: dict):
    """
    处理飞书群消息事件。

    当前实现：收到消息后，简单回复确认。
    后续可扩展为：分析告警上下文、调用 AI 生成处置建议等。
    """
    message = event.get("message", {})
    sender = event.get("sender", {})

    message_id = message.get("message_id", "")
    chat_id = message.get("chat_id", "")
    msg_type = message.get("message_type", "")
    content_str = message.get("content", "{}")
    sender_type = sender.get("sender_type", "")
    sender_id = sender.get("sender_id", {}).get("open_id", "")

    # 忽略机器人自身发送的消息，避免无限循环
    if sender_type == "app":
        logger.debug("忽略机器人自身消息: message_id=%s", message_id)
        return

    logger.info(
        "收到群消息: chat_id=%s, message_id=%s, type=%s, sender=%s",
        chat_id, message_id, msg_type, sender_id
    )

    # 解析消息文本
    try:
        content = json.loads(content_str)
        text = content.get("text", "").strip()
    except (json.JSONDecodeError, AttributeError):
        text = ""

    if not text:
        logger.debug("消息内容为空或非文本，跳过回复")
        return

    # 检查是否是对告警消息的回复（通过 parent_id 关联）
    parent_id = message.get("parent_id", "")
    alert_context = _alert_message_cache.get(parent_id)

    if alert_context:
        reply_text = (
            f"📋 已收到你对告警 **{alert_context['alert_name']}** 的回复。\n"
            f"告警状态: {alert_context['status']}\n"
            f"你的消息: {text}\n\n"
            f"（值班虚拟员工已记录，后续将自动分析并给出处置建议）"
        )
    else:
        reply_text = (
            f"👋 已收到消息: {text}\n\n"
            f"（值班虚拟员工在线，如需处理告警请直接回复告警卡片消息）"
        )

    try:
        resp = feishu_api.reply_text(message_id, reply_text)
        reply_msg_id = resp.get("data", {}).get("message_id", "")
        logger.info("已回复消息: original=%s, reply=%s", message_id, reply_msg_id)
    except Exception as e:
        logger.error("回复消息失败: message_id=%s, error=%s", message_id, e, exc_info=True)


# ============================================================
# HTTP Server
# ============================================================

class AlarmServiceHandler(BaseHTTPRequestHandler):
    """HTTP 请求处理器"""

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "ok", "service": "alarm-service"})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
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

        elif self.path == "/webhook/feishu":
            result = handle_feishu_event(payload)
            if result is not None:
                self._send_json(200, result)
            else:
                self._send_json(200, {"ok": True})

        else:
            self._send_json(404, {"error": "not found"})

    def _send_json(self, status_code: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        """覆盖默认日志，使用 logging 模块"""
        logger.debug("%s %s", self.client_address[0], format % args)


def main():
    server = HTTPServer(("0.0.0.0", PORT), AlarmServiceHandler)
    logger.info("alarm-service 启动: port=%d", PORT)
    logger.info("  POST /webhook/grafana  — 接收 Grafana 告警 Webhook")
    logger.info("  POST /webhook/feishu   — 接收飞书事件订阅回调")
    logger.info("  GET  /health           — 健康检查")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("alarm-service 正在关闭...")
        server.shutdown()


if __name__ == "__main__":
    main()
