#!/usr/bin/env python3
"""
值班虚拟员工 Mock 演示 — 完美场景版

模拟 Agent 端到端自主处理告警的完整流程（除审批外无需人工介入）。

场景剧本：
  1. 告警A到达 → Agent 分析 → RCA 定位（adservice 配置变更）
  2. 告警B到达（A分析中）→ 归并到 P-1001
  3. 生成止损方案 → 审批通过 → 执行止损
  4. 告警C到达（审批等待中）→ 初判归并 P-1001
  5. 恢复验证 → A/B 恢复，C 未恢复
  6. 纠偏：C 拆分为 P-1002（JVM 内存不足）
  7. P-1001 消除

用法：
  python3 mock_demo.py                   # 标准模式（约 3-4 分钟）
  python3 mock_demo.py --duration 300    # 指定总时长 5 分钟
  python3 mock_demo.py --fast            # 快速模式（约 40s）
  python3 mock_demo.py --step            # 单步模式（每步按回车）
"""

import json
import os
import sys
import time
from pathlib import Path

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

_BASE_TOTAL_SECONDS = 90.0
_DEFAULT_DURATION = 210.0


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
_msg_ids = {}
_start_time = 0.0


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


# ============================================================
# 卡片构建：JSON 2.0 + collapsible_panel
# ============================================================

def _build_alert_card(alert_name, service, severity, summary, alert_id="",
                      env="", rule_name="", oncall_users=None,
                      notify_channel="Lark", tags=None,
                      dashboard_url="", duration_min=0):
    """
    构建丰富的告警卡片，参考 Grafana OnCall 风格。

    参数:
        alert_name:   告警名称
        service:      服务名称
        severity:     严重级别 (critical / warning / info)
        summary:      告警摘要
        alert_id:     Alert Group ID
        env:          环境标识 (prod / staging / dev)
        rule_name:    告警规则名称
        oncall_users: 值班人列表 (e.g. ["张三", "李四"])
        notify_channel: 通知方式 (e.g. "Lark")
        tags:         标签字典 (e.g. {"_pod_name": "xxx", "host": "n1"})
        dashboard_url: Dashboard / 详情链接
        duration_min: 已持续分钟数
    """
    color_map = {"critical": "red", "warning": "orange", "info": "blue"}
    severity_label = severity.capitalize() if severity else "Warning"

    now_str = time.strftime("%Y-%m-%d %H:%M:%S (UTC+8)")
    duration_text = f" (已持续{duration_min}分钟)" if duration_min > 0 else ""

    elements = []

    # — 基本信息区 —
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

    # — 摘要 —
    if summary:
        elements.append({"tag": "markdown", "content": f"**摘要:** {summary}"})

    # — Tags 区域 —
    if tags:
        tag_lines = [f"**Tags:**"]
        for k, v in tags.items():
            tag_lines.append(f"  {k}: `{v}`")
        elements.append({"tag": "markdown", "content": "\n".join(tag_lines)})

    elements.append({"tag": "hr"})

    # — 详情链接按钮 —
    if dashboard_url:
        elements.append({"tag": "action", "actions": [
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "📋 查看详情"},
                "type": "primary",
                "behaviors": [{"type": "open_url", "default_url": dashboard_url}],
            },
        ]})

    return {
        "config": {"update_multi": True, "wide_screen_mode": True},
        "header": {
            "template": color_map.get(severity, "orange"),
            "title": {"tag": "plain_text",
                      "content": f"[触发中] [{severity_label}] {alert_name}"},
        },
        "elements": elements,
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
                              steps_md, confidence, color="green"):
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
            {"tag": "markdown", "content": "⚠️ 请值班人确认是否执行："},
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
                        f"时间：{time.strftime('%H:%M:%S')}"},
        ],
    }


