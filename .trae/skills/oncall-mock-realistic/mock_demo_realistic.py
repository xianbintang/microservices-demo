#!/usr/bin/env python3
"""
值班虚拟员工 Mock 演示 — 真实场景版

模拟 Agent 犯错、卡住、人类纠偏和接管的完整人机协作流程。

四幕场景：
  Act 1: RCA 分析错误 → 值班人给出新方向 → Agent 重新分析
  Act 2: 止损方案有风险 → 值班人修改方案 → 重新审批
  Act 3: 新告警 Agent 分析卡住 → 主动求助 → 值班人告知已知问题 → 静默
  Act 4: 恢复验证不彻底 → 值班人决定接管

交互特点：
  - Agent 分析以卡片形式呈现，支持展开/收起查看分析过程
  - 分析完成后卡片原地更新为结论
  - 消息精简，不冗长

用法：
  python3 mock_demo_realistic.py                   # 标准模式（约 3-4 分钟）
  python3 mock_demo_realistic.py --duration 300    # 指定总时长 5 分钟
  python3 mock_demo_realistic.py --fast            # 快速模式（约 40s）
  python3 mock_demo_realistic.py --step            # 单步模式（按回车继续）
"""

import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import quote

# ============================================================
# 路径初始化
# ============================================================

_SKILL_DIR = Path(__file__).resolve().parent
_SKILLS_ROOT = _SKILL_DIR.parent
_FEISHU_API_DIR = _SKILLS_ROOT / "feishu-messenger"

if not _FEISHU_API_DIR.exists():
    print(f"  ❌ 未找到 feishu-messenger Skill: {_FEISHU_API_DIR}")
    sys.exit(1)

if str(_FEISHU_API_DIR) not in sys.path:
    sys.path.insert(0, str(_FEISHU_API_DIR))

_PROJECT_ROOT = _SKILLS_ROOT.parent.parent
for _env_path in [_PROJECT_ROOT / ".env",
                  _PROJECT_ROOT / "deploy" / "docker" / "alarm-service" / ".env"]:
    if _env_path.exists():
        with open(_env_path, "r") as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    os.environ.setdefault(_k.strip(), _v.strip())
        print(f"  📄 已加载环境配置: {_env_path}")
        break
else:
    print("  ⚠️  未找到 .env 文件，将依赖系统环境变量")

import feishu_api

# ============================================================
# 参数解析与时间配置
# ============================================================

_BASE_TOTAL_SECONDS = 87.0
_DEFAULT_DURATION = 210.0
_ONCALL_PERSON_NAME = "赵欣欣"


def _parse_args():
    fast = "--fast" in sys.argv
    step = "--step" in sys.argv
    duration = None
    for i, arg in enumerate(sys.argv):
        if arg == "--duration" and i + 1 < len(sys.argv):
            try:
                duration = float(sys.argv[i + 1])
            except ValueError:
                pass
    if step:
        return "step", 1.0 / 3.0
    elif duration is not None:
        return f"duration({duration:.0f}s)", max(0.2, duration / _BASE_TOTAL_SECONDS)
    elif fast:
        return "fast", 1.0 / 3.0
    else:
        return "standard", _DEFAULT_DURATION / _BASE_TOTAL_SECONDS


MODE, _SCALE = _parse_args()
STEP_MODE = MODE == "step"
PROBLEM_BASE_URL = os.environ.get("PROBLEM_BASE_URL", "")


def _problem_link(pid: str) -> str:
    """将问题编号转为飞书 markdown 超链接；未配置 URL 时退化为加粗文本。"""
    if PROBLEM_BASE_URL:
        raw_url = f"{PROBLEM_BASE_URL}#{pid}"
        applink = f"https://applink.feishu.cn/client/web_url/open?mode=sidebar-semi&url={quote(raw_url, safe='')}"
        return f"[{pid}]({applink})"
    return f"**{pid}**"


_msg_ids = {}
_start_time = 0.0
_oncall_open_id = None


def _t(seconds: float) -> float:
    return max(0.3, seconds * _SCALE)


# ============================================================
# 辅助函数
# ============================================================

def _elapsed() -> str:
    return f"T+{time.time() - _start_time:.0f}s"


def _pause(description: str):
    if STEP_MODE:
        input(f"\n  ⏸️  [{_elapsed()}] {description}  — 按回车继续...")
    else:
        print(f"\n  [{_elapsed()}] {description}")


def _wait(seconds: float, description: str = ""):
    actual = _t(seconds)
    if description:
        print(f"         ⏳ {description}")
    time.sleep(actual)


def _send_card(card: dict) -> str:
    resp = feishu_api.send_card(card=card)
    msg_id = resp.get("data", {}).get("message_id", "")
    print(f"         📨 卡片已发送 [{msg_id[:20]}...]")
    return msg_id


def _reply_card_in_thread(parent_msg_id: str, card: dict) -> str:
    card_json = json.dumps(card, ensure_ascii=False)
    resp = feishu_api.reply_message(
        parent_msg_id, card_json, msg_type="interactive", reply_in_thread=True)
    msg_id = resp.get("data", {}).get("message_id", "")
    print(f"         📨 话题内卡片已发送 [{msg_id[:20]}...]")
    return msg_id


def _update_card(msg_id: str, card: dict):
    feishu_api.update_card(msg_id, card)
    print(f"         📝 卡片已更新 [{msg_id[:20]}...]")


def _reply(message_id: str, text: str) -> str:
    resp = feishu_api.reply_in_thread(message_id, text)
    return resp.get("data", {}).get("message_id", "")


def _reply_at_oncall(parent_msg_id: str, text: str) -> str:
    if _oncall_open_id:
        resp = feishu_api.reply_at_message(
            parent_msg_id, _oncall_open_id, text, in_thread=True)
        return resp.get("data", {}).get("message_id", "")
    else:
        return _reply(parent_msg_id, f"@{_ONCALL_PERSON_NAME} {text}")


def _human_reply_in_thread(parent_msg_id: str, text: str) -> str:
    return _reply(parent_msg_id, text)


# ============================================================
# 卡片构建：JSON 2.0 + collapsible_panel
# ============================================================

