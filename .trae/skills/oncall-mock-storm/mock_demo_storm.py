#!/usr/bin/env python3
"""
值班虚拟员工 Mock 演示 — 报警风暴版

模拟基础设施故障引发大规模报警风暴：K8s 节点资源耗尽导致 5 条告警在短时间内密集到达。

三幕场景：
  Act 1: 告警密集到达 + Agent 并行分析 + 风暴触发
         - 告警1-5 陆续密集到达，Agent 对每条都 ACK + 启动独立分析（Agent 可并行处理）
         - 告警1 的分析卡片先出来；告警2、3 各自也有分析卡片
         - 当第5条到达时，Agent 内部检测到风暴模式（5条/30秒）
         - 立即创建 Problem P-2001，发送风暴卡片（群级别）
         - 中止所有独立分析 → 回到每条告警下通知"已归并至 P-2001"
         - 在 P-2001 话题内静默所有报警规则

  Act 2: 风暴 RCA + 止损（P-2001 话题内）
         - Agent 在 P-2001 话题内启动关联分析 → RCA 完成
         - @值班人建议止损方案 → 值班人确认并去处理
         - Agent 在话题内记录止损进展

  Act 3: 取消静默 + 恢复验证 + 纠偏（P-2001 话题内）
         - 值班人通知修复完成 → Agent 取消静默
         - 恢复验证第1轮：4/5 恢复，ServiceHighLatency 未恢复（纠偏）
         - Agent 重新分析未恢复告警 → 发现独立根因 → @值班人
         - 值班人处理 → 第2轮全部恢复 → P-2001 消除

交互特点：
  - Agent 并行处理：每条告警独立 ACK + 分析，不存在串行等待
  - 风暴触发即创建 Problem：归并所有未归属告警 + 静默所有报警规则
  - 所有风暴处理在 P-2001 话题内：RCA → 止损 → 取消静默 → 验证 → 纠偏
  - 纠偏逻辑：止损后发现未完全恢复 → 重新分析 → 定位独立根因

用法：
  python3 mock_demo_storm.py                   # 标准模式（约 4-5 分钟）
  python3 mock_demo_storm.py --duration 300    # 指定总时长 5 分钟
  python3 mock_demo_storm.py --fast            # 快速模式（约 50s）
  python3 mock_demo_storm.py --step            # 单步模式（按回车继续）
"""

import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import quote
import urllib.request
import urllib.error

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

_BASE_TOTAL_SECONDS = 120.0
_DEFAULT_DURATION = 300.0
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
_default_api_base = "http://localhost:9095"
if PROBLEM_BASE_URL:
    import urllib.parse as _urlparse
    _parsed = _urlparse.urlparse(PROBLEM_BASE_URL)
    _default_api_base = f"{_parsed.scheme}://{_parsed.netloc}"
PROBLEM_API_BASE = os.environ.get("PROBLEM_API_BASE", _default_api_base)


def _api_call(method: str, path: str, body: dict = None) -> dict:
    url = f"{PROBLEM_API_BASE}{path}"
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result
    except Exception as e:
        print(f"         ⚠️ API 调用失败 {method} {path}: {e}")
        return {}


def _problem_link(pid: str) -> str:
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
# 卡片构建
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
                                alert_time=None, problem_id=""):
    # 保留原始报警卡片完整内容，仅在"报警时间"下方追加"恢复时间"，header 变绿色 [已恢复]
    severity_label = severity.capitalize() if severity else "Warning"

    now_str = time.strftime("%Y-%m-%d %H:%M:%S (UTC+8)")
    # 根据告警发送时间计算持续时长
    if alert_time:
        elapsed_sec = time.time() - alert_time
        elapsed_min = int(elapsed_sec / 60)
        resolve_time_text = f"{now_str}（持续{elapsed_min}min）"
    else:
        resolve_time_text = now_str

    elements = []

    basic_lines = []
    if alert_id:
        basic_lines.append(f"**Alert Group:** `{alert_id}`")
    basic_lines.append(f"**服务:** {service}")
    if rule_name:
        basic_lines.append(f"**规则:** {rule_name}")
    basic_lines.append(f"**报警时间:** {now_str}")
    basic_lines.append(f"**恢复时间:** {resolve_time_text}")
    if oncall_users:
        users_str = " ".join(f"👤 {u}" for u in oncall_users)
        basic_lines.append(f"**值班人:** {users_str}")
    basic_lines.append(f"**通知方式:** {notify_channel}")
    if problem_id:
        basic_lines.append(f"**所属问题:** {_problem_link(problem_id)}")
    elements.append({"tag": "markdown", "content": "\n".join(basic_lines)})

    elements.append({"tag": "hr"})

    if summary:
        elements.append({"tag": "markdown", "content": f"**摘要:** {summary}"})

    # 保留 Tags 信息，不删除
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
                            silence_duration="30 min", problem_id=""):
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
    if problem_id:
        basic_lines.append(f"**所属问题:** {_problem_link(problem_id)}")
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


def _build_storm_problem_card_resolved(problem_id, alert_count, service_count,
                                        duration_sec, alerts_list_md, resolve_note=""):
    # 构建"已恢复"状态的风暴问题卡片（绿色），用于问题消除后更新原风暴卡片
    return {
        "config": {"update_multi": True, "wide_screen_mode": True},
        "header": {
            "template": "green",
            "title": {"tag": "plain_text",
                      "content": f"[已恢复] 🌪️ {problem_id} 报警风暴 — "
                                 f"{alert_count} 条告警 / {duration_sec}s"},
        },
        "elements": [
            {"tag": "markdown",
             "content": f"**{duration_sec} 秒**内收到 **{alert_count} 条告警**，"
                        f"涉及 **{service_count} 个服务**。\n\n"
                        f"✅ 问题已消除\n"
                        f"{'**恢复说明:** ' + resolve_note if resolve_note else ''}"},
            {"tag": "hr"},
            {"tag": "markdown", "content": alerts_list_md},
        ],
    }