def _build_execution_card_running(problem_id, title, steps_md):
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
    status_map = {
        "verifying": ("orange", "📉 恢复验证中"),
        "passed": ("green", "✅ 恢复完成"),
        "partial": ("orange", "⚠️ 部分恢复"),
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
        "processing": ("blue", "🟡", "处理中"),
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
    global _start_time
    _start_time = time.time()

    # ================================================================
    # 🚨 告警 A 到达
    # ================================================================
    _pause("🚨 告警A到达：交易服务响应超时 (Critical)")
    _msg_ids["alert_a"] = _send_card(_build_alert_card(
        "ServiceHighErrorRate", "checkoutservice", "critical",
        "交易服务响应超时，P99 延迟从 200ms 飙升至 5000ms，影响交易链路",
        alert_id="AG-20001",
        env="prod",
        rule_name="ServiceHighErrorRate",
        oncall_users=["赵欣欣"],
        tags={"_env": "prod", "_pod_name": "checkout-7b5f8d9c6-x2k9m",
              "host": "n128-052-031"},
        dashboard_url="https://grafana.example.com/d/checkout-overview",
        duration_min=3))

    _wait(2, "Agent 检测到新告警...")

    _pause("🤖 Agent 回复并发出分析卡片")
    _reply(_msg_ids["alert_a"], "🤖 收到，开始分析。")

    _wait(2)

    analysis_a_steps_v1 = (
        "1. ✅ Tempo: checkoutservice → adservice 调用链 P99=4800ms\n"
        "2. ✅ Loki: adservice 日志无明显错误\n"
        "3. ⏳ 关联近期变更记录..."
    )
    _msg_ids["analysis_a"] = _reply_card_in_thread(
        _msg_ids["alert_a"],
        _build_analysis_card_thinking(
            "P-1001", "交易服务响应超时", analysis_a_steps_v1))

    _wait(5, "Agent 正在查询 Tempo 链路 + 变更记录...")

    # ================================================================
    # 🚨 告警 B 到达（A 还在分析中）
    # ================================================================
    _pause("🚨 告警B到达：交易服务成功率下跌 (Warning) ← A还在分析中")
    _msg_ids["alert_b"] = _send_card(_build_alert_card(
        "ServiceSuccessRateDrop", "checkoutservice", "warning",
        "交易服务接口成功率从 99.9% 跌至 85.2%",
        alert_id="AG-20002",
        env="prod",
        rule_name="ServiceSuccessRateDrop",
        oncall_users=["赵欣欣"],
        tags={"_env": "prod", "_pod_name": "checkout-7b5f8d9c6-x2k9m",
              "host": "n128-052-031"},
        dashboard_url="https://grafana.example.com/d/checkout-overview",
        duration_min=1))

    _wait(2)

    _reply(_msg_ids["alert_b"],
           "🤖 收到，开始分析。")

    _wait(4, "Agent 继续分析告警A...")

    # ================================================================
    # 🧠 告警 A 的 RCA 完成
    # ================================================================
    _pause("🧠 告警A分析完成，更新卡片")
    analysis_a_steps_done = (
        "1. ✅ Tempo: checkoutservice → adservice P99=4800ms\n"
        "2. ✅ Loki: adservice 无明显错误，但响应极慢\n"
        "3. ✅ 变更记录: adservice 于 15:32 执行配置变更 CHG-2026-0331-007\n"
        "4. ✅ 该变更引入异常促销规则计算逻辑 → 处理耗时 50ms→4800ms"
    )
    _update_card(_msg_ids["analysis_a"], _build_analysis_card_done(
        "P-1001", "营销服务配置变更导致交易超时",
        "**根因定位**：adservice 于 15:32 执行配置变更（CHG-2026-0331-007），"
        "引入异常促销规则计算逻辑，处理耗时从 50ms 飙升至 4800ms，"
        "导致下游 checkoutservice 调用超时。\n\n"
        "**影响范围**：checkoutservice → adservice 调用链路\n"
        "📝 已创建问题 **P-1001**",
        analysis_a_steps_done,
        "⭐⭐⭐⭐⭐ (95%)",
        color="green"))

    _wait(3)

    # ================================================================
    # 🔗 告警 B 归并
    # ================================================================
    _pause("🔗 告警B归并到 P-1001")
    _reply(_msg_ids["alert_b"],
           "🔗 该告警与 P-1001 直接相关 — adservice 超时导致请求失败，成功率下降。\n"
           "已归并至 **P-1001**，无需单独处理。")

    _wait(3)

    # ================================================================
    # 🧾 止损审批
    # ================================================================
    _pause("🧾 发送止损审批卡片")
    _msg_ids["approval"] = _reply_card_in_thread(
        _msg_ids["alert_a"],
        _build_approval_card(
            "P-1001", "营销服务配置变更导致交易超时",
            "adservice 配置变更（CHG-2026-0331-007）引入异常促销规则",
            "删除异常 Pod adservice-7d8f6b9c4-x2k9m，触发 K8s 自动重建（预计恢复 30s）"))

    _wait(5, "等待值班人审批...")

    # ================================================================
    # 🚨 告警 C 到达（审批等待中）
    # ================================================================
    _pause("🚨 告警C到达：用户中心服务超时 (Warning) ← 审批等待中")
    _msg_ids["alert_c"] = _send_card(_build_alert_card(
        "ServiceHighLatency", "userservice", "warning",
        "用户中心服务响应超时，P99 延迟从 150ms 升至 3200ms",
        alert_id="AG-20003",
        env="prod",
        rule_name="ServiceHighLatency",
        oncall_users=["赵欣欣"],
        tags={"_env": "prod", "_pod_name": "userservice-6c4d8b7f5-w3m1n",
              "host": "n128-055-012"},
        dashboard_url="https://grafana.example.com/d/userservice-overview",
        duration_min=0))

    _wait(2)

    _reply(_msg_ids["alert_c"], "🤖 收到，开始分析。")

    _wait(2)

    analysis_c_steps = (
        "1. ✅ Tempo: userservice 内部处理耗时正常\n"
        "2. ✅ userservice 与 checkoutservice 共享下游依赖 adservice\n"
        "3. ✅ 时间窗口与 P-1001 高度重合"
    )
    _msg_ids["analysis_c"] = _reply_card_in_thread(
        _msg_ids["alert_c"],
        _build_analysis_card_thinking(
            "P-1001 (归并)", "userservice 超时初判", analysis_c_steps))

    _wait(4, "Agent 分析告警C...")

    _update_card(_msg_ids["analysis_c"], _build_analysis_card_done(
        "P-1001 (归并)", "userservice 超时 → 初判归并 P-1001",
        "**分析结果**：userservice 与 checkoutservice 共享下游依赖 adservice，"
        "时间窗口高度重合。\n\n"
        "🔗 已归并至 **P-1001**，统一处理。\n"
        "_⚠️ 置信度中等，将在止损完成后验证。_",
        analysis_c_steps,
        "⭐⭐⭐ (65%) — 中等",
        color="orange"))

    _wait(4, "继续等待审批...")

    # ================================================================
    # ✅ 审批通过 → 执行止损
    # ================================================================
    _pause("✅ 值班人批准了审批")
    _update_card(_msg_ids["approval"], _build_approval_result_card(
        "P-1001", "营销服务配置变更导致交易超时",
        "adservice 配置变更（CHG-2026-0331-007）引入异常促销规则",
        "删除异常 Pod adservice-7d8f6b9c4-x2k9m，触发 K8s 自动重建",
        result="approved"))

    _wait(1)

    _pause("⚙️ 开始执行止损")
    exec_steps_1 = (
        "1. ⏳ 删除 Pod adservice-7d8f6b9c4-x2k9m..."
    )
    _msg_ids["exec_card"] = _reply_card_in_thread(
        _msg_ids["alert_a"],
        _build_execution_card_running(
            "P-1001", "删除异常 Pod 触发重建", exec_steps_1))

    _wait(4, "K8s 正在重建 Pod...")

    exec_steps_done = (
        "1. ✅ 旧 Pod adservice-7d8f6b9c4-x2k9m 已删除\n"
        "2. ✅ 新 Pod adservice-7d8f6b9c4-m3n7p 启动 (Ready 1/1, 耗时 18s)\n"
        "3. ✅ adservice 响应时间已降至 60ms"
    )
    exec_result = (
        "**执行结果**：止损操作执行成功 ✅\n\n"
        "| 步骤 | 结果 |\n"
        "|------|------|\n"
        "| 删除异常 Pod | ✅ 已删除 |\n"
        "| 新 Pod 启动 | ✅ Ready 1/1 (18s) |\n"
        "| adservice 响应 | ✅ 4800ms → 60ms |\n\n"
        "⏳ 进入 **Recovering** 状态，开始恢复验证..."
    )
    _update_card(_msg_ids["exec_card"],
                 _build_execution_card_done(
                     "P-1001", "删除异常 Pod 触发重建",
                     exec_result, exec_steps_done))

    _wait(3)

    # ================================================================
    # 📉 恢复验证
    # ================================================================
    _pause("📉 恢复验证第 1 轮")
    round1_time = time.strftime('%H:%M:%S')
    verify_round1 = (
        f"**第 1 轮** ({round1_time})  ·  止损完成后 ~30s\n\n"
        "| 告警 | 服务 | 指标 | 状态 |\n"
        "|------|------|------|------|\n"
        "| A: ServiceHighErrorRate | checkoutservice | P99=1200ms (↓) | ⏳ 恢复中 |\n"
        "| B: ServiceSuccessRateDrop | checkoutservice | 成功率 92.1% (↑) | ⏳ 恢复中 |\n"
        "| C: ServiceHighLatency | userservice | P99=3100ms (→) | ❌ 未恢复 |\n\n"
        "A/B 指标在好转，C 暂无变化。继续观察..."
    )
    _msg_ids["recovery_card"] = _reply_card_in_thread(
        _msg_ids["alert_a"],
        _build_recovery_card("P-1001", "恢复验证", verify_round1, "verifying"))

    _wait(8, "等待指标进一步恢复...")

    _pause("📉 恢复验证第 2 轮")
    round2_time = time.strftime('%H:%M:%S')
    verify_rounds_all = (
        f"**第 1 轮** ({round1_time})  ·  止损完成后 ~30s\n\n"
        "| 告警 | 服务 | 指标 | 状态 |\n"
        "|------|------|------|------|\n"
        "| A: ServiceHighErrorRate | checkoutservice | P99=1200ms (↓) | ⏳ 恢复中 |\n"
        "| B: ServiceSuccessRateDrop | checkoutservice | 成功率 92.1% (↑) | ⏳ 恢复中 |\n"
        "| C: ServiceHighLatency | userservice | P99=3100ms (→) | ❌ 未恢复 |\n\n"
        "---\n\n"
        f"**第 2 轮** ({round2_time})  ·  止损完成后 ~1min\n\n"
        "| 告警 | 服务 | 指标 | 状态 |\n"
        "|------|------|------|------|\n"
        "| A: ServiceHighErrorRate | checkoutservice | P99=180ms ✅ | ✅ 已恢复 |\n"
        "| B: ServiceSuccessRateDrop | checkoutservice | 成功率 99.8% ✅ | ✅ 已恢复 |\n"
        "| C: ServiceHighLatency | userservice | P99=3050ms ❌ | ❌ 未恢复 |\n\n"
        "🟢 A/B 已恢复正常\n"
        "🔴 C 仍然异常 — 止损方案对 C 无效"
    )
    _update_card(_msg_ids["recovery_card"],
                 _build_recovery_card("P-1001", "恢复验证",
                                      verify_rounds_all, "partial"))

    _wait(3, "Agent 准备将C从P-1001移除...")

    # 告警A话题：通知C被移除
    _pause("📤 告警A话题：通知C已移除P-1001")
    _reply(_msg_ids["alert_a"],
           "📤 恢复验证发现告警C（userservice）未恢复，"
           "判断初始归并有误。\n"
           "已将告警C从 **P-1001** 移除，将对C进行独立分析。")

    _wait(2)

    # 告警C话题：说明归并错误，重新分析
    _pause("⚡ 告警C话题：说明归并错误，重新分析")
    _reply(_msg_ids["alert_c"],
           "⚡ **P-1001 已止损成功，但本告警未恢复。**\n"
           "说明初始归并判断有误（与 adservice 配置变更无关），"
           "现在从 P-1001 移除，重新进行独立 RCA 分析。")

    _wait(2)

    # 告警C话题：发新的分析卡片
    correction_steps_thinking = (
        "1. ✅ 排除 adservice 配置变更（P-1001 已修复，C 未恢复）\n"
        "2. ✅ Prometheus: userservice CPU > 95%\n"
        "3. ✅ Loki: 大量 `GC overhead limit exceeded` 警告\n"
        "4. ⏳ 关联 JVM 配置和近期变更..."
    )
    _msg_ids["analysis_c_v2"] = _reply_card_in_thread(
        _msg_ids["alert_c"],
        _build_analysis_card_thinking(
            "独立分析", "userservice 超时（重新分析）", correction_steps_thinking))

    _wait(5, "Agent 重新分析告警C...")

    # 更新为最终RCA
    _pause("🧠 告警C第二次RCA完成")
    correction_steps_done = (
        "1. ✅ 排除 adservice 配置变更（P-1001 已修复，C 未恢复）\n"
        "2. ✅ Prometheus: userservice CPU > 95%，内存使用 98.7%\n"
        "3. ✅ Loki: 大量 `GC overhead limit exceeded` 和 `Full GC` 日志\n"
        "4. ✅ JVM 配置: -Xmx=256m（不足），上次扩容后未同步调整\n"
        "5. ✅ 结论: JVM 堆内存不足 → 频繁 Full GC → 服务超时"
    )
    _update_card(_msg_ids["analysis_c_v2"], _build_analysis_card_done(
        "P-1002 (新建)", "用户中心 JVM 内存不足导致 GC 风暴",
        "**根因定位**：userservice JVM 堆内存配置不足（-Xmx=256m），"
        "随业务量增长导致频繁 Full GC，服务响应超时。\n\n"
        "**与 P-1001 无关**：adservice 配置变更已修复，本告警独立于 P-1001。\n\n"
        "📝 创建新问题 **P-1002**：「用户中心 JVM 内存不足导致 GC 风暴」\n"
        "_正在生成止损方案..._",
        correction_steps_done,
        "⭐⭐⭐⭐ (85%)",
        color="orange"))

    _wait(3)

    # ================================================================
    # 🎉 P-1001 消除
    # ================================================================
    _pause("🎉 P-1001 消除")
    _reply_card_in_thread(_msg_ids["alert_a"], _build_status_card(
        "P-1001", "营销服务配置变更导致交易超时",
        "resolved",
        "告警A: checkoutservice P99=180ms ✅\n"
        "告警B: checkoutservice 成功率 99.8% ✅\n"
        "告警C: 已移除（独立为 P-1002）\n\n"
        "处理耗时：约 12 分钟"))

    _wait(1)

    _reply(_msg_ids["alert_b"],
           "🎉 P-1001 已消除，交易服务成功率已恢复至 99.8%。")

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
    print("🤖 值班虚拟员工 Mock 演示 — 完美场景版")
    print(f"{'=' * 60}")
    print(f"  模式: {desc}")
    print(f"  飞书群: {feishu_api._resolve_chat_id(None)}")
    print(f"  时间倍率: {_SCALE:.2f}x")
    print(f"  场景: Agent端到端自主处理（仅需审批）")
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