def _build_alert_card(alert_name, service, severity, summary, alert_id="",
                      env="", rule_name="", oncall_users=None,
                      notify_channel="Lark", tags=None,
                      dashboard_url="", duration_min=0):
    color_map = {"critical": "red", "warning": "orange", "info": "blue"}
    severity_label = severity.capitalize() if severity else "Warning"

    now_str = time.strftime("%Y-%m-%d %H:%M:%S (UTC+8)")
    duration_text = f" (已持续{duration_min}分钟)" if duration_min > 0 else ""

    elements = []

    basic_lines = []
    if alert_id:
        basic_lines.append(f"**Alert Group:** `{alert_id}`")
    basic_lines.append(f"**服务:** {service}")
    if rule_name:
        basic_lines.append(f"**规则:** {rule_name}")
    basic_lines.append(f"**报警时间:** {now_str}{duration_text}")
    if oncall_users:
        users_str = " ".join(f"👤 {u}" for u in oncall_users)
        basic_lines.append(f"**值班人:** {users_str}")
    basic_lines.append(f"**通知方式:** {notify_channel}")
    elements.append({"tag": "markdown", "content": "\n".join(basic_lines)})

    elements.append({"tag": "hr"})

    if summary:
        elements.append({"tag": "markdown", "content": f"**摘要:** {summary}"})

    if tags:
        tag_lines = ["**Tags:**"]
        for k, v in tags.items():
            tag_lines.append(f"  {k}: `{v}`")
        elements.append({"tag": "markdown", "content": "\n".join(tag_lines)})

    elements.append({"tag": "hr"})

    actions_column = []
    actions_column.append({
        "tag": "button",
        "text": {"tag": "plain_text", "content": "📢 ACK"},
        "type": "primary_filled",
        "behaviors": [{"type": "callback", "value": {
            "action": "ack", "alert_id": alert_id}}],
    })
    actions_column.append({
        "tag": "select_static",
        "placeholder": {"tag": "plain_text", "content": "🔇 静默"},
        "options": [
            {"text": {"tag": "plain_text", "content": "30 min"}, "value": "30m"},
            {"text": {"tag": "plain_text", "content": "1 hour"}, "value": "1h"},
            {"text": {"tag": "plain_text", "content": "2 hours"}, "value": "2h"},
            {"text": {"tag": "plain_text", "content": "4 hours"}, "value": "4h"},
        ],
        "width": "120px",
        "behaviors": [{"type": "callback", "value": {
            "action": "silence", "alert_id": alert_id}}],
    })
    if dashboard_url:
        actions_column.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "📋 详情"},
            "type": "primary",
            "behaviors": [{"type": "open_url", "default_url": dashboard_url}],
        })

    elements.append({
        "tag": "column_set",
        "flex_mode": "flow",
        "background_style": "default",
        "horizontal_spacing": "8px",
        "columns": [
            {"tag": "column", "width": "auto", "weight": 1, "vertical_align": "center",
             "elements": [actions_column[0]]},
            {"tag": "column", "width": "auto", "weight": 1, "vertical_align": "center",
             "elements": [actions_column[1]]},
        ] + ([
            {"tag": "column", "width": "auto", "weight": 1, "vertical_align": "center",
             "elements": [actions_column[2]]}
        ] if dashboard_url else []),
    })

    return {
        "schema": "2.0",
        "config": {"update_multi": True, "wide_screen_mode": True},
        "header": {
            "template": color_map.get(severity, "orange"),
            "title": {"tag": "plain_text",
                      "content": f"[触发中] [{severity_label}] {alert_name}"},
        },
        "body": {"elements": elements},
    }


def _build_alert_card_resolved(alert_name, service, severity, summary, alert_id="",
                                env="", rule_name="", oncall_users=None,
                                notify_channel="Lark", tags=None,
                                dashboard_url="", duration_min=0,
                                resolve_note="", alert_time=None):
    severity_label = severity.capitalize() if severity else "Warning"

    now_str = time.strftime("%Y-%m-%d %H:%M:%S (UTC+8)")
    if alert_time:
        elapsed_sec = time.time() - alert_time
        elapsed_min = int(elapsed_sec / 60)
        resolve_time_text = f"{now_str}（持续{elapsed_min}min）"
    else:
        resolve_time_text = now_str
    duration_text = f" (已持续{duration_min}分钟)" if duration_min > 0 else ""

    elements = []

    basic_lines = []
    if alert_id:
        basic_lines.append(f"**Alert Group:** `{alert_id}`")
    basic_lines.append(f"**服务:** {service}")
    if rule_name:
        basic_lines.append(f"**规则:** {rule_name}")
    basic_lines.append(f"**报警时间:** {now_str}{duration_text}")
    basic_lines.append(f"**恢复时间:** {resolve_time_text}")
    if oncall_users:
        users_str = " ".join(f"👤 {u}" for u in oncall_users)
        basic_lines.append(f"**值班人:** {users_str}")
    basic_lines.append(f"**通知方式:** {notify_channel}")
    elements.append({"tag": "markdown", "content": "\n".join(basic_lines)})

    elements.append({"tag": "hr"})

    if summary:
        elements.append({"tag": "markdown", "content": f"**摘要:** {summary}"})

    if tags:
        tag_lines = ["**Tags:**"]
        for k, v in tags.items():
            tag_lines.append(f"  {k}: `{v}`")
        elements.append({"tag": "markdown", "content": "\n".join(tag_lines)})

    if resolve_note:
        elements.append({"tag": "markdown", "content": f"**恢复说明:** {resolve_note}"})

    elements.append({"tag": "hr"})

    action_cols = [
        {"tag": "column", "width": "auto", "weight": 1, "vertical_align": "center",
         "elements": [{
             "tag": "button",
             "text": {"tag": "plain_text", "content": "✅ 已ACK"},
             "type": "default",
             "disabled": True,
             "disabled_tips": {"tag": "plain_text", "content": "告警已恢复"},
         }]},
        {"tag": "column", "width": "auto", "weight": 1, "vertical_align": "center",
         "elements": [{
             "tag": "select_static",
             "placeholder": {"tag": "plain_text", "content": "🔇 静默"},
             "initial_option": "30 min",
             "disabled": True,
             "options": [
                 {"text": {"tag": "plain_text", "content": "30 min"}, "value": "30m"},
                 {"text": {"tag": "plain_text", "content": "1 hour"}, "value": "1h"},
                 {"text": {"tag": "plain_text", "content": "2 hours"}, "value": "2h"},
                 {"text": {"tag": "plain_text", "content": "4 hours"}, "value": "4h"},
             ],
             "width": "120px",
             "behaviors": [{"type": "callback", "value": {"action": "silence"}}],
         }]},
    ]
    if dashboard_url:
        action_cols.append(
            {"tag": "column", "width": "auto", "weight": 1, "vertical_align": "center",
             "elements": [{
                 "tag": "button",
                 "text": {"tag": "plain_text", "content": "📋 详情"},
                 "type": "primary",
                 "behaviors": [{"type": "open_url", "default_url": dashboard_url}],
             }]})

    elements.append({
        "tag": "column_set",
        "flex_mode": "flow",
        "background_style": "default",
        "horizontal_spacing": "8px",
        "columns": action_cols,
    })

    return {
        "schema": "2.0",
        "config": {"update_multi": True, "wide_screen_mode": True},
        "header": {
            "template": "green",
            "title": {"tag": "plain_text",
                      "content": f"[已恢复] [{severity_label}] {alert_name}"},
        },
        "body": {"elements": elements},
    }