def _build_analysis_card_thinking(problem_id, title, steps_md):
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


def _build_analysis_card_aborted(alert_id, title, steps_md, problem_id):
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "wide_screen_mode": True},
        "header": {
            "template": "grey",
            "title": {"tag": "plain_text",
                      "content": f"⏹️ 分析已中止 — {alert_id}"},
            "subtitle": {"tag": "plain_text",
                         "content": f"已归并至 {problem_id}"},
        },
        "body": {
            "elements": [
                {"tag": "markdown",
                 "content": f"🤖 检测到报警风暴，已中止独立分析，"
                            f"归并至 {_problem_link(problem_id)} 统一处理。"},
                {
                    "tag": "collapsible_panel",
                    "expanded": False,
                    "header": {
                        "title": {"tag": "plain_text",
                                  "content": "查看中止前的分析步骤"},
                        "vertical_align": "center",
                        "icon": {"tag": "standard_icon",
                                 "token": "down-small-ccm_outlined",
                                 "size": "16px 16px"},
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


def _build_storm_problem_card(problem_id, alert_count, service_count,
                              duration_sec, alerts_list_md):
    return {
        "config": {"update_multi": True, "wide_screen_mode": True},
        "header": {
            "template": "red",
            "title": {"tag": "plain_text",
                      "content": f"🌪️ {problem_id} 报警风暴 — "
                                 f"{alert_count} 条告警 / {duration_sec}s"},
        },
        "elements": [
            {"tag": "markdown",
             "content": f"**{duration_sec} 秒**内收到 **{alert_count} 条告警**，"
                        f"涉及 **{service_count} 个服务**。\n\n"
                        f"📝 已创建问题 {_problem_link(problem_id)}\n"
                        f"🔗 已将 {alert_count} 条告警全部归并至本 Problem\n"
                        "🔇 已静默所有相关报警规则\n"
                        "🔍 启动风暴模式 RCA 分析"},
            {"tag": "hr"},
            {"tag": "markdown", "content": alerts_list_md},
        ],
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
            "title": {"tag": "plain_text",
                      "content": f"{emoji} {problem_id} {text}"},
        },
        "elements": [
            {"tag": "markdown", "content": f"**问题**: {title}"},
            {"tag": "hr"},
            {"tag": "markdown", "content": body},
        ],
    }


def _build_recovery_card(problem_id, title, rounds_md, status="verifying"):
    status_map = {
        "verifying": ("orange", "📉 恢复验证中"),
        "passed": ("green", "✅ 恢复验证通过"),
        "failed": ("red", "❌ 恢复验证不通过"),
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


# ============================================================
# 告警定义
# ============================================================

ALERTS = [
    {
        "key": "alert_1", "name": "NodeHighCPU", "service": "k8s-node-pool",
        "severity": "critical", "alert_id": "AG-40001",
        "summary": "K8s 节点 n128-052-031 CPU 使用率 98.7%",
        "rule_name": "NodeHighCPU",
        "tags": {"_env": "prod", "_pod_name": "node-exporter-xz9k2",
                 "host": "n128-052-031", "node": "n128-052-031"},
        "dashboard_url": "https://grafana.example.com/d/k8s-node-overview",
        "duration_min": 1,
    },
    {
        "key": "alert_2", "name": "PodCrashLoopBackOff", "service": "checkoutservice",
        "severity": "critical", "alert_id": "AG-40002",
        "summary": "Pod checkout-7b5f8d9c6-x2k9m CrashLoopBackOff 重启 5 次",
        "rule_name": "PodCrashLoopBackOff",
        "tags": {"_env": "prod", "_pod_name": "checkout-7b5f8d9c6-x2k9m",
                 "host": "n128-052-031", "node": "n128-052-031"},
        "dashboard_url": "https://grafana.example.com/d/k8s-pod-overview",
        "duration_min": 0,
    },
    {
        "key": "alert_3", "name": "ServiceHighErrorRate", "service": "adservice",
        "severity": "warning", "alert_id": "AG-40003",
        "summary": "adservice 错误率从 0.1% 飙升至 45%",
        "rule_name": "ServiceHighErrorRate",
        "tags": {"_env": "prod", "_pod_name": "adservice-6f4b8c7d5-m3n7p",
                 "host": "n128-052-031", "node": "n128-052-031"},
        "dashboard_url": "https://grafana.example.com/d/adservice-overview",
        "duration_min": 0,
    },
    {
        "key": "alert_4", "name": "PodOOMKilled", "service": "cartservice",
        "severity": "critical", "alert_id": "AG-40004",
        "summary": "cartservice Pod 因 OOM 被连续 Kill",
        "rule_name": "PodOOMKilled",
        "tags": {"_env": "prod", "_pod_name": "cartservice-5d9f8b7c4-q8r2s",
                 "host": "n128-052-031", "node": "n128-052-031"},
        "dashboard_url": "https://grafana.example.com/d/k8s-pod-overview",
        "duration_min": 0,
    },
    {
        "key": "alert_5", "name": "ServiceHighLatency", "service": "productcatalogservice",
        "severity": "warning", "alert_id": "AG-40005",
        "summary": "商品服务 P99 延迟从 80ms 升至 4200ms",
        "rule_name": "ServiceHighLatency",
        "tags": {"_env": "prod", "_pod_name": "productcatalog-8c6d7e5f3-v4w1x",
                 "host": "n128-052-031", "node": "n128-052-031"},
        "dashboard_url": "https://grafana.example.com/d/productcatalog-overview",
        "duration_min": 0,
    },
]


# ============================================================
# 演示主流程
# ============================================================

def run_demo():
    global _start_time, _oncall_open_id
    _start_time = time.time()
    print("  🔄 重置 Problem 数据...")
    _api_call("POST", "/api/problems/reset")
    _api_call("POST", "/api/problems/reinit")
    print("  ✅ Problem 数据已重置（初始 Mock 数据已导入）")
    pid_1 = ""  # 对应原来的 P-2001
    pid_2 = ""  # 对应原来的 P-2002
    _alert_times = {}

    member = feishu_api.find_member_by_name(name=_ONCALL_PERSON_NAME)
    if member:
        _oncall_open_id = member.get("member_id")
        print(f"  👤 值班人: {_ONCALL_PERSON_NAME} (open_id: {_oncall_open_id[:12]}...)")
    else:
        print(f"  ⚠️ 未在群里找到 {_ONCALL_PERSON_NAME}，将以文本方式 @")

    # ================================================================
    # 🎬 ACT 1: 告警密集到达 + Agent 并行分析 + 风暴触发 (~40s base)
    #
    # Agent 是并行处理的：每条告警到达后都独立 ACK + 启动分析。
    # 当第5条告警到达时触发风暴检测 → 创建 Problem → 归并 + 静默。
    # ================================================================
    print(f"\n  {'━' * 50}")
    print(f"  🎬 第一幕：告警密集到达 + Agent 并行分析 + 风暴触发")
    print(f"  {'━' * 50}")

    # --- 告警 1: NodeHighCPU → Agent ACK + 开始分析 ---
    a1 = ALERTS[0]
    _pause(f"🚨 告警1到达：{a1['name']} ({a1['severity'].capitalize()})")
    _msg_ids["alert_1"] = _send_card(_build_alert_card(
        a1["name"], a1["service"], a1["severity"], a1["summary"],
        alert_id=a1["alert_id"], env="prod", rule_name=a1["rule_name"],
        oncall_users=[_ONCALL_PERSON_NAME], tags=a1["tags"],
        dashboard_url=a1["dashboard_url"], duration_min=a1["duration_min"]))
    _alert_times["alert_1"] = time.time()

    _wait(1)
    _pause("🤖 Agent ACK 告警1 + 开始独立分析")
    _reply(_msg_ids["alert_1"], "🤖 收到，已ACK并屏蔽报警30min，现在开始分析。")
    _update_card(_msg_ids["alert_1"], _build_alert_card_acked(
        a1["name"], a1["service"], a1["severity"], a1["summary"],
        alert_id=a1["alert_id"], env="prod", rule_name=a1["rule_name"],
        oncall_users=[_ONCALL_PERSON_NAME], tags=a1["tags"],
        dashboard_url=a1["dashboard_url"], duration_min=a1["duration_min"]))
    _wait(1)

    analysis_1_steps = (
        "1. ✅ 查询节点指标: CPU 98.7%, 内存 96.2%\n"
        "2. ⏳ 查询 kubelet 日志..."
    )
    _msg_ids["analysis_1"] = _reply_card_in_thread(
        _msg_ids["alert_1"],
        _build_analysis_card_thinking("AG-40001", "NodeHighCPU 分析", analysis_1_steps))

    _wait(3, "Agent 并行分析 AG-40001...")

    # --- 告警 2: PodCrashLoopBackOff → Agent 也独立 ACK + 分析 ---
    a2 = ALERTS[1]
    _pause(f"🚨 告警2到达：{a2['name']} ({a2['severity'].capitalize()})")
    _msg_ids["alert_2"] = _send_card(_build_alert_card(
        a2["name"], a2["service"], a2["severity"], a2["summary"],
        alert_id=a2["alert_id"], env="prod", rule_name=a2["rule_name"],
        oncall_users=[_ONCALL_PERSON_NAME], tags=a2["tags"],
        dashboard_url=a2["dashboard_url"], duration_min=a2["duration_min"]))
    _alert_times["alert_2"] = time.time()

    _wait(1)
    _reply(_msg_ids["alert_2"], "🤖 收到，已ACK并屏蔽报警30min，现在开始分析。")
    _update_card(_msg_ids["alert_2"], _build_alert_card_acked(
        a2["name"], a2["service"], a2["severity"], a2["summary"],
        alert_id=a2["alert_id"], env="prod", rule_name=a2["rule_name"],
        oncall_users=[_ONCALL_PERSON_NAME], tags=a2["tags"],
        dashboard_url=a2["dashboard_url"], duration_min=a2["duration_min"]))
    _wait(1)

    analysis_2_steps = (
        "1. ✅ Pod 状态: CrashLoopBackOff, 重启 5 次\n"
        "2. ⏳ 查询 Pod 日志和事件..."
    )
    _msg_ids["analysis_2"] = _reply_card_in_thread(
        _msg_ids["alert_2"],
        _build_analysis_card_thinking("AG-40002", "PodCrashLoopBackOff 分析",
                                      analysis_2_steps))

    _wait(2, "Agent 并行分析 AG-40001 + AG-40002...")

    # --- 告警 3: ServiceHighErrorRate → Agent 继续并行分析 ---
    a3 = ALERTS[2]
    _pause(f"🚨 告警3到达：{a3['name']} ({a3['severity'].capitalize()})")
    _msg_ids["alert_3"] = _send_card(_build_alert_card(
        a3["name"], a3["service"], a3["severity"], a3["summary"],
        alert_id=a3["alert_id"], env="prod", rule_name=a3["rule_name"],
        oncall_users=[_ONCALL_PERSON_NAME], tags=a3["tags"],
        dashboard_url=a3["dashboard_url"], duration_min=a3["duration_min"]))
    _alert_times["alert_3"] = time.time()

    _wait(1)
    _reply(_msg_ids["alert_3"], "🤖 收到，已ACK并屏蔽报警30min，现在开始分析。")
    _update_card(_msg_ids["alert_3"], _build_alert_card_acked(
        a3["name"], a3["service"], a3["severity"], a3["summary"],
        alert_id=a3["alert_id"], env="prod", rule_name=a3["rule_name"],
        oncall_users=[_ONCALL_PERSON_NAME], tags=a3["tags"],
        dashboard_url=a3["dashboard_url"], duration_min=a3["duration_min"]))
    _wait(1)

    analysis_3_steps = (
        "1. ✅ 错误率: 0.1% → 45%\n"
        "2. ⏳ 查询错误日志分布..."
    )
    _msg_ids["analysis_3"] = _reply_card_in_thread(
        _msg_ids["alert_3"],
        _build_analysis_card_thinking("AG-40003", "ServiceHighErrorRate 分析",
                                      analysis_3_steps))

    _wait(2, "Agent 并行分析 3 条告警...")

    # --- 告警 4: PodOOMKilled → Agent ACK + 开始分析 ---
    a4 = ALERTS[3]
    _pause(f"🚨 告警4到达：{a4['name']} ({a4['severity'].capitalize()})")
    _msg_ids["alert_4"] = _send_card(_build_alert_card(
        a4["name"], a4["service"], a4["severity"], a4["summary"],
        alert_id=a4["alert_id"], env="prod", rule_name=a4["rule_name"],
        oncall_users=[_ONCALL_PERSON_NAME], tags=a4["tags"],
        dashboard_url=a4["dashboard_url"], duration_min=a4["duration_min"]))
    _alert_times["alert_4"] = time.time()

    _wait(1)
    _reply(_msg_ids["alert_4"], "🤖 收到，已ACK并屏蔽报警30min，现在开始分析。")
    _update_card(_msg_ids["alert_4"], _build_alert_card_acked(
        a4["name"], a4["service"], a4["severity"], a4["summary"],
        alert_id=a4["alert_id"], env="prod", rule_name=a4["rule_name"],
        oncall_users=[_ONCALL_PERSON_NAME], tags=a4["tags"],
        dashboard_url=a4["dashboard_url"], duration_min=a4["duration_min"]))

    _wait(1)

    # --- 告警 5: ServiceHighLatency → 第5条到达，触发风暴 ---
    a5 = ALERTS[4]
    _pause(f"🚨 告警5到达：{a5['name']} ({a5['severity'].capitalize()}) → 触发风暴检测")
    _msg_ids["alert_5"] = _send_card(_build_alert_card(
        a5["name"], a5["service"], a5["severity"], a5["summary"],
        alert_id=a5["alert_id"], env="prod", rule_name=a5["rule_name"],
        oncall_users=[_ONCALL_PERSON_NAME], tags=a5["tags"],
        dashboard_url=a5["dashboard_url"], duration_min=a5["duration_min"]))
    _alert_times["alert_5"] = time.time()

    _wait(1)
    _reply(_msg_ids["alert_5"], "🤖 收到，已ACK并屏蔽报警30min，现在开始分析。")
    _update_card(_msg_ids["alert_5"], _build_alert_card_acked(
        a5["name"], a5["service"], a5["severity"], a5["summary"],
        alert_id=a5["alert_id"], env="prod", rule_name=a5["rule_name"],
        oncall_users=[_ONCALL_PERSON_NAME], tags=a5["tags"],
        dashboard_url=a5["dashboard_url"], duration_min=a5["duration_min"]))

    _wait(2, "Agent 内部检测到 30 秒内 5 条告警...")

    # =============================================================
    # ⚡ 风暴触发！创建 Problem P-2001 + 发风暴卡片（群级别）
    # =============================================================
    _pause("🌪️ 风暴触发！创建 P-2001 + 发送风暴 Problem 卡片")
    resp = _api_call("POST", "/api/problems", {
        "title": "K8s 节点 n128-052-031 资源耗尽引发报警风暴",
        "root_cause": "节点资源耗尽（初判）",
        "alert_group_id": "AG-40001",
        "message_id": "",
    })
    pid_1 = resp.get("problem", {}).get("id", "P-UNKNOWN")
    print(f"         📋 Problem 已创建: {pid_1}")
    storm_list = (
        "- **AG-40001** NodeHighCPU (k8s-node-pool) · Critical\n"
        "- **AG-40002** PodCrashLoopBackOff (checkoutservice) · Critical\n"
        "- **AG-40003** ServiceHighErrorRate (adservice) · Warning\n"
        "- **AG-40004** PodOOMKilled (cartservice) · Critical\n"
        "- **AG-40005** ServiceHighLatency (productcatalogservice) · Warning"
    )
    _msg_ids["storm_card"] = _send_card(
        _build_storm_problem_card(pid_1, 5, 4, 30, storm_list))
    storm_mid = _msg_ids["storm_card"]

    for ag_id, desc in [
        ("AG-40002", "checkoutservice 的 PodCrashLoopBackOff 告警 (AG-40002) 归并至本问题"),
        ("AG-40003", "adservice 的 ServiceHighErrorRate 告警 (AG-40003) 归并至本问题"),
        ("AG-40004", "cartservice 的 PodOOMKilled 告警 (AG-40004) 归并至本问题"),
        ("AG-40005", "productcatalogservice 的 ServiceHighLatency 告警 (AG-40005) 归并至本问题"),
    ]:
        _api_call("POST", f"/api/problems/{pid_1}/merge", {"alert_group_id": ag_id, "description": desc})

    _wait(1)

    # --- 中止所有独立分析 → 更新分析卡片为"已中止" ---
    _pause("⏹️ 中止所有独立分析 → 更新分析卡片")

    analysis_1_aborted = (
        "1. ✅ 查询节点指标: CPU 98.7%, 内存 96.2%\n"
        "2. ✅ kubelet 日志: `eviction manager: attempting to reclaim resources`\n"
        f"3. ⏹️ **报警风暴触发，中止独立分析，归并至 {_problem_link(pid_1)}**"
    )
    _update_card(_msg_ids["analysis_1"], _build_analysis_card_aborted(
        "AG-40001", "NodeHighCPU 分析", analysis_1_aborted, pid_1))

    analysis_2_aborted = (
        "1. ✅ Pod 状态: CrashLoopBackOff, 重启 5 次\n"
        "2. ✅ Pod 事件: Back-off restarting failed container\n"
        f"3. ⏹️ **报警风暴触发，中止独立分析，归并至 {_problem_link(pid_1)}**"
    )
    _update_card(_msg_ids["analysis_2"], _build_analysis_card_aborted(
        "AG-40002", "PodCrashLoopBackOff 分析", analysis_2_aborted, pid_1))

    analysis_3_aborted = (
        "1. ✅ 错误率: 0.1% → 45%\n"
        f"2. ⏹️ **报警风暴触发，中止独立分析，归并至 {_problem_link(pid_1)}**"
    )
    _update_card(_msg_ids["analysis_3"], _build_analysis_card_aborted(
        "AG-40003", "ServiceHighErrorRate 分析", analysis_3_aborted, pid_1))

    print(f"         ✅ 3 张分析卡片已更新为[已中止]")

    _wait(1)

    # --- 回到每条告警下通知已归并 ---
    _pause("🔗 回到每条告警下通知已归并至 P-2001")
    for a in ALERTS:
        _reply(_msg_ids[a["key"]],
               f"🔗 已归并至 {_problem_link(pid_1)}（报警风暴），中止独立分析，由 {_problem_link(pid_1)} 统一处理。")
    print(f"         ✅ 5 条告警已全部归并")

    for a in ALERTS:
        _update_card(_msg_ids[a["key"]], _build_alert_card_acked(
            a["name"], a["service"], a["severity"], a["summary"],
            alert_id=a["alert_id"], env="prod", rule_name=a["rule_name"],
            oncall_users=[_ONCALL_PERSON_NAME], tags=a["tags"],
            dashboard_url=a["dashboard_url"], duration_min=a["duration_min"],
            problem_id=pid_1))
    print(f"         ✅ 5 条告警卡片已更新所属问题为 P-2001")

    _wait(1)

    # --- P-2001 话题内：静默所有报警规则 ---
    _pause("🔇 P-2001 话题内：静默所有报警规则")
    _reply(storm_mid, "🔇 已静默所有相关报警规则（2 小时），避免风暴期间持续报警干扰。")
    _api_call("POST", f"/api/problems/{pid_1}/events", {
        "event_type": "silence",
        "description": "已静默所有 5 条相关报警规则（2 小时），避免风暴持续干扰"
    })

    _wait(2)

    # ================================================================
    # 🎬 ACT 2: 风暴 RCA + 止损（P-2001 话题内）(~30s base)
    # ================================================================
    print(f"\n  {'━' * 50}")
    print(f"  🎬 第二幕：风暴 RCA + 止损（P-2001 话题内）")
    print(f"  {'━' * 50}")

    # --- P-2001 话题内：关联分析卡片 ---
    _pause("🔍 P-2001 话题内：启动风暴模式 RCA 分析")
    analysis_steps = (
        "1. ✅ 共同特征: 5/5 告警均涉及 K8s 节点 `n128-052-031`\n"
        "2. ✅ 节点指标: CPU 98.7%，内存 96.2%（均处于极限）\n"
        "3. ✅ kubelet 日志: `eviction manager: attempting to reclaim resources`\n"
        "4. ⏳ 确认因果链和影响范围..."
    )
    _msg_ids["analysis_storm"] = _reply_card_in_thread(
        storm_mid,
        _build_analysis_card_thinking(pid_1, "风暴关联分析", analysis_steps))

    _wait(5, "Agent 风暴模式 RCA 分析中...")

    # --- 更新为 RCA 完成 ---
    _pause("🧠 风暴 RCA 完成")
    analysis_steps_done = (
        "1. ✅ 共同特征: 5/5 告警均涉及 K8s 节点 `n128-052-031`\n"
        "2. ✅ 节点指标: CPU 98.7%，内存 96.2%（均处于极限）\n"
        "3. ✅ kubelet 日志: `eviction manager: attempting to reclaim resources`\n"
        "4. ✅ 因果链: 节点资源耗尽 → kubelet 驱逐 Pod → "
        "4 个服务 CrashLoop/OOMKill/性能劣化\n"
        "5. ✅ 根因: 节点上残留大数据任务进程，持续消耗 CPU 和内存"
    )
    conclusion_md = (
        "**根因定位**：K8s 节点 `n128-052-031` 资源耗尽（CPU 98.7% / 内存 96.2%），"
        "疑似有残留进程持续消耗资源。"
        "触发 kubelet eviction，导致该节点上所有 Pod 被驱逐或 OOMKill。\n\n"
        "**影响范围**：checkoutservice / adservice / cartservice / "
        "productcatalogservice\n\n"
        "**因果链**：\n"
        "节点资源耗尽 → kubelet eviction →\n"
        "  - AG-40001 NodeHighCPU\n"
        "  - AG-40002 PodCrashLoopBackOff (checkoutservice)\n"
        "  - AG-40003 ServiceHighErrorRate (adservice)\n"
        "  - AG-40004 PodOOMKilled (cartservice)\n"
        "  - AG-40005 ServiceHighLatency (productcatalogservice)\n\n"
        "**建议止损**：清理节点上的异常进程，释放资源，等待 Pod 自动恢复。"
    )
    _update_card(_msg_ids["analysis_storm"], _build_analysis_card_done(
        pid_1, "K8s 节点 n128-052-031 资源耗尽",
        conclusion_md, analysis_steps_done,
        "⭐⭐⭐⭐ (85%)", color="orange"))
    _api_call("POST", f"/api/problems/{pid_1}/root_cause", {
        "root_cause": "K8s 节点 n128-052-031 资源耗尽（CPU 98.7% / 内存 96.2%），残留大数据任务进程持续消耗资源"
    })
    _api_call("POST", f"/api/problems/{pid_1}/events", {
        "event_type": "rca_done",
        "description": "RCA 完成：节点 n128-052-031 残留大数据任务进程耗尽资源，触发 kubelet eviction 影响 4 个服务"
    })

    _wait(2)

    # --- @值班人建议止损方案 ---
    _pause("🤖 @值班人：建议止损方案")
    _reply_at_oncall(
        storm_mid,
        "风暴 RCA 完成。根因为节点 n128-052-031 资源耗尽，"
        "疑似残留大数据任务进程。建议登录节点清理异常进程，释放资源后 Pod 应自动恢复。")

    _wait(4, "等待值班人响应...")

    # --- 值班人确认并去处理 ---
    _pause("👤 值班人确认，去处理节点")
    _human_reply_in_thread(
        storm_mid,
        f"👨‍💻 [{_ONCALL_PERSON_NAME}] "
        "确认了，这个节点昨晚有个大数据任务没清理干净。我去节点上 kill 掉那个进程。")
    _api_call("POST", f"/api/problems/{pid_1}/actions", {
        "description": "登录节点 n128-052-031 清理残留大数据任务进程"
    })
    _action_resp = _api_call("GET", f"/api/problems/{pid_1}")
    _action_id_1 = ""
    if _action_resp:
        for _act in _action_resp.get("actions", []):
            if _act.get("status") == "pending":
                _action_id_1 = _act["id"]
                break
    if _action_id_1:
        _api_call("POST", f"/api/problems/{pid_1}/actions/{_action_id_1}/approve", {"operator": _ONCALL_PERSON_NAME})

    _wait(2)
    _reply(storm_mid, "🤖 收到，等待处理完成后我来验证恢复情况。")

    _wait(5, "值班人处理节点中...")

    # --- 值班人通知处理完成 ---
    _pause("👤 值班人通知处理完成")
    _human_reply_in_thread(
        storm_mid,
        f"👨‍💻 [{_ONCALL_PERSON_NAME}] "
        "搞定了，进程已经 kill 掉，节点 CPU 已经在下降。帮我取消静默看看恢复情况。")
    if _action_id_1:
        _api_call("POST", f"/api/problems/{pid_1}/actions/{_action_id_1}/complete", {
            "result": "残留进程已 kill，节点 CPU 在下降"
        })

    _wait(2)

    # ================================================================
    # 🎬 ACT 3: 取消静默 + 恢复验证 + 纠偏（P-2001 话题内）(~50s base)
    # ================================================================
    print(f"\n  {'━' * 50}")
    print(f"  🎬 第三幕：取消静默 + 恢复验证 + 纠偏")
    print(f"  {'━' * 50}")

    # --- 取消静默 ---
    _pause("🔔 Agent 取消静默")
    _reply(storm_mid,
           "🤖 收到，正在取消静默...\n\n"
           "🔔 已取消 5 条告警的静默，恢复正常报警推送。开始恢复验证。")
    _api_call("POST", f"/api/problems/{pid_1}/events", {
        "event_type": "unsilence",
        "description": "已取消 5 条告警的静默，恢复正常报警推送"
    })
    _api_call("POST", f"/api/problems/{pid_1}/status", {"status": "recovering"})

    _wait(3, "等待指标回落...")

    # --- 恢复验证第 1 轮：4/5 恢复，1 条未恢复 ---
    _pause("📉 恢复验证第 1 轮 → 4/5 恢复，1 条未恢复")
    round1_time = time.strftime("%H:%M:%S")
    verify_round1 = (
        f"**第 1 轮** ({round1_time})  ·  止损后 ~2min\n\n"
        "- ✅ **AG-40001** NodeHighCPU · CPU 98.7% → 32.1%\n"
        "- ✅ **AG-40002** PodCrashLoopBackOff · 重启 5 次 → Running\n"
        "- ✅ **AG-40003** ServiceHighErrorRate · 错误率 45% → 0.2%\n"
        "- ✅ **AG-40004** PodOOMKilled · OOMKilled → Running\n"
        "- ❌ **AG-40005** ServiceHighLatency · P99 4200ms → **3800ms（未恢复）**\n\n"
        "⚠️ 4/5 告警已恢复，**ServiceHighLatency (AG-40005) 未恢复**，"
        "P99 延迟仍高达 3800ms。"
    )
    _msg_ids["recovery_card"] = _reply_card_in_thread(
        storm_mid,
        _build_recovery_card(pid_1, "恢复验证", verify_round1, "failed"))
    _api_call("POST", f"/api/problems/{pid_1}/events", {
        "event_type": "recovery_check",
        "description": "恢复验证第 1 轮：AG-40001~40004 已恢复，AG-40005 (productcatalogservice) 未恢复 P99=3800ms"
    })

    _wait(2)

    # --- 纠偏：Agent 发现有告警未恢复，启动独立分析 ---
    _pause("⚡ 纠偏：AG-40005 未恢复，启动独立分析")
    _reply(storm_mid,
           "⚠️ AG-40005 (ServiceHighLatency) 报警仍未恢复，"
           "可能存在其他原因，从该问题中剔除。")

    _wait(2)

    # --- 从 P-2001 剔除 AG-40005 ---
    _pause("🔀 将 AG-40005 从 P-2001 剔除")
    _api_call("POST", f"/api/problems/{pid_1}/remove_alert", {
        "alert_group_id": "AG-40005",
        "reason": "AG-40005 根因与节点资源耗尽无关，为 Redis 缓存打满的独立问题"
    })

    _wait(1)

    # --- P-2001 第2轮验证（仅剩4条）→ 全部通过 → P-2001 消除 ---
    _pause("✅ P-2001 第2轮验证（4条）→ 全部通过")
    round2_time = time.strftime("%H:%M:%S")
    verify_p2001_final = (
        f"**第 1 轮** ({round1_time})  ·  止损后 ~2min\n\n"
        "- ✅ **AG-40001** NodeHighCPU · CPU 98.7% → 32.1%\n"
        "- ✅ **AG-40002** PodCrashLoopBackOff · 重启 5 次 → Running\n"
        "- ✅ **AG-40003** ServiceHighErrorRate · 错误率 45% → 0.2%\n"
        "- ✅ **AG-40004** PodOOMKilled · OOMKilled → Running\n"
        "- ❌ **AG-40005** ServiceHighLatency · P99 4200ms → 3800ms（未恢复）\n\n"
        "---\n\n"
        f"**第 2 轮** ({round2_time})\n\n"
        "- ✅ **AG-40001** NodeHighCPU · CPU 98.7% → 30.5%\n"
        "- ✅ **AG-40002** PodCrashLoopBackOff · 重启 5 次 → Running\n"
        "- ✅ **AG-40003** ServiceHighErrorRate · 错误率 45% → 0.1%\n"
        "- ✅ **AG-40004** PodOOMKilled · OOMKilled → Running\n"
        "- ❌ **AG-40005** ServiceHighLatency · P99 4200ms → 3800ms（未恢复）\n\n"
        "4/5 告警已恢复，1 条未恢复"
    )
    _update_card(_msg_ids["recovery_card"],
                 _build_recovery_card(pid_1, "恢复验证",
                                      verify_p2001_final, "failed"))
    _api_call("POST", f"/api/problems/{pid_1}/events", {
        "event_type": "recovery_check",
        "description": "恢复验证第 2 轮：AG-40001~40004 全部恢复，AG-40005 已剔除独立处理"
    })
    _api_call("POST", f"/api/problems/{pid_1}/resolve")

    _wait(1)

    # 回到前4条告警下标记已恢复
    for a in ALERTS[:4]:
        _update_card(_msg_ids[a["key"]], _build_alert_card_resolved(
            a["name"], a["service"], a["severity"], a["summary"],
            alert_id=a["alert_id"],
            env="prod",
            rule_name=a["name"],
            oncall_users=["赵欣欣"],
            tags=a.get("tags"),
            dashboard_url=a.get("dashboard_url", ""),
            alert_time=_alert_times.get(a["key"]),
            problem_id=pid_1))
        _reply(_msg_ids[a["key"]], f"✅ 已恢复，告警已消除。{_problem_link(pid_1)} 问题已解决。")
    print(f"         ✅ 前 4 条告警卡片已更新为已恢复")

    _wait(1)

    # P-2001 最终状态卡片
    _pause("🎉 P-2001 消除")
    p2001_final_body = (
        "- ✅ **AG-40001** NodeHighCPU (k8s-node-pool)\n"
        "- ✅ **AG-40002** PodCrashLoopBackOff (checkoutservice)\n"
        "- ✅ **AG-40003** ServiceHighErrorRate (adservice)\n"
        "- ✅ **AG-40004** PodOOMKilled (cartservice)\n"
        "- 🔀 AG-40005 已剔除，独立处理\n\n"
        "根因：节点 n128-052-031 残留大数据任务进程耗尽资源\n"
        "止损：清理进程 + 取消静默\n"
        "处理过程：风暴检测 → 归并 + 静默 → RCA → 止损 → 恢复验证 → 纠偏剔除"
    )
    storm_resolved_list = (
        "- ✅ **AG-40001** NodeHighCPU (k8s-node-pool)\n"
        "- ✅ **AG-40002** PodCrashLoopBackOff (checkoutservice)\n"
        "- ✅ **AG-40003** ServiceHighErrorRate (adservice)\n"
        "- ✅ **AG-40004** PodOOMKilled (cartservice)\n"
        "- 🔀 AG-40005 已剔除，独立处理"
    )
    _update_card(storm_mid, _build_storm_problem_card_resolved(
        pid_1, 5, 4, 30, storm_resolved_list,
        resolve_note="节点 n128-052-031 残留进程已清理，4/5 告警已恢复，AG-40005 已剔除，独立处理"))

    _reply(storm_mid, f"✅ 已恢复，告警已消除。{_problem_link(pid_1)} 问题已解决。")

    _wait(2)

    # ================================================================
    # P-2002：在 AG-40005 原始告警话题下重新分析处理
    # ================================================================
    print(f"\n  {'━' * 50}")
    print(f"  🎬 P-2002：AG-40005 话题下重新分析处理")
    print(f"  {'━' * 50}")

    alert5_mid = _msg_ids["alert_5"]

    # --- AG-40005 话题下：通知剔除 + 重新分析 ---
    _pause("🔀 AG-40005 话题下：通知剔除，创建 P-2002，重新分析")
    resp = _api_call("POST", "/api/problems", {
        "title": "Redis 缓存打满导致 productcatalogservice 延迟",
        "root_cause": "风暴期间重试请求打满 Redis 缓存（内存 95%），导致频繁 eviction 和缓存穿透",
        "alert_group_id": "AG-40005",
        "message_id": _msg_ids.get("alert_5", ""),
    })
    pid_2 = resp.get("problem", {}).get("id", "P-UNKNOWN")
    print(f"         📋 Problem 已创建: {pid_2}")
    _api_call("POST", f"/api/problems/{pid_2}/events", {
        "event_type": "alert_merged",
        "description": f"productcatalogservice 的 ServiceHighLatency 告警 (AG-40005) 从 {pid_1} 纠偏移入本问题"
    })
    _reply(alert5_mid,
           f"🔀 已从 {_problem_link(pid_1)} 剔除（根因不同）。\n"
           f"📝 已创建独立问题 {_problem_link(pid_2)}，现在重新分析。")

    _update_card(_msg_ids["alert_5"], _build_alert_card_acked(
        a5["name"], a5["service"], a5["severity"], a5["summary"],
        alert_id=a5["alert_id"], env="prod", rule_name=a5["rule_name"],
        oncall_users=[_ONCALL_PERSON_NAME], tags=a5["tags"],
        dashboard_url=a5["dashboard_url"], duration_min=a5["duration_min"],
        problem_id=pid_2))

    _wait(2)

    # 重新分析卡片（在 AG-40005 话题内）
    p2002_analysis_steps = (
        "1. ✅ 排除节点资源问题（CPU 32.1%，已正常）\n"
        "2. ✅ productcatalogservice Pod Running，无异常\n"
        "3. ✅ Tempo: productcatalogservice → Redis P99=3500ms\n"
        "4. ✅ Redis 内存使用率 95%，大量 key eviction\n"
        "5. ✅ 根因确认: 风暴期间重试请求打满 Redis 缓存"
    )
    _msg_ids["p2002_analysis"] = _reply_card_in_thread(
        alert5_mid,
        _build_analysis_card_done(
            pid_2, "Redis 缓存打满导致 productcatalogservice 延迟",
            "**根因定位**：风暴期间大量重试请求打满 Redis 缓存（内存 95%），"
            "导致频繁 eviction 和缓存穿透，productcatalogservice P99 延迟 3800ms。\n\n"
            "**建议止损**：清理 Redis 缓存或重启 productcatalogservice。",
            p2002_analysis_steps,
            "⭐⭐⭐⭐ (90%)", color="orange"))

    _wait(2)

    # --- @值班人 ---
    _pause("🤖 AG-40005 话题内：@值班人建议止损")
    _reply_at_oncall(alert5_mid,
                     f" {pid_2} 根因为 Redis 缓存打满。"
                     "建议清理 Redis 缓存或重启 productcatalogservice。")

    _wait(3, "等待值班人处理...")

    # --- 值班人在 AG-40005 话题内处理 ---
    _pause("👤 值班人处理 Redis")
    _human_reply_in_thread(
        alert5_mid,
        f"👨‍💻 [{_ONCALL_PERSON_NAME}] "
        "已执行 Redis FLUSHDB 清理缓存，productcatalogservice 正在重建缓存。")
    _api_call("POST", f"/api/problems/{pid_2}/actions", {
        "description": "执行 Redis FLUSHDB 清理缓存"
    })
    _action_resp2 = _api_call("GET", f"/api/problems/{pid_2}")
    _action_id_2 = ""
    if _action_resp2:
        for _act in _action_resp2.get("actions", []):
            if _act.get("status") == "pending":
                _action_id_2 = _act["id"]
                break
    if _action_id_2:
        _api_call("POST", f"/api/problems/{pid_2}/actions/{_action_id_2}/approve", {"operator": _ONCALL_PERSON_NAME})
        _api_call("POST", f"/api/problems/{pid_2}/actions/{_action_id_2}/complete", {
            "result": "Redis FLUSHDB 清理缓存完成，productcatalogservice 重建缓存中"
        })

    _wait(2)
    _reply(alert5_mid, "🤖 收到，等待缓存重建后进行恢复验证。")

    _wait(5, "等待缓存重建...")

    # --- P-2002 恢复验证 → 通过（在 AG-40005 话题内） ---
    _pause("✅ P-2002 恢复验证 → 通过")
    p2002_verify_time = time.strftime("%H:%M:%S")
    p2002_verify = (
        f"**验证时间** ({p2002_verify_time})  ·  Redis 缓存清理后 ~2min\n\n"
        "- ✅ **AG-40005** ServiceHighLatency · P99 4200ms → **85ms（已恢复）**\n"
        "- ✅ Redis 内存使用率 95% → 42%\n\n"
        "告警已恢复 ✅"
    )
    _msg_ids["p2002_recovery"] = _reply_card_in_thread(
        alert5_mid,
        _build_recovery_card(pid_2, "恢复验证", p2002_verify, "passed"))
    _api_call("POST", f"/api/problems/{pid_2}/events", {
        "event_type": "recovery_check",
        "description": "恢复验证：AG-40005 P99 从 4200ms 恢复至 85ms，Redis 内存 42%"
    })
    _api_call("POST", f"/api/problems/{pid_2}/resolve")

    _wait(1)

    # P-2002 最终状态（在 AG-40005 话题内）
    _pause("🎉 P-2002 消除")
    total_minutes = max(1, int((time.time() - _start_time) / 60))
    p2002_final_body = (
        "- ✅ **AG-40005** ServiceHighLatency (productcatalogservice)\n\n"
        "根因：风暴期间重试请求打满 Redis 缓存\n"
        "止损：清理 Redis 缓存\n"
        f"总处理耗时：约 {total_minutes} 分钟"
    )
    _update_card(_msg_ids["alert_5"], _build_alert_card_resolved(
        "ServiceHighLatency", "productcatalogservice", "warning",
        "商品服务 P99 延迟从 80ms 升至 4200ms",
        alert_id="AG-40005",
        env="prod",
        rule_name="ServiceHighLatency",
        oncall_users=["赵欣欣"],
        tags={"_env": "prod", "host": "n128-055-012"},
        alert_time=_alert_times.get("alert_5"),
        problem_id=pid_2))

    _reply(alert5_mid, f"✅ 已恢复，告警已消除。{_problem_link(pid_2)} 问题已解决。")

    _wait(2)

    # --- 值班人在 AG-40005 话题内最终回复 ---
    _pause("👤 值班人回复")
    _human_reply_in_thread(
        alert5_mid,
        f"👨‍💻 [{_ONCALL_PERSON_NAME}] "
        "👍 拆分问题很及时。我给大数据任务加资源限制，"
        "Redis 也加个内存上限告警，避免下次再被打满。")

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
    print("🤖 值班虚拟员工 Mock 演示 — 报警风暴版")
    print(f"{'=' * 60}")
    print(f"  模式: {desc}")
    print(f"  飞书群: {feishu_api._resolve_chat_id(None)}")
    print(f"  值班人: {_ONCALL_PERSON_NAME}")
    print(f"  时间倍率: {_SCALE:.2f}x")
    print(f"  场景: 告警并行分析→风暴触发→归并+静默→RCA→止损→"
          "取消静默→恢复验证→纠偏")
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
