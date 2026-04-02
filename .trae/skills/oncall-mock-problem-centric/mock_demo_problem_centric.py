#!/usr/bin/env python3
"""
值班虚拟员工 Mock 演示 — Problem-Centric 未来模式

模拟 Agent 足够强大后的理想值守形态：
  - 飞书群里不再发送单条告警卡片
  - Agent 后台自动聚合多条告警，直接向群里发送 Problem 卡片
  - 所有后续处理（RCA、审批、执行、恢复验证）都在 Problem 话题下回复
  - 直到 Problem 消除

四幕场景：
  Act 1: 智能聚合 + Problem 创建
         - Agent 后台收到 4 条告警 → 自动聚合 → 群里只发一张 Problem 卡片 P-3001
         - 卡片内含关联告警列表（可折叠展开查看明细）

  Act 2: 话题内 RCA 深入分析
         - 在 Problem 话题下发送分析卡片（Thinking → Done）

  Act 3: 话题内止损审批 + 执行
         - 话题下发送止损方案审批卡片
         - 值班人在话题内批准 → Agent 在话题内汇报执行进度
         - 新告警到达 → Problem 主卡片自动更新关联告警数（4→5）

  Act 4: 恢复验证 + Problem 消除
         - 话题下发恢复验证卡片
         - 全部恢复 → 更新 Problem 主卡片为「已消除」（保留影响面/详情按钮/告警列表）
         - 话题下发改进建议

用法：
  python3 mock_demo_problem_centric.py                   # 标准模式（约 3-4 分钟）
  python3 mock_demo_problem_centric.py --duration 300    # 指定总时长 5 分钟
  python3 mock_demo_problem_centric.py --fast            # 快速模式（约 40s）
  python3 mock_demo_problem_centric.py --step            # 单步模式（按回车继续）
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

_BASE_TOTAL_SECONDS = 100.0
_DEFAULT_DURATION = 240.0
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


def _problem_link(pid: str) -> str:
    if PROBLEM_BASE_URL:
        raw_url = f"{PROBLEM_BASE_URL}#{pid}"
        applink = f"https://applink.feishu.cn/client/web_url/open?mode=sidebar-semi&url={quote(raw_url, safe='')}"
        return f"[{pid}]({applink})"
    return f"**{pid}**"


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
    msg_id = resp.get("data", {}).get("message_id", "")
    print(f"         💬 话题回复已发送 [{msg_id[:20]}...]")
    return msg_id


def _reply_at_oncall(parent_msg_id: str, text: str) -> str:
    if _oncall_open_id:
        resp = feishu_api.reply_at_message(
            parent_msg_id, _oncall_open_id, text, in_thread=True)
        return resp.get("data", {}).get("message_id", "")
    else:
        return _reply(parent_msg_id, f"@{_ONCALL_PERSON_NAME} {text}")


def _human_reply_in_thread(parent_msg_id: str, text: str) -> str:
    return _reply(parent_msg_id, text)


def _now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S (UTC+8)")


# ============================================================
# 卡片构建：Problem-Centric 专用卡片
# ============================================================

def _collapsible_panel(title: str, content_md: str, expanded: bool = False) -> dict:
    """构建可折叠面板组件，复用于各类卡片中。"""
    return {
        "tag": "collapsible_panel",
        "expanded": expanded,
        "header": {
            "title": {"tag": "plain_text", "content": title},
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
            {"tag": "markdown", "content": content_md},
        ],
    }


def _build_problem_card(problem_id: str, title: str, severity: str,
                         alert_count: int, services: list,
                         root_cause_brief: str, impact: str,
                         status: str = "processing",
                         dashboard_url: str = "",
                         alerts_data: list = None):
    """
    构建 Problem 主卡片 — 群里唯一的卡片类型。

    status: processing / mitigating / recovering / resolved
    alerts_data: 关联告警明细列表，每项包含 name/service/severity/time
    """
    status_config = {
        "processing": ("orange", "🟡 处理中"),
        "analyzing":  ("blue",   "🔍 分析中"),
        "mitigating": ("blue",   "🔧 止损中"),
        "recovering": ("orange", "📉 恢复验证中"),
        "resolved":   ("green",  "✅ 已消除"),
    }
    color, status_label = status_config.get(status, ("orange", "🟡 处理中"))

    severity_map = {"critical": "🔴 Critical", "warning": "🟡 Warning", "info": "🔵 Info"}
    severity_label = severity_map.get(severity, "🟡 Warning")

    now = _now_str()
    services_str = ", ".join(services)

    elements = []

    # — 问题概要 —
    summary_lines = [
        f"**Problem ID:** `{problem_id}`",
        f"**严重级别:** {severity_label}",
        f"**状态:** {status_label}",
        f"**关联告警:** {alert_count} 条",
        f"**影响服务:** {services_str}",
        f"**创建时间:** {now}",
        f"**值班人:** 👤 {_ONCALL_PERSON_NAME}",
    ]
    elements.append({"tag": "markdown", "content": "\n".join(summary_lines)})
    elements.append({"tag": "hr"})

    # — 根因初判 —
    if root_cause_brief:
        elements.append({"tag": "markdown",
                         "content": f"**🧠 根因初判:** {root_cause_brief}"})

    # — 影响范围 —
    if impact:
        elements.append({"tag": "markdown",
                         "content": f"**💥 影响范围:** {impact}"})

    elements.append({"tag": "hr"})

    # — 关联告警明细折叠面板 —
    if alerts_data:
        table_lines = [
            "| # | 告警名 | 服务 | 级别 | 触发时间 |",
            "|---|--------|------|------|----------|",
        ]
        for i, a in enumerate(alerts_data, 1):
            table_lines.append(
                f"| {i} | {a['name']} | {a['service']} | {a['severity']} | {a['time']} |")
        elements.append(_collapsible_panel(
            f"📋 关联告警明细（共 {len(alerts_data)} 条）",
            "\n".join(table_lines),
            expanded=False))

    # — 详情按钮（schema 2.0 直接放 button，不包 action） —
    if dashboard_url:
        elements.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "📋 查看 Problem 详情"},
            "type": "primary",
            "behaviors": [{"type": "open_url", "default_url": dashboard_url}],
        })

    # — 底部提示 —
    elements.append({"tag": "markdown",
                     "content": "_💡 所有处理进展将在本消息的话题下更新_"})

    return {
        "schema": "2.0",
        "config": {"update_multi": True, "wide_screen_mode": True},
        "header": {
            "template": color,
            "title": {"tag": "plain_text",
                      "content": f"{status_label} {problem_id} — {title}"},
        },
        "body": {"elements": elements},
    }


def _build_problem_card_resolved(problem_id: str, title: str,
                                  alert_count: int, services: list,
                                  root_cause: str, duration_min: int,
                                  impact: str = "",
                                  dashboard_url: str = "",
                                  alerts_data: list = None):
    """构建 Problem 已消除状态的卡片（用于最终更新）。"""
    services_str = ", ".join(services)
    now = _now_str()

    elements = [
        {"tag": "markdown", "content": "\n".join([
            f"**Problem ID:** `{problem_id}`",
            f"**严重级别:** 🔴 Critical → ✅ Resolved",
            f"**状态:** ✅ 已消除",
            f"**关联告警:** {alert_count} 条（全部恢复）",
            f"**影响服务:** {services_str}",
            f"**消除时间:** {now}",
            f"**处理耗时:** 约 {duration_min} 分钟",
        ])},
        {"tag": "hr"},
        {"tag": "markdown", "content": f"**🧠 根因:** {root_cause}"},
    ]

    # — 影响范围 —
    if impact:
        elements.append({"tag": "markdown",
                         "content": f"**💥 影响范围:** {impact}"})

    elements.append({"tag": "hr"})

    # — 关联告警明细折叠面板 —
    if alerts_data:
        table_lines = [
            "| # | 告警名 | 服务 | 级别 | 触发时间 |",
            "|---|--------|------|------|----------|",
        ]
        for i, a in enumerate(alerts_data, 1):
            table_lines.append(
                f"| {i} | {a['name']} | {a['service']} | {a['severity']} | {a['time']} |")
        elements.append(_collapsible_panel(
            f"📋 关联告警明细（共 {len(alerts_data)} 条）",
            "\n".join(table_lines),
            expanded=False))

    # — 详情按钮（schema 2.0 直接放 button，不包 action） —
    if dashboard_url:
        elements.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "📋 查看 Problem 详情"},
            "type": "primary",
            "behaviors": [{"type": "open_url", "default_url": dashboard_url}],
        })

    elements.append({"tag": "markdown",
                     "content": "_📋 完整处理时间线请查看本消息的话题_"})

    return {
        "schema": "2.0",
        "config": {"update_multi": True, "wide_screen_mode": True},
        "header": {
            "template": "green",
            "title": {"tag": "plain_text",
                      "content": f"✅ 已消除 {problem_id} — {title}"},
        },
        "body": {"elements": elements},
    }



def _build_rca_thinking_card(problem_id: str, title: str, steps_md: str):
    """构建 RCA 分析中卡片。"""
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text",
                      "content": f"🔍 深入分析中... — {problem_id}"},
            "subtitle": {"tag": "plain_text", "content": title},
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": "🤖 **正在深入分析根因，请稍候...**"},
                _collapsible_panel("查看分析过程", steps_md, expanded=False),
            ],
        },
    }


def _build_rca_done_card(problem_id: str, title: str, conclusion_md: str,
                          steps_md: str, confidence: str, color: str = "green"):
    """构建 RCA 分析完成卡片。"""
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
                _collapsible_panel("查看分析过程", steps_md, expanded=False),
            ],
        },
    }


def _build_approval_card(problem_id: str, title: str, root_cause: str,
                          action_plan: str, risk_note: str = ""):
    """构建止损审批卡片（在话题内发送）。"""
    elements = [
        {"tag": "markdown", "content": f"**问题**: {title}"},
        {"tag": "markdown", "content": f"**根因**: {root_cause}"},
        {"tag": "hr"},
        {"tag": "markdown", "content": f"**止损方案**:\n{action_plan}"},
    ]
    if risk_note:
        elements.append({"tag": "markdown",
                         "content": f"⚠️ **风险提示**: {risk_note}"})
    elements.append({"tag": "hr"})
    elements.append({"tag": "markdown", "content": "⚠️ 请值班人确认是否执行："})
    elements.append({"tag": "button",
                     "text": {"tag": "plain_text", "content": "✅ 同意执行"},
                     "type": "primary",
                     "behaviors": [{"type": "callback", "value": {
                         "action": "approval_confirm", "approval_id": f"ACT-{problem_id}"}}]})
    elements.append({"tag": "button",
                     "text": {"tag": "plain_text", "content": "❌ 拒绝"},
                     "type": "danger",
                     "behaviors": [{"type": "callback", "value": {
                         "action": "approval_reject", "approval_id": f"ACT-{problem_id}"}}]})

    return {
        "schema": "2.0",
        "config": {"update_multi": True, "wide_screen_mode": True},
        "header": {
            "template": "orange",
            "title": {"tag": "plain_text",
                      "content": f"🧾 止损审批 — {problem_id}"},
        },
        "body": {"elements": elements},
    }


def _build_approval_result_card(problem_id: str, title: str, root_cause: str,
                                 action_plan: str, result: str = "approved"):
    """构建审批结果卡片（更新原审批卡片）。"""
    status_text = "✅ 已批准" if result == "approved" else "❌ 已拒绝"
    color = "green" if result == "approved" else "red"
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "wide_screen_mode": True},
        "header": {
            "template": color,
            "title": {"tag": "plain_text",
                      "content": f"🧾 止损审批 — {problem_id}  [{status_text}]"},
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": f"**问题**: {title}"},
                {"tag": "markdown", "content": f"**根因**: {root_cause}"},
                {"tag": "hr"},
                {"tag": "markdown", "content": f"**止损方案**: {action_plan}"},
                {"tag": "hr"},
                {"tag": "markdown",
                 "content": f"**审批结果**：{status_text}\n"
                            f"时间：{time.strftime('%H:%M:%S')}"},
            ],
        },
    }


def _build_execution_card(problem_id: str, title: str, steps_md: str,
                           status: str = "running"):
    """构建止损执行卡片（running / done）。"""
    if status == "running":
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
                    _collapsible_panel("查看执行过程", steps_md, expanded=False),
                ],
            },
        }
    else:
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
                    {"tag": "markdown", "content": steps_md},
                ],
            },
        }


def _build_recovery_card(problem_id: str, rounds_md: str,
                          status: str = "verifying"):
    """构建恢复验证卡片。"""
    status_map = {
        "verifying": ("orange", "📉 恢复验证中"),
        "passed":    ("green",  "✅ 恢复验证通过"),
        "failed":    ("red",    "❌ 恢复验证不通过"),
    }
    color, label = status_map.get(status, ("orange", "📉 恢复验证中"))
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "wide_screen_mode": True},
        "header": {
            "template": color,
            "title": {"tag": "plain_text",
                      "content": f"{label} — {problem_id}"},
        },
        "body": {
            "elements": [
                {"tag": "markdown", "content": rounds_md},
            ],
        },
    }



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

    pid_1 = ""  # 对应原来的 P-3001

    # 尝试查找值班人 open_id
    try:
        member = feishu_api.find_member_by_name(name=_ONCALL_PERSON_NAME)
        if member:
            _oncall_open_id = member.get("member_id")
            print(f"  👤 值班人 {_ONCALL_PERSON_NAME} open_id: {_oncall_open_id}")
    except Exception:
        pass

    # 关联告警明细数据（初始 4 条，Act 3 新增第 5 条）
    alerts_data = [
        {"name": "ServiceHighErrorRate", "service": "checkoutservice",
         "severity": "Critical", "time": "15:32:01"},
        {"name": "ServiceSuccessRateDrop", "service": "checkoutservice",
         "severity": "Warning", "time": "15:32:15"},
        {"name": "PodHighCPU", "service": "adservice",
         "severity": "Warning", "time": "15:32:28"},
        {"name": "ServiceHighLatency", "service": "paymentservice",
         "severity": "Warning", "time": "15:32:42"},
    ]

    # ================================================================
    # Act 1: 🧠 智能聚合 + Problem 创建
    # ================================================================
    _pause("🧠 Act 1: Agent 后台收到 4 条告警，开始自动聚合")
    print("         📡 后台告警流（群里不会看到这些）：")
    print("           [15:32:01] AG-50001 ServiceHighErrorRate / checkoutservice / Critical")
    print("           [15:32:15] AG-50002 ServiceSuccessRateDrop / checkoutservice / Warning")
    print("           [15:32:28] AG-50003 PodHighCPU / adservice / Warning")
    print("           [15:32:42] AG-50004 ServiceHighLatency / paymentservice / Warning")

    _wait(3, "Agent 后台自动聚合 + 初判...")

    resp = _api_call("POST", "/api/problems", {
        "title": "交易链路大面积超时",
        "root_cause": "adservice 近期变更导致处理耗时飙升（初判）",
        "alert_group_id": "AG-50001",
        "message_id": "",
    })
    pid_1 = resp.get("problem", {}).get("id", "P-UNKNOWN")
    print(f"         📋 Problem 已创建: {pid_1}")

    for ag_id, desc in [
        ("AG-50002", "checkoutservice 的 ServiceSuccessRateDrop 告警 (AG-50002) 归并至本问题"),
        ("AG-50003", "adservice 的 PodHighCPU 告警 (AG-50003) 归并至本问题"),
        ("AG-50004", "paymentservice 的 ServiceHighLatency 告警 (AG-50004) 归并至本问题"),
    ]:
        _api_call("POST", f"/api/problems/{pid_1}/merge", {"alert_group_id": ag_id, "description": desc})

    # — 群里只发一张 Problem 卡片 —
    _pause("📨 群里发送 Problem 卡片（唯一的一张群消息）")
    _msg_ids["problem"] = _send_card(_build_problem_card(
        pid_1,
        "交易链路大面积超时",
        "critical",
        alert_count=4,
        services=["checkoutservice", "adservice", "paymentservice"],
        root_cause_brief="初判：adservice 近期变更导致处理耗时飙升，级联影响交易链路",
        impact="交易成功率从 99.9% 降至 82.3%，P99 延迟从 200ms 飙升至 5200ms",
        status="analyzing",
        dashboard_url="https://grafana.example.com/d/problem-3001",
        alerts_data=alerts_data))

    _wait(3)

    # ================================================================
    # Act 2: 🔍 话题内 RCA 深入分析
    # ================================================================
    _pause("🔍 Act 2: 话题内发送 RCA 分析卡片（分析中）")

    rca_steps_v1 = (
        "1. ✅ Tempo: checkoutservice → adservice 调用链 P99=4800ms（正常<50ms）\n"
        "2. ✅ Loki: adservice 日志 — 无错误，但 `/ads` 接口响应极慢\n"
        "3. ✅ Prometheus: adservice CPU 使用率 95%+，GC pause 异常\n"
        "4. ⏳ 关联近期变更记录..."
    )
    _msg_ids["rca"] = _reply_card_in_thread(
        _msg_ids["problem"],
        _build_rca_thinking_card(pid_1, "交易链路大面积超时", rca_steps_v1))

    _wait(6, "Agent 深入分析：查询 Tempo + Loki + 变更记录...")

    # — 分析完成 —
    _pause("🧠 RCA 分析完成，更新分析卡片")

    rca_steps_done = (
        "1. ✅ Tempo: checkoutservice → adservice P99=4800ms\n"
        "2. ✅ Loki: adservice `/ads` 接口响应极慢，无异常日志\n"
        "3. ✅ Prometheus: adservice CPU 95%+，内存 88%，GC pause 频繁\n"
        "4. ✅ 变更记录: adservice 于 15:28 执行配置变更 CHG-2026-0401-003\n"
        "5. ✅ 该变更引入异常促销规则计算逻辑 → 处理耗时 50ms→4800ms\n"
        "6. ✅ 影响链：adservice 超时 → checkoutservice 调用失败 → paymentservice 级联超时"
    )
    rca_conclusion = (
        "**根因定位**：adservice 于 15:28 执行配置变更（CHG-2026-0401-003），"
        "引入了一条异常的促销规则计算逻辑，导致 `/ads` 接口处理耗时从 50ms 飙升至 4800ms。\n\n"
        "**级联影响**：\n"
        "- checkoutservice → adservice 调用超时 → 交易失败率飙升\n"
        "- paymentservice → adservice 调用超时 → 支付流程延迟\n"
        "- adservice Pod CPU 被打满 → PodHighCPU 告警\n\n"
        "**变更关联**：CHG-2026-0401-003（配置变更，非代码发布）"
    )
    _update_card(_msg_ids["rca"], _build_rca_done_card(
        pid_1, "adservice 配置变更引入异常促销规则",
        rca_conclusion, rca_steps_done,
        "⭐⭐⭐⭐⭐ (96%)", color="green"))

    _api_call("POST", f"/api/problems/{pid_1}/root_cause", {
        "root_cause": "adservice 配置变更（CHG-2026-0401-003）引入异常促销规则，处理耗时 50ms→4800ms"
    })
    _api_call("POST", f"/api/problems/{pid_1}/events", {
        "event_type": "rca_done",
        "description": "RCA 完成：adservice 配置变更 CHG-2026-0401-003 引入异常促销规则，级联影响 checkout/payment 服务"
    })

    _wait(3)

    # ================================================================
    # Act 3: 🔧 话题内止损审批 + 执行
    # ================================================================
    _pause("🔧 Act 3: 话题内发送止损审批卡片")

    action_plan = (
        "1. 回滚 adservice 配置到变更前版本（CHG-2026-0401-003 之前）\n"
        "2. 删除当前异常 Pod adservice-7d8f6b9c4-x2k9m，触发 K8s 重建\n"
        "3. 验证 adservice `/ads` 接口响应恢复到 <100ms"
    )
    _msg_ids["approval"] = _reply_card_in_thread(
        _msg_ids["problem"],
        _build_approval_card(
            pid_1,
            "adservice 配置变更导致交易链路超时",
            "adservice 配置变更（CHG-2026-0401-003）引入异常促销规则",
            action_plan,
            risk_note="回滚配置不影响其他服务，删除 Pod 由 K8s 自动重建（预计 30s）"))

    _api_call("POST", f"/api/problems/{pid_1}/actions", {
        "description": "回滚 adservice 配置 + 删除异常 Pod 触发重建"
    })
    _action_resp = _api_call("GET", f"/api/problems/{pid_1}")
    _action_id_1 = ""
    if _action_resp:
        for _act in _action_resp.get("actions", []):
            if _act.get("status") == "pending":
                _action_id_1 = _act["id"]
                break

    _wait(1)

    # — 话题内@值班人加急 —
    _reply_at_oncall(_msg_ids["problem"],
                     f"⚠️ {pid_1} 止损方案已生成，请审批。"
                     "当前交易成功率 82.3%，建议尽快处理。")

    _wait(5, "等待值班人审批...")

    # — 值班人在话题内批准 —
    _pause("✅ 值班人在话题内批准")

    _human_reply_in_thread(_msg_ids["problem"], "👤 已确认，执行吧。注意观察回滚后的指标。")

    if _action_id_1:
        _api_call("POST", f"/api/problems/{pid_1}/actions/{_action_id_1}/approve", {"operator": _ONCALL_PERSON_NAME})

    _wait(1)

    _update_card(_msg_ids["approval"], _build_approval_result_card(
        pid_1,
        "adservice 配置变更导致交易链路超时",
        "adservice 配置变更（CHG-2026-0401-003）引入异常促销规则",
        action_plan,
        result="approved"))

    _wait(1)

    # — 执行止损 —
    _pause("⚙️ 话题内发送止损执行进度")

    exec_steps_v1 = (
        "1. ⏳ 回滚 adservice 配置到 CHG-2026-0401-003 之前的版本...\n"
        "2. ⏳ 等待配置生效..."
    )
    _msg_ids["exec"] = _reply_card_in_thread(
        _msg_ids["problem"],
        _build_execution_card(pid_1, "回滚配置 + 重建 Pod", exec_steps_v1, "running"))

    _wait(4, "执行配置回滚...")

    # — 新告警到达，归并并更新主卡片 —
    _pause("🚨 新告警到达（AG-50005），Agent 自动归并，更新 Problem 主卡片")
    _api_call("POST", f"/api/problems/{pid_1}/merge", {
        "alert_group_id": "AG-50005",
        "description": "adservice 的 PodRestartCount 告警 (AG-50005) 在执行止损期间触发，归并至本问题"
    })
    alerts_data.append(
        {"name": "PodRestartCount", "service": "adservice",
         "severity": "Warning", "time": time.strftime("%H:%M:%S")})
    _update_card(_msg_ids["problem"], _build_problem_card(
        pid_1,
        "交易链路大面积超时",
        "critical",
        alert_count=5,
        services=["checkoutservice", "adservice", "paymentservice"],
        root_cause_brief="初判：adservice 近期变更导致处理耗时飙升，级联影响交易链路",
        impact="交易成功率从 99.9% 降至 82.3%，P99 延迟从 200ms 飙升至 5200ms",
        status="analyzing",
        dashboard_url="https://grafana.example.com/d/problem-3001",
        alerts_data=alerts_data))

    _wait(3, "继续执行止损...")

    # — 执行完成 —
    _pause("✅ 止损执行完成")

    exec_steps_done = (
        "**执行结果**：止损操作全部成功 ✅\n\n"
        "| 步骤 | 结果 |\n"
        "|------|------|\n"
        "| 配置回滚 | ✅ 已回滚至 CHG-2026-0401-003 之前 |\n"
        "| 删除异常 Pod | ✅ adservice-7d8f6b9c4-x2k9m 已删除 |\n"
        "| 新 Pod 启动 | ✅ adservice-7d8f6b9c4-r8p2q Ready 1/1 (22s) |\n"
        "| adservice `/ads` 响应 | ✅ 4800ms → 45ms |\n\n"
        "⏳ 进入 **恢复验证** 阶段..."
    )
    _update_card(_msg_ids["exec"],
                 _build_execution_card(pid_1, "回滚配置 + 重建 Pod",
                                       exec_steps_done, "done"))

    if _action_id_1:
        _api_call("POST", f"/api/problems/{pid_1}/actions/{_action_id_1}/complete", {
            "result": "配置回滚完成，异常 Pod 已删除并重建，adservice /ads 响应从 4800ms 恢复至 45ms"
        })
    _api_call("POST", f"/api/problems/{pid_1}/status", {"status": "recovering"})
    _api_call("POST", f"/api/problems/{pid_1}/events", {
        "event_type": "execution_done",
        "description": "止损执行完成：配置回滚 + Pod 重建，adservice 响应从 4800ms 恢复至 45ms"
    })

    _wait(2)

    # ================================================================
    # Act 4: ✅ 恢复验证 + Problem 消除
    # ================================================================
    _pause("📉 Act 4: 话题内恢复验证第 1 轮")

    t_verify1 = time.strftime("%H:%M:%S")

    round1 = (
        f"**第 1 轮** ({t_verify1})  ·  止损完成后 ~30s\n\n"
        "| 告警 | 服务 | 指标 | 状态 |\n"
        "|------|------|------|------|\n"
        "| ServiceHighErrorRate | checkoutservice | P99=850ms (↓) | ⏳ 恢复中 |\n"
        "| ServiceSuccessRateDrop | checkoutservice | 成功率 95.1% (↑) | ⏳ 恢复中 |\n"
        "| PodHighCPU | adservice | CPU 42% (↓) | ✅ 已恢复 |\n"
        "| ServiceHighLatency | paymentservice | P99=680ms (↓) | ⏳ 恢复中 |\n"
        "| PodRestartCount | adservice | 重启完成 | ✅ 正常 |\n\n"
        "指标全面好转，继续观察..."
    )
    _msg_ids["recovery"] = _reply_card_in_thread(
        _msg_ids["problem"], _build_recovery_card(pid_1, round1, "verifying"))

    _api_call("POST", f"/api/problems/{pid_1}/events", {
        "event_type": "recovery_check",
        "description": "恢复验证第 1 轮：PodHighCPU/PodRestartCount 已恢复，其余指标好转中"
    })

    _wait(8, "等待指标进一步恢复...")

    # — 恢复验证第 2 轮 —
    _pause("📉 恢复验证第 2 轮")

    t_verify2 = time.strftime("%H:%M:%S")

    rounds_all = (
        f"**第 1 轮** ({t_verify1})  ·  止损完成后 ~30s\n\n"
        "| 告警 | 服务 | 指标 | 状态 |\n"
        "|------|------|------|------|\n"
        "| ServiceHighErrorRate | checkoutservice | P99=850ms (↓) | ⏳ 恢复中 |\n"
        "| ServiceSuccessRateDrop | checkoutservice | 成功率 95.1% (↑) | ⏳ 恢复中 |\n"
        "| PodHighCPU | adservice | CPU 42% (↓) | ✅ 已恢复 |\n"
        "| ServiceHighLatency | paymentservice | P99=680ms (↓) | ⏳ 恢复中 |\n"
        "| PodRestartCount | adservice | 重启完成 | ✅ 正常 |\n\n"
        "---\n\n"
        f"**第 2 轮** ({t_verify2})  ·  止损完成后 ~2min\n\n"
        "| 告警 | 服务 | 指标 | 状态 |\n"
        "|------|------|------|------|\n"
        "| ServiceHighErrorRate | checkoutservice | P99=165ms ✅ | ✅ 已恢复 |\n"
        "| ServiceSuccessRateDrop | checkoutservice | 成功率 99.9% ✅ | ✅ 已恢复 |\n"
        "| PodHighCPU | adservice | CPU 28% ✅ | ✅ 已恢复 |\n"
        "| ServiceHighLatency | paymentservice | P99=120ms ✅ | ✅ 已恢复 |\n"
        "| PodRestartCount | adservice | 正常 ✅ | ✅ 已恢复 |\n\n"
        "🎉 **全部 5 条告警对应指标已恢复正常！**"
    )
    _update_card(_msg_ids["recovery"],
                 _build_recovery_card(pid_1, rounds_all, "passed"))

    _api_call("POST", f"/api/problems/{pid_1}/events", {
        "event_type": "recovery_check",
        "description": "恢复验证第 2 轮：全部 5 条告警对应指标已恢复正常"
    })

    _wait(2)

    # — 更新 Problem 主卡片为已消除 —
    _pause("✅ 更新 Problem 主卡片为已消除")

    total_min = int((time.time() - _start_time) / 60) + 12
    _update_card(_msg_ids["problem"], _build_problem_card_resolved(
        pid_1,
        "adservice 配置变更导致交易链路超时",
        alert_count=5,
        services=["checkoutservice", "adservice", "paymentservice"],
        root_cause="adservice 配置变更（CHG-2026-0401-003）引入异常促销规则，"
                   "处理耗时 50ms→4800ms，级联影响 checkout/payment 服务",
        duration_min=total_min,
        impact="交易成功率从 99.9% 降至 82.3%，P99 延迟从 200ms 飙升至 5200ms",
        dashboard_url="https://grafana.example.com/d/problem-3001",
        alerts_data=alerts_data))

    _api_call("POST", f"/api/problems/{pid_1}/resolve")

    _wait(2)

    # — 话题内发送改进建议 —
    _pause("💡 话题内发送改进建议")
    _reply(_msg_ids["problem"],
           "💡 **改进建议**\n\n"
           "1. **配置变更守护**：adservice 配置变更应增加灰度验证，"
           "在全量生效前先对 5% 流量验证性能影响\n"
           "2. **变更关联告警**：建议在配置变更后 15 分钟内自动关联新增告警，"
           "加速根因定位\n"
           "3. **促销规则测试**：新增促销规则应在 staging 环境压测后再上线\n\n"
           "_以上建议已自动同步至变更管理系统。_")

    # ============================================================
    total = time.time() - _start_time
    print(f"\n{'=' * 60}")
    print(f"🎉 演示完成！ 总耗时: {total:.0f}s ({total / 60:.1f} 分钟)")
    print(f"{'=' * 60}")
    print("\n  请到飞书群中查看完整的值守交互效果。")
    print(f"\n  核心亮点：")
    print(f"    ✅ 群里只有 1 张 Problem 卡片（零告警噪音）")
    print(f"    ✅ 所有进展在 Problem 话题下闭环")
    print(f"    ✅ 审批在话题内完成（不打断群聊）")
    print(f"    ✅ 新告警自动归并（不额外发卡片）")
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
    print("🤖 值班虚拟员工 Mock 演示 — Problem-Centric 未来模式")
    print(f"{'=' * 60}")
    print(f"  模式: {desc}")
    print(f"  飞书群: {feishu_api._resolve_chat_id(None)}")
    print(f"  时间倍率: {_SCALE:.2f}x")
    print(f"  场景: 群里只发 Problem 卡片，话题内闭环处理")
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