def _build_alert_card_acked(alert_name, service, severity, summary, alert_id="",
                            env="", rule_name="", oncall_users=None,
                            notify_channel="Lark", tags=None,
                            dashboard_url="", duration_min=0,
                            silence_duration="30 min"):
    color_map = {"critical": "red", "warning": "orange", "info": "blue"}
    severity_label = severity.capitalize() if severity else "Warning"

    now_str = time.strftime("%Y-%m-%d %H:%M:%S (UTC+8)")
    duration_text = f" (已持续{duration_min}分钟)" if duration_min > 0 else ""

    elements = []

    basic_lines = []
    if alert_id:
        basic_lines.append(f"**Alert Group:** `{alert_id}`")
    basic_lines.append(f"**服务:** {service}")
    if rule_name:
        basic_lines.append(f"**规则:** {rule_name}")
    basic_lines.append(f"**报警时间:** {now_str}{duration_text}")
    if oncall_users:
        users_str = " ".join(f"👤 {u}" for u in oncall_users)
        basic_lines.append(f"**值班人:** {users_str}")
    basic_lines.append(f"**通知方式:** {notify_channel}")
    elements.append({"tag": "markdown", "content": "\n".join(basic_lines)})

    elements.append({"tag": "hr"})

    if summary:
        elements.append({"tag": "markdown", "content": f"**摘要:** {summary}"})

    if tags:
        tag_lines = ["**Tags:**"]
        for k, v in tags.items():
            tag_lines.append(f"  {k}: `{v}`")
        elements.append({"tag": "markdown", "content": "\n".join(tag_lines)})

    elements.append({"tag": "hr"})

    action_cols = [
        {"tag": "column", "width": "auto", "weight": 1, "vertical_align": "center",
         "elements": [{
             "tag": "button",
             "text": {"tag": "plain_text", "content": "✅ 已ACK"},
             "type": "default",
             "disabled": True,
             "disabled_tips": {"tag": "plain_text", "content": "已确认告警"},
         }]},
        {"tag": "column", "width": "auto", "weight": 1, "vertical_align": "center",
         "elements": [{
             "tag": "select_static",
             "placeholder": {"tag": "plain_text", "content": "🔇 静默"},
             "initial_option": silence_duration,
             "disabled": True,
             "options": [
                 {"text": {"tag": "plain_text", "content": "30 min"}, "value": "30m"},
                 {"text": {"tag": "plain_text", "content": "1 hour"}, "value": "1h"},
                 {"text": {"tag": "plain_text", "content": "2 hours"}, "value": "2h"},
                 {"text": {"tag": "plain_text", "content": "4 hours"}, "value": "4h"},
             ],
             "width": "120px",
             "behaviors": [{"type": "callback", "value": {"action": "silence"}}],
         }]},
    ]
    if dashboard_url:
        action_cols.append(
            {"tag": "column", "width": "auto", "weight": 1, "vertical_align": "center",
             "elements": [{
                 "tag": "button",
                 "text": {"tag": "plain_text", "content": "📋 详情"},
                 "type": "primary",
                 "behaviors": [{"type": "open_url", "default_url": dashboard_url}],
             }]})

    elements.append({
        "tag": "column_set",
        "flex_mode": "flow",
        "background_style": "default",
        "horizontal_spacing": "8px",
        "columns": action_cols,
    })

    return {
        "schema": "2.0",
        "config": {"update_multi": True, "wide_screen_mode": True},
        "header": {
            "template": color_map.get(severity, "orange"),
            "title": {"tag": "plain_text",
                      "content": f"[处理中] [{severity_label}] {alert_name}"},
        },
        "body": {"elements": elements},
    }


def _build_analysis_card_thinking(problem_id, title, steps_md):
    """分析中卡片：蓝色头 + 分析过程在折叠面板里（JSON 2.0）。"""
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text",
                      "content": f"🔍 分析中... — {problem_id}"},
            "subtitle": {"tag": "plain_text", "content": title},
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": "🤖 **正在分析根因，请稍候...**"},
                {
                    "tag": "collapsible_panel",
                    "expanded": False,
                    "header": {
                        "title": {"tag": "plain_text", "content": "查看分析过程"},
                        "vertical_align": "center",
                        "icon": {
                            "tag": "standard_icon",
                            "token": "down-small-ccm_outlined",
                            "size": "16px 16px",
                        },
                        "icon_position": "follow_text",
                        "icon_expanded_angle": -180,
                    },
                    "border": {"color": "grey", "corner_radius": "5px"},
                    "vertical_spacing": "8px",
                    "padding": "8px 8px 8px 8px",
                    "elements": [
                        {"tag": "markdown", "content": steps_md},
                    ],
                },
            ],
        },
    }


def _build_analysis_card_done(problem_id, title, conclusion_md,
                              steps_md, confidence, color="orange"):
    """分析完成卡片：显示结论 + 分析过程可折叠（JSON 2.0）。"""
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "wide_screen_mode": True},
        "header": {
            "template": color,
            "title": {"tag": "plain_text",
                      "content": f"🧠 RCA 分析完成 — {problem_id}"},
            "subtitle": {"tag": "plain_text", "content": title},
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": conclusion_md},
                {"tag": "markdown", "content": f"**置信度**：{confidence}"},
                {"tag": "hr"},
                {
                    "tag": "collapsible_panel",
                    "expanded": False,
                    "header": {
                        "title": {"tag": "plain_text", "content": "查看分析过程"},
                        "vertical_align": "center",
                        "icon": {
                            "tag": "standard_icon",
                            "token": "down-small-ccm_outlined",
                            "size": "16px 16px",
                        },
                        "icon_position": "follow_text",
                        "icon_expanded_angle": -180,
                    },
                    "border": {"color": "grey", "corner_radius": "5px"},
                    "vertical_spacing": "8px",
                    "padding": "8px 8px 8px 8px",
                    "elements": [
                        {"tag": "markdown", "content": steps_md},
                    ],
                },
            ],
        },
    }


def _build_approval_card(problem_id, title, root_cause, action_plan):
    return {
        "config": {"update_multi": True, "wide_screen_mode": True},
        "header": {
            "template": "orange",
            "title": {"tag": "plain_text", "content": f"🧾 止损审批 — {problem_id}"},
        },
        "elements": [
            {"tag": "markdown", "content": f"**问题**: {title}"},
            {"tag": "markdown", "content": f"**根因**: {root_cause}"},
            {"tag": "hr"},
            {"tag": "markdown", "content": f"**止损方案**: {action_plan}"},
            {"tag": "hr"},
            {"tag": "markdown",
             "content": f"⚠️ 请 **{_ONCALL_PERSON_NAME}** 确认是否执行："},
            {"tag": "action", "actions": [
                {"tag": "button",
                 "text": {"tag": "plain_text", "content": "✅ 同意执行"},
                 "type": "primary",
                 "behaviors": [{"type": "callback", "value": {
                     "action": "approval_confirm", "approval_id": f"ACT-{problem_id}"}}]},
                {"tag": "button",
                 "text": {"tag": "plain_text", "content": "❌ 拒绝"},
                 "type": "danger",
                 "behaviors": [{"type": "callback", "value": {
                     "action": "approval_reject", "approval_id": f"ACT-{problem_id}"}}]},
            ]},
        ],
    }


def _build_approval_result_card(problem_id, title, root_cause, action_plan,
                                result="approved"):
    status_text = "✅ 已批准" if result == "approved" else "❌ 已拒绝"
    color = "green" if result == "approved" else "red"
    return {
        "config": {"update_multi": True, "wide_screen_mode": True},
        "header": {
            "template": color,
            "title": {"tag": "plain_text",
                      "content": f"🧾 止损审批 — {problem_id}  [{status_text}]"},
        },
        "elements": [
            {"tag": "markdown", "content": f"**问题**: {title}"},
            {"tag": "markdown", "content": f"**根因**: {root_cause}"},
            {"tag": "hr"},
            {"tag": "markdown", "content": f"**止损方案**: {action_plan}"},
            {"tag": "hr"},
            {"tag": "markdown",
             "content": f"**审批结果**：{status_text}\n"
                        f"审批人：{_ONCALL_PERSON_NAME} | 时间：{time.strftime('%H:%M:%S')}"},
        ],
    }


def _build_execution_card_running(problem_id, title, steps_md):
    """止损执行中卡片：蓝色头 + 步骤在折叠面板（JSON 2.0）。"""
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text",
                      "content": f"⚙️ 止损执行中... — {problem_id}"},
            "subtitle": {"tag": "plain_text", "content": title},
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": "🤖 **正在执行止损方案...**"},
                {
                    "tag": "collapsible_panel",
                    "expanded": False,
                    "header": {
                        "title": {"tag": "plain_text", "content": "查看执行过程"},
                        "vertical_align": "center",
                        "icon": {
                            "tag": "standard_icon",
                            "token": "down-small-ccm_outlined",
                            "size": "16px 16px",
                        },
                        "icon_position": "follow_text",
                        "icon_expanded_angle": -180,
                    },
                    "border": {"color": "grey", "corner_radius": "5px"},
                    "vertical_spacing": "8px",
                    "padding": "8px 8px 8px 8px",
                    "elements": [
                        {"tag": "markdown", "content": steps_md},
                    ],
                },
            ],
        },
    }


def _build_execution_card_done(problem_id, title, result_md, steps_md):
    """止损执行完成卡片：显示结果 + 执行过程可折叠（JSON 2.0）。"""
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "wide_screen_mode": True},
        "header": {
            "template": "green",
            "title": {"tag": "plain_text",
                      "content": f"✅ 止损执行完成 — {problem_id}"},
            "subtitle": {"tag": "plain_text", "content": title},
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": result_md},
                {"tag": "hr"},
                {
                    "tag": "collapsible_panel",
                    "expanded": False,
                    "header": {
                        "title": {"tag": "plain_text", "content": "查看执行过程"},
                        "vertical_align": "center",
                        "icon": {
                            "tag": "standard_icon",
                            "token": "down-small-ccm_outlined",
                            "size": "16px 16px",
                        },
                        "icon_position": "follow_text",
                        "icon_expanded_angle": -180,
                    },
                    "border": {"color": "grey", "corner_radius": "5px"},
                    "vertical_spacing": "8px",
                    "padding": "8px 8px 8px 8px",
                    "elements": [
                        {"tag": "markdown", "content": steps_md},
                    ],
                },
            ],
        },
    }


def _build_recovery_card(problem_id, title, rounds_md, status="verifying"):
    """恢复验证卡片：累积展示多轮验证结果（JSON 2.0，可更新）。"""
    status_map = {
        "verifying": ("orange", "📉 恢复验证中"),
        "passed": ("green", "✅ 恢复完成"),
        "failed": ("red", "⚠️ 恢复未达标"),
    }
    color, label = status_map.get(status, ("orange", "📉 恢复验证中"))
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "wide_screen_mode": True},
        "header": {
            "template": color,
            "title": {"tag": "plain_text",
                      "content": f"{label} — {problem_id}"},
            "subtitle": {"tag": "plain_text", "content": title},
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": rounds_md},
            ],
        },
    }


def _build_status_card(problem_id, title, status, body):
    status_config = {
        "resolved": ("green", "🎉", "已消除"),
        "silenced": ("grey", "🔇", "已静默"),
        "takeover": ("purple", "👤", "人工处理中"),
    }
    color, emoji, text = status_config.get(status, ("blue", "📋", "处理中"))
    return {
        "config": {"update_multi": True, "wide_screen_mode": True},
        "header": {
            "template": color,
            "title": {"tag": "plain_text", "content": f"{emoji} {problem_id} {text}"},
        },
        "elements": [
            {"tag": "markdown", "content": f"**问题**: {title}"},
            {"tag": "hr"},
            {"tag": "markdown", "content": body},
        ],
    }


# ============================================================
# 演示主流程
# ============================================================

def run_demo():
    global _start_time, _oncall_open_id
    _start_time = time.time()
    _alert_times = {}

    member = feishu_api.find_member_by_name(name=_ONCALL_PERSON_NAME)
    if member:
        _oncall_open_id = member.get("member_id")
        print(f"  👤 值班人: {_ONCALL_PERSON_NAME} (open_id: {_oncall_open_id[:12]}...)")
    else:
        print(f"  ⚠️ 未在群里找到 {_ONCALL_PERSON_NAME}，将以文本方式 @")

    # ================================================================
    # 🎬 ACT 1: RCA 分析错误 → 值班人纠偏
    # ================================================================
    print(f"\n  {'━' * 50}")
    print(f"  🎬 第一幕：RCA 分析错误 → 值班人纠偏")
    print(f"  {'━' * 50}")

    _pause("🚨 告警A到达：支付服务响应超时 (Critical)")
    _msg_ids["alert_a"] = _send_card(_build_alert_card(
        "PaymentServiceTimeout", "payment-gateway", "critical",
        "支付服务 P99 延迟从 300ms 飙升至 8000ms，大量支付请求超时",
        alert_id="AG-30001",
        env="prod",
        rule_name="PaymentServiceTimeout",
        oncall_users=["赵欣欣"],
        tags={"_env": "prod", "_pod_name": "payment-gw-5c8f9d7b4-k8x2p",
              "host": "n124-188-186"},
        dashboard_url="https://grafana.example.com/d/payment-overview",
        duration_min=2))
    _alert_times["alert_a"] = time.time()

    _wait(2, "Agent 检测到新告警...")

    # Agent 简短回复 + 发分析卡片
    _pause("🤖 Agent 回复并发出分析卡片")
    _reply(_msg_ids["alert_a"], "🤖 收到，已ACK并屏蔽报警30min，现在开始分析。")

    _update_card(_msg_ids["alert_a"], _build_alert_card_acked(
        "PaymentServiceTimeout", "payment-gateway", "critical",
        "支付服务 P99 延迟从 300ms 飙升至 8000ms，大量支付请求超时",
        alert_id="AG-30001", env="prod", rule_name="PaymentServiceTimeout",
        oncall_users=["赵欣欣"],
        tags={"_env": "prod", "_pod_name": "payment-gw-5c8f9d7b4-k8x2p",
              "host": "n124-188-186"},
        dashboard_url="https://grafana.example.com/d/payment-overview",
        duration_min=2))

    _wait(2)

    # 发送"分析中"卡片（折叠面板里放初步步骤）
    analysis_steps_v1 = (
        "1. ✅ 查询 Tempo: payment-gateway 外部调用耗时异常\n"
        "2. ✅ 查询 Loki: 发现 `TLS handshake timeout` 错误日志\n"
        "3. ⏳ 关联变更记录..."
    )
    _msg_ids["analysis_a"] = _reply_card_in_thread(
        _msg_ids["alert_a"],
        _build_analysis_card_thinking(
            "P-1003", "支付网关响应超时", analysis_steps_v1))

    _wait(5, "Agent 分析中...")

    # 更新分析卡片为"完成"状态（❌ 错误的 RCA）
    _pause("🤖 分析完成，更新卡片（❌ 错误RCA）+ @值班人")
    analysis_steps_v1_done = (
        "1. ✅ Tempo: payment-gateway → upstream 调用链路 P99 = 7800ms\n"
        "2. ✅ Loki: 大量 `TLS handshake timeout` 错误\n"
        "3. ✅ 变更记录: 近 24h 无部署变更"
    )
    _update_card(_msg_ids["analysis_a"], _build_analysis_card_done(
        "P-1003", "支付网关响应超时",
        "**根因定位**：payment-gateway 的 **TLS 证书可能过期**，"
        "导致与上游支付渠道的 HTTPS 握手失败。\n\n"
        f"📝 已创建问题 {_problem_link('P-1003')}\n"
        "⚠️ 置信度中等，请值班人确认。如有误请纠正。",
        analysis_steps_v1_done,
        "⭐⭐⭐ (60%) — 中等",
        color="orange"))

    _reply_at_oncall(_msg_ids["alert_a"],
                     "\nRCA 分析完成（置信度 60%），请查看上方卡片确认。")

    _wait(5, "等待值班人确认或纠偏...")

    # 值班人纠偏
    _pause("👤 值班人纠偏：根因不对")
    _human_reply_in_thread(_msg_ids["alert_a"],
                           f"👨‍💻 [{_ONCALL_PERSON_NAME}]\n"
                           "根因不对。TLS 证书上周刚换过，不可能过期。\n"
                           "查一下是不是 **上游 DNS 解析** 的问题，"
                           "CoreDNS 最近有点不稳定。")

    _wait(2)

    # Agent 重新分析 — 发新的分析卡片
    _pause("🤖 接受纠偏，发新分析卡片")
    _reply(_msg_ids["alert_a"], "🔄 收到，排除 TLS 证书，重新聚焦 **DNS 解析**方向。")

    _wait(2)

    reanalysis_steps = (
        "1. ✅ Prometheus: CoreDNS 请求延迟 5ms → 3200ms\n"
        "2. ✅ Loki: CoreDNS 日志 `OOMKilled` 事件 (15:23)\n"
        "3. ⏳ 查询 K8s Events..."
    )
    _msg_ids["analysis_a2"] = _reply_card_in_thread(
        _msg_ids["alert_a"],
        _build_analysis_card_thinking(
            "P-1003 (重新分析)", "聚焦 CoreDNS / DNS 解析", reanalysis_steps))

    _wait(5, "Agent 重新分析中...")

    # 更新为正确 RCA
    _pause("🤖 重新分析完成，更新卡片（✅ 正确RCA）")
    reanalysis_steps_done = (
        "1. ✅ Prometheus: CoreDNS 请求延迟 5ms → 3200ms\n"
        "2. ✅ Loki: CoreDNS `OOMKilled` 事件 (15:23)\n"
        "3. ✅ K8s Events: coredns-5d78c9869d-xk7m2 被 OOMKill 重启 3 次\n"
        "4. ✅ 集群仅剩 1 个 CoreDNS 副本 → DNS 解析延迟飙升"
    )
    _update_card(_msg_ids["analysis_a2"], _build_analysis_card_done(
        "P-1003 (更新)", "CoreDNS OOMKill 导致 DNS 解析超时",
        "**根因定位**：CoreDNS Pod 于 15:23 因 OOM 被 Kill，"
        "集群仅剩 1 副本，DNS 解析延迟飙升至 3200ms，"
        "导致 payment-gateway 连接上游超时。\n\n"
        "**修正**：~~TLS 证书过期~~ → CoreDNS OOMKill\n"
        "_💡 TLS handshake timeout 是 DNS 超时的下游表现_",
        reanalysis_steps_done,
        "⭐⭐⭐⭐⭐ (95%)",
        color="green"))

    _wait(3)

    # ================================================================
    # 🎬 ACT 2: 止损方案有风险 → 值班人修改
    # ================================================================
    print(f"\n  {'━' * 50}")
    print(f"  🎬 第二幕：止损方案有风险 → 值班人修改")
    print(f"  {'━' * 50}")

    # 审批卡片（有风险方案）+ @值班人
    _pause("🧾 发送止损审批卡片（⚠️ 有风险方案）+ @值班人")
    _msg_ids["approval_v1"] = _reply_card_in_thread(
        _msg_ids["alert_a"],
        _build_approval_card(
            "P-1003", "CoreDNS OOMKill 导致 DNS 解析超时",
            "CoreDNS Pod OOMKill → DNS 解析延迟飙升",
            "删除 CoreDNS Pod coredns-5d78c9869d-xk7m2，触发 K8s 重建"))

    _reply_at_oncall(_msg_ids["alert_a"], "\n请审批上方止损方案。")

    _wait(4, "值班人审阅...")

    # 值班人拒绝
    _pause("👤 值班人拒绝方案")
    _human_reply_in_thread(_msg_ids["alert_a"],
                           f"👨‍💻 [{_ONCALL_PERSON_NAME}]\n"
                           "❌ 不行！只剩 1 个副本了，删 Pod 整个集群 DNS 都会挂。\n"
                           "应该：**先扩容到 3 副本**，等 Ready 后再处理。"
                           "另外内存 limit 从 170Mi 调到 256Mi。")

    _wait(1)

    _update_card(_msg_ids["approval_v1"], _build_approval_result_card(
        "P-1003", "CoreDNS OOMKill 导致 DNS 解析超时",
        "CoreDNS Pod OOMKill → DNS 解析延迟飙升",
        "删除 CoreDNS Pod coredns-5d78c9869d-xk7m2",
        result="rejected"))

    _wait(2)

    # 更新后的审批卡片
    _pause("🧾 发送更新后的审批卡片")
    _reply(_msg_ids["alert_a"], "✅ 已采纳修改，更新方案。")

    _wait(1)

    _msg_ids["approval_v2"] = _reply_card_in_thread(
        _msg_ids["alert_a"],
        _build_approval_card(
            "P-1003 v2", "CoreDNS OOMKill 导致 DNS 解析超时",
            "CoreDNS Pod OOMKill → DNS 解析延迟飙升",
            "① 扩容 CoreDNS 到 3 副本  ② 内存 limit 170Mi→256Mi  ③ 等新副本 Ready"))

    _reply_at_oncall(_msg_ids["alert_a"], "\n方案已更新，请审批。")

    _wait(4, "等待审批...")

    # 值班人批准
    _pause("✅ 值班人批准")
    _update_card(_msg_ids["approval_v2"], _build_approval_result_card(
        "P-1003 v2", "CoreDNS OOMKill 导致 DNS 解析超时",
        "CoreDNS Pod OOMKill → DNS 解析延迟飙升",
        "① 扩容 CoreDNS 到 3 副本  ② 内存 limit 170Mi→256Mi  ③ 等新副本 Ready",
        result="approved"))

    _wait(1)

    # 止损执行卡片（带折叠面板展示执行步骤）
    _pause("⚙️ 开始执行止损")
    exec_steps_1 = (
        "1. ✅ `kubectl scale deployment coredns --replicas=3` — 副本数扩容至 3\n"
        "2. ⏳ 等待新副本启动..."
    )
    _msg_ids["exec_card"] = _reply_card_in_thread(
        _msg_ids["alert_a"],
        _build_execution_card_running(
            "P-1003", "CoreDNS OOMKill 止损", exec_steps_1))

    _wait(4, "K8s 正在创建新 Pod...")

    # 更新执行步骤
    exec_steps_2 = (
        "1. ✅ `kubectl scale deployment coredns --replicas=3` — 副本数扩容至 3\n"
        "2. ✅ 等待新副本: 3/3 Ready (耗时 28s)\n"
        "3. ⏳ 调整内存 limit..."
    )
    _update_card(_msg_ids["exec_card"],
                 _build_execution_card_running(
                     "P-1003", "CoreDNS OOMKill 止损", exec_steps_2))

    _wait(3, "调整内存 limit...")

    # 执行完成 — 更新卡片为完成状态
    _pause("✅ 止损执行完成")
    exec_steps_done = (
        "1. ✅ `kubectl scale deployment coredns --replicas=3` — 副本数扩容至 3\n"
        "2. ✅ 等待新副本: 3/3 Ready (耗时 28s)\n"
        "3. ✅ `kubectl patch` 内存 limit 170Mi → 256Mi\n"
        f"4. ✅ 全部完成 ({time.strftime('%H:%M:%S')})"
    )
    exec_result = (
        "**执行结果**：全部 3 个步骤执行成功 ✅\n\n"
        "| 步骤 | 结果 |\n"
        "|------|------|\n"
        "| CoreDNS 扩容至 3 副本 | ✅ 成功 |\n"
        "| 新副本 Ready | ✅ 3/3 Ready (28s) |\n"
        "| 内存 limit 调整 | ✅ 170Mi → 256Mi |\n\n"
        "⏳ 进入 **Recovering** 状态，开始恢复验证..."
    )
    _update_card(_msg_ids["exec_card"],
                 _build_execution_card_done(
                     "P-1003", "CoreDNS OOMKill 止损",
                     exec_result, exec_steps_done))

    _wait(3)

    # ================================================================
    # 🎬 ACT 3: 新告警 → Agent 分析卡住 → 主动求助
    # ================================================================
    print(f"\n  {'━' * 50}")
    print(f"  🎬 第三幕：Agent 分析卡住 → 主动求助")
    print(f"  {'━' * 50}")

    _pause("🚨 告警B到达：Kafka 消费 lag 持续增长 (Warning)")
    _msg_ids["alert_b"] = _send_card(_build_alert_card(
        "KafkaConsumerLagHigh", "order-processor", "warning",
        "Kafka consumer group order-events 消费 lag 从 50 飙升至 8500+",
        alert_id="AG-30002",
        env="prod",
        rule_name="KafkaConsumerLagHigh",
        oncall_users=["赵欣欣"],
        tags={"_env": "prod", "consumer_group": "order-events",
              "host": "n124-190-055"},
        dashboard_url="https://grafana.example.com/d/kafka-overview",
        duration_min=5))
    _alert_times["alert_b"] = time.time()

    _wait(2)

    _reply(_msg_ids["alert_b"], "🤖 收到，已ACK并屏蔽报警30min，现在开始分析。")

    _update_card(_msg_ids["alert_b"], _build_alert_card_acked(
        "KafkaConsumerLagHigh", "order-processor", "warning",
        "Kafka consumer group order-events 消费 lag 从 50 飙升至 8500+",
        alert_id="AG-30002", env="prod", rule_name="KafkaConsumerLagHigh",
        oncall_users=["赵欣欣"],
        tags={"_env": "prod", "consumer_group": "order-events",
              "host": "n124-190-055"},
        dashboard_url="https://grafana.example.com/d/kafka-overview",
        duration_min=5))

    _wait(2)

    # 分析卡片
    kafka_steps = (
        "1. ✅ Consumer 实例状态正常，无报错\n"
        "2. ✅ 生产端 QPS 稳定 ~2000 msg/s\n"
        "3. ✅ Kafka Broker 指标正常\n"
        "4. ⚠️ 每条消息处理耗时 5ms → 200ms\n"
        "5. ❌ 近 24h 无 Deployment 变更\n"
        "6. ❌ 无法确定处理耗时变长原因"
    )
    _msg_ids["analysis_b"] = _reply_card_in_thread(
        _msg_ids["alert_b"],
        _build_analysis_card_thinking(
            "P-1004", "Kafka 消费延迟异常", kafka_steps))

    _wait(5, "Agent 分析 Kafka 指标...")

    # 分析卡住，更新卡片为"需要协助"
    _pause("❓ Agent 分析无果，更新卡片 + @值班人求助")
    kafka_stuck_card = {
        "schema": "2.0",
        "config": {"update_multi": True, "wide_screen_mode": True},
        "header": {
            "template": "orange",
            "title": {"tag": "plain_text",
                      "content": f"❓ 需要协助 — {_problem_link('P-1004')}"},
            "subtitle": {"tag": "plain_text", "content": "Kafka 消费延迟异常"},
        },
        "body": {
            "elements": [
                {"tag": "markdown",
                 "content": f"📝 已创建问题 {_problem_link('P-1004')}\n\n"
                            "🤖 暂时无法确定根因，需要值班人提供线索：\n"
                            "- order-processor 最近是否有发版？\n"
                            "- 是否有已知 bug 与此相关？"},
                {"tag": "hr"},
                {
                    "tag": "collapsible_panel",
                    "expanded": False,
                    "header": {
                        "title": {"tag": "plain_text", "content": "查看已排查内容"},
                        "vertical_align": "center",
                        "icon": {
                            "tag": "standard_icon",
                            "token": "down-small-ccm_outlined",
                            "size": "16px 16px",
                        },
                        "icon_position": "follow_text",
                        "icon_expanded_angle": -180,
                    },
                    "border": {"color": "grey", "corner_radius": "5px"},
                    "vertical_spacing": "8px",
                    "padding": "8px 8px 8px 8px",
                    "elements": [
                        {"tag": "markdown", "content": kafka_steps},
                    ],
                },
            ],
        },
    }
    _update_card(_msg_ids["analysis_b"], kafka_stuck_card)

    _reply_at_oncall(_msg_ids["alert_b"],
                     "\n分析暂无头绪，请查看上方卡片并提供线索。")

    _wait(5, "等待值班人...")

    # 值班人告知已知 bug
    _pause("👤 值班人告知：已知 bug，静默即可")
    _human_reply_in_thread(_msg_ids["alert_b"],
                           f"👨‍💻 [{_ONCALL_PERSON_NAME}]\n"
                           "这个是上周三发版引入的 bug，修复 MR 已提交，下周一发版。")

    _wait(2)

    _pause("🤖 Agent 执行指令")
    exec_kafka_steps = (
        "1. ✅ 关联 ISSUE-456\n"
        "2. ⏳ 静默报警规则 KafkaConsumerLagHigh..."
    )
    _msg_ids["exec_kafka"] = _reply_card_in_thread(
        _msg_ids["alert_b"],
        _build_execution_card_running(
            "P-1004", "Kafka 消费延迟处理", exec_kafka_steps))

    _wait(2)

    exec_kafka_done_steps = (
        "1. ✅ 关联 ISSUE-456\n"
        "2. ✅ 报警规则 KafkaConsumerLagHigh 静默 7 天\n"
        f"3. ✅ {_problem_link('P-1004')} 标记为 Resolved"
    )
    exec_kafka_result = (
        "**执行结果**：全部 3 个步骤执行成功 ✅\n\n"
        "| 步骤 | 结果 |\n"
        "|------|------|\n"
        "| 关联 ISSUE-456 | ✅ 已关联 |\n"
        "| 报警规则静默 | ✅ 静默 7 天 |\n"
        f"| {_problem_link('P-1004')} 状态 | ✅ Resolved |"
    )
    _update_card(_msg_ids["exec_kafka"],
                 _build_execution_card_done(
                     "P-1004", "Kafka 消费延迟处理",
                     exec_kafka_result, exec_kafka_done_steps))

    _wait(1)

    # 告警B已恢复：将原始报警卡片更新为绿色「已恢复」状态
    _update_card(_msg_ids["alert_b"], _build_alert_card_resolved(
        "KafkaConsumerLagHigh", "order-processor", "warning",
        "Kafka consumer group order-events 消费 lag 从 50 飙升至 8500+",
        alert_id="AG-30002",
        env="prod",
        rule_name="KafkaConsumerLagHigh",
        oncall_users=["赵欣欣"],
        tags={"_env": "prod", "consumer_group": "order-events",
              "host": "n124-190-055"},
        dashboard_url="https://grafana.example.com/d/kafka-overview",
        duration_min=5,
        resolve_note="已知 bug（ISSUE-456），报警规则已静默 7 天",
        alert_time=_alert_times.get("alert_b")))

    _reply_card_in_thread(_msg_ids["alert_b"], _build_status_card(
        "P-1004", "Kafka 消费延迟异常",
        "resolved",
        "**处理结果**：已知 bug（ISSUE-456），无需止损\n"
        "**操作**: 报警规则静默 7 天 + 问题标记 Resolved\n"
        "**根因**: order-processor N+1 查询 bug\n"
        "**修复计划**: 下周一发版"))

    _wait(3)

    # ================================================================
    # 🎬 ACT 4: 恢复验证不彻底 → 值班人接管
    # ================================================================
    print(f"\n  {'━' * 50}")
    print(f"  🎬 第四幕：恢复验证不彻底 → 值班人接管")
    print(f"  {'━' * 50}")

    # 恢复验证第 1 轮 — 发独立恢复验证卡片
    _pause("📉 恢复验证第 1 轮")
    round1_time = time.strftime('%H:%M:%S')
    verify_round1 = (
        f"**第 1 轮** ({round1_time})  ·  止损完成后 ~30s\n\n"
        "| 指标 | 止损前 | 当前 | 状态 |\n"
        "|------|--------|------|------|\n"
        "| CoreDNS 延迟 | 3200ms | 850ms | ⏳ 好转 |\n"
        "| CoreDNS 副本 | 1 | 3 (Ready) | ✅ |\n"
        "| gateway P99 | 8000ms | 2100ms | ⏳ 好转 |\n"
        "| 支付成功率 | 62.3% | 88.7% | ⏳ 好转 |\n\n"
        "好转中，继续观察..."
    )
    _msg_ids["recovery_card"] = _reply_card_in_thread(
        _msg_ids["alert_a"],
        _build_recovery_card("P-1003", "恢复验证", verify_round1, "verifying"))

    _wait(6, "等待指标进一步恢复...")

    # 恢复验证第 2 轮 — 更新同一张卡片，累积两轮结果
    _pause("📉 恢复验证第 2 轮 → 未达标，@值班人")
    round2_time = time.strftime('%H:%M:%S')
    verify_rounds_all = (
        f"**第 1 轮** ({round1_time})  ·  止损完成后 ~30s\n\n"
        "| 指标 | 止损前 | 当前 | 状态 |\n"
        "|------|--------|------|------|\n"
        "| CoreDNS 延迟 | 3200ms | 850ms | ⏳ 好转 |\n"
        "| CoreDNS 副本 | 1 | 3 (Ready) | ✅ |\n"
        "| gateway P99 | 8000ms | 2100ms | ⏳ 好转 |\n"
        "| 支付成功率 | 62.3% | 88.7% | ⏳ 好转 |\n\n"
        "---\n\n"
        f"**第 2 轮** ({round2_time})  ·  止损完成后 ~2min\n\n"
        "| 指标 | 止损前 | 当前 | 正常值 | 状态 |\n"
        "|------|--------|------|--------|------|\n"
        "| CoreDNS 延迟 | 3200ms | 120ms | <10ms | ⚠️ 偏高 |\n"
        "| CoreDNS 副本 | 1 | 3 | 3 | ✅ |\n"
        "| gateway P99 | 8000ms | 950ms | <400ms | ⚠️ 偏高 |\n"
        "| 支付成功率 | 62.3% | 96.1% | >99.5% | ⚠️ 未达标 |\n\n"
        "🟡 大幅好转，但未完全恢复。可能还有其他因素。"
    )
    _update_card(_msg_ids["recovery_card"],
                 _build_recovery_card("P-1003", "恢复验证",
                                      verify_rounds_all, "failed"))

    _reply_at_oncall(_msg_ids["alert_a"],
                     "\n恢复验证未完全达标（详见上方卡片），建议人工介入。")

    _wait(5, "等待值班人...")

    # 值班人接管
    _pause("👤 值班人接管")
    _human_reply_in_thread(_msg_ids["alert_a"],
                           f"👨‍💻 [{_ONCALL_PERSON_NAME}]\n"
                           "好的，我来接管。CoreDNS 延迟偏高，"
                           "我怀疑 Corefile 缓存配置有问题，手动排查。\n"
                           "你先不要自动操作了。")

    _wait(2)

    _pause("🤖 Agent 确认移交")
    _reply(_msg_ids["alert_a"],
           f"🤖 {_problem_link('P-1003')} 已移交 {_ONCALL_PERSON_NAME} 处理，我停止自动操作。\n"
           "后续需要数据查询随时 @我。🫡")

    _wait(2)

    # ============================================================
    total = time.time() - _start_time
    print(f"\n{'=' * 60}")
    print(f"🎉 演示完成！ 总耗时: {total:.0f}s ({total / 60:.1f} 分钟)")
    print(f"{'=' * 60}")
    print("\n  请到飞书群中查看完整的值守交互效果。")
    print(f"\n  发送的消息 ID:")
    for key, mid in _msg_ids.items():
        print(f"    {key}: {mid}")


# ============================================================
# 主入口
# ============================================================

def main():
    estimated = _BASE_TOTAL_SECONDS * _SCALE
    if MODE.startswith("duration"):
        desc = f"自定义时长（约 {estimated:.0f}s / {estimated / 60:.1f} 分钟）"
    elif MODE == "step":
        desc = "单步模式（每步按回车继续）"
    elif MODE == "fast":
        desc = f"快速模式（约 {estimated:.0f}s）"
    else:
        desc = f"标准模式（约 {estimated:.0f}s / {estimated / 60:.1f} 分钟）"

    print(f"\n{'=' * 60}")
    print("🤖 值班虚拟员工 Mock 演示 — 真实场景版")
    print(f"{'=' * 60}")
    print(f"  模式: {desc}")
    print(f"  飞书群: {feishu_api._resolve_chat_id(None)}")
    print(f"  值班人: {_ONCALL_PERSON_NAME}")
    print(f"  时间倍率: {_SCALE:.2f}x")
    print(f"  场景: Agent犯错→人纠偏→协作处理")
    print(f"{'=' * 60}\n")

    try:
        run_demo()
    except KeyboardInterrupt:
        print(f"\n\n  ⏹️  演示已中断 (耗时 {time.time() - _start_time:.0f}s)")
    except Exception as e:
        print(f"\n\n  ❌ 演示出错: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
