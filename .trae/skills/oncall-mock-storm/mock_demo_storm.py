#!/usr/bin/env python3
"""
值班虚拟员工 Mock 演示 — 报警风暴版

模拟基础设施故障引发大规模报警风暴：K8s 节点资源耗尽导致 5 条告警在 30 秒内密集到达。
Agent 检测到风暴 → 关联分析 → 批量静默 → 恢复验证。

三幕场景：
  Act 1: 报警风暴识别 — 5 条告警密集到达，Agent 检测到风暴模式
  Act 2: 关联分析 + 风暴归因 — 定位根因为节点资源耗尽，批量静默
  Act 3: 故障恢复 + 取消静默 — 人工修复后取消静默，恢复验证通过

交互特点：
  - Agent 分析以卡片形式呈现，支持展开/收起查看分析过程
  - 分析完成后卡片原地更新为结论
  - 消息精简，不冗长

用法：
  python3 mock_demo_storm.py                   # 标准模式（约 3-4 分钟）
  python3 mock_demo_storm.py --duration 300    # 指定总时长 5 分钟
  python3 mock_demo_storm.py --fast            # 快速模式（约 40s）
  python3 mock_demo_storm.py --step            # 单步模式（按回车继续）
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

_BASE_TOTAL_SECONDS = 75.0
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


def _build_storm_summary_card(alert_count, service_count, duration_sec, alerts_table_md):
    """报警风暴检测摘要卡片：红色头，展示风暴统计和告警列表。"""
    return {
        "config": {"update_multi": True, "wide_screen_mode": True},
        "header": {
            "template": "red",
            "title": {"tag": "plain_text",
                      "content": f"⚠️ 报警风暴检测 — {alert_count} 条告警 / {duration_sec} 秒"},
        },
        "elements": [
            {"tag": "markdown",
             "content": f"过去 {duration_sec} 秒内收到 **{alert_count} 条告警**，"
                        f"涉及 **{service_count} 个服务**，触发报警风暴模式。\n\n"
                        "已暂停逐个分析，转为关联分析。"},
            {"tag": "hr"},
            {"tag": "markdown", "content": alerts_table_md},
        ],
    }


# ============================================================
# 演示主流程
# ============================================================

def run_demo():
    global _start_time, _oncall_open_id
    _start_time = time.time()

    member = feishu_api.find_member_by_name(name=_ONCALL_PERSON_NAME)
    if member:
        _oncall_open_id = member.get("member_id")
        print(f"  👤 值班人: {_ONCALL_PERSON_NAME} (open_id: {_oncall_open_id[:12]}...)")
    else:
        print(f"  ⚠️ 未在群里找到 {_ONCALL_PERSON_NAME}，将以文本方式 @")

    # ================================================================
    # 🎬 ACT 1: 报警风暴识别 (~20s base)
    # ================================================================
    print(f"\n  {'━' * 50}")
    print(f"  🎬 第一幕：报警风暴识别")
    print(f"  {'━' * 50}")

    # --- 告警 1: NodeHighCPU ---
    _pause("🚨 告警1到达：NodeHighCPU (Critical)")
    _msg_ids["alert_1"] = _send_card(_build_alert_card(
        "NodeHighCPU", "k8s-node-pool", "critical",
        "K8s 节点 n128-052-031 CPU 使用率 98.7%",
        alert_id="AG-40001",
        env="prod",
        rule_name="NodeHighCPU",
        oncall_users=["赵欣欣"],
        tags={"_env": "prod", "_pod_name": "node-exporter-xz9k2",
              "host": "n128-052-031", "node": "n128-052-031"},
        dashboard_url="https://grafana.example.com/d/k8s-node-overview",
        duration_min=1))

    _wait(2, "Agent 检测到新告警...")

    _pause("🤖 Agent ACK 告警1")
    _reply(_msg_ids["alert_1"], "🤖 收到，已ACK并屏蔽报警30min，现在开始分析。")

    # --- 告警 2: PodCrashLoopBackOff ---
    _wait(2)
    _pause("🚨 告警2到达：PodCrashLoopBackOff (Critical)")
    _msg_ids["alert_2"] = _send_card(_build_alert_card(
        "PodCrashLoopBackOff", "checkoutservice", "critical",
        "Pod checkout-7b5f8d9c6-x2k9m CrashLoopBackOff 重启 5 次",
        alert_id="AG-40002",
        env="prod",
        rule_name="PodCrashLoopBackOff",
        oncall_users=["赵欣欣"],
        tags={"_env": "prod", "_pod_name": "checkout-7b5f8d9c6-x2k9m",
              "host": "n128-052-031", "node": "n128-052-031"},
        dashboard_url="https://grafana.example.com/d/k8s-pod-overview",
        duration_min=0))

    _wait(1)
    _reply(_msg_ids["alert_2"], "🤖 收到，已ACK并屏蔽报警30min，现在开始分析。")

    # --- 告警 3: ServiceHighErrorRate ---
    _wait(1)
    _pause("🚨 告警3到达：ServiceHighErrorRate (Warning)")
    _msg_ids["alert_3"] = _send_card(_build_alert_card(
        "ServiceHighErrorRate", "adservice", "warning",
        "adservice 错误率从 0.1% 飙升至 45%",
        alert_id="AG-40003",
        env="prod",
        rule_name="ServiceHighErrorRate",
        oncall_users=["赵欣欣"],
        tags={"_env": "prod", "_pod_name": "adservice-6f4b8c7d5-m3n7p",
              "host": "n128-052-031", "node": "n128-052-031"},
        dashboard_url="https://grafana.example.com/d/adservice-overview",
        duration_min=0))

    _wait(1)
    _reply(_msg_ids["alert_3"], "🤖 收到，已ACK并屏蔽报警30min，现在开始分析。")

    # --- 告警 4: PodOOMKilled ---
    _wait(1)
    _pause("🚨 告警4到达：PodOOMKilled (Critical)")
    _msg_ids["alert_4"] = _send_card(_build_alert_card(
        "PodOOMKilled", "cartservice", "critical",
        "cartservice Pod 因 OOM 被连续 Kill",
        alert_id="AG-40004",
        env="prod",
        rule_name="PodOOMKilled",
        oncall_users=["赵欣欣"],
        tags={"_env": "prod", "_pod_name": "cartservice-5d9f8b7c4-q8r2s",
              "host": "n128-052-031", "node": "n128-052-031"},
        dashboard_url="https://grafana.example.com/d/k8s-pod-overview",
        duration_min=0))

    _wait(1)
    _reply(_msg_ids["alert_4"], "🤖 收到，已ACK并屏蔽报警30min，现在开始分析。")

    # --- 告警 5: ServiceHighLatency ---
    _wait(1)
    _pause("🚨 告警5到达：ServiceHighLatency (Warning)")
    _msg_ids["alert_5"] = _send_card(_build_alert_card(
        "ServiceHighLatency", "productcatalogservice", "warning",
        "商品服务 P99 延迟从 80ms 升至 4200ms",
        alert_id="AG-40005",
        env="prod",
        rule_name="ServiceHighLatency",
        oncall_users=["赵欣欣"],
        tags={"_env": "prod", "_pod_name": "productcatalog-8c6d7e5f3-v4w1x",
              "host": "n128-052-031", "node": "n128-052-031"},
        dashboard_url="https://grafana.example.com/d/productcatalog-overview",
        duration_min=0))

    _wait(1)

    # --- ⚠️ Agent 检测到风暴 ---
    _pause("⚠️ Agent 检测到报警风暴！发送风暴检测卡片")
    storm_table = (
        "| 告警 | 服务 | 级别 | Alert Group |\n"
        "|------|------|------|-------------|\n"
        "| NodeHighCPU | k8s-node-pool | critical | AG-40001 |\n"
        "| PodCrashLoopBackOff | checkoutservice | critical | AG-40002 |\n"
        "| ServiceHighErrorRate | adservice | warning | AG-40003 |\n"
        "| PodOOMKilled | cartservice | critical | AG-40004 |\n"
        "| ServiceHighLatency | productcatalogservice | warning | AG-40005 |"
    )
    _msg_ids["storm_card"] = _reply_card_in_thread(
        _msg_ids["alert_1"],
        _build_storm_summary_card(5, 4, 30, storm_table))

    _wait(1)
    _reply_at_oncall(_msg_ids["alert_1"],
                     "检测到报警风暴（5条/30秒），已切换为关联分析模式。")

    _wait(2)

    # ================================================================
    # 🎬 ACT 2: 关联分析 + 风暴归因 (~25s base)
    # ================================================================
    print(f"\n  {'━' * 50}")
    print(f"  🎬 第二幕：关联分析 + 风暴归因")
    print(f"  {'━' * 50}")

    # --- 发送分析中卡片 ---
    _pause("🔍 Agent 开始风暴关联分析")
    analysis_steps = (
        "1. ✅ 5/5 告警均发生在同一 K8s 节点 n128-052-031\n"
        "2. ✅ 节点 CPU 98.7%，内存 96.2%\n"
        "3. ✅ kubelet 日志: `eviction manager: attempting to reclaim resources`\n"
        "4. ⏳ 确认节点故障范围..."
    )
    _msg_ids["analysis_storm"] = _reply_card_in_thread(
        _msg_ids["alert_1"],
        _build_analysis_card_thinking(
            "风暴关联分析", "5 条告警关联性分析", analysis_steps))

    _wait(5, "Agent 关联分析中...")

    # --- 更新为分析完成 ---
    _pause("🧠 关联分析完成，更新卡片")
    analysis_steps_done = (
        "1. ✅ 5/5 告警均发生在同一 K8s 节点 n128-052-031\n"
        "2. ✅ 节点 CPU 98.7%，内存 96.2%\n"
        "3. ✅ kubelet 日志: `eviction manager: attempting to reclaim resources`\n"
        "4. ✅ 节点上 4 个服务 Pod 均受影响（驱逐/OOMKill/性能劣化）"
    )
    conclusion_md = (
        "**根因定位**：K8s 节点 n128-052-031 内存和 CPU 资源耗尽，"
        "触发 kubelet eviction，导致该节点上所有 Pod 被驱逐或 OOMKill。\n\n"
        "**影响范围**：checkoutservice / adservice / cartservice / productcatalogservice\n\n"
        "📝 已创建问题 **P-2001**\n"
        "🔕 **建议：一键静默以下 5 条告警 2 小时**，专心排查节点故障。"
    )
    _update_card(_msg_ids["analysis_storm"], _build_analysis_card_done(
        "P-2001", "K8s 节点 n128-052-031 资源耗尽",
        conclusion_md,
        analysis_steps_done,
        "⭐⭐⭐⭐ (85%)",
        color="orange"))

    _wait(1)
    _reply_at_oncall(_msg_ids["alert_1"],
                     "风暴归因完成，建议一键静默 5 条告警 2 小时，详见上方卡片。")

    _wait(3, "等待值班人确认...")

    # --- 值班人确认 ---
    _pause("👤 值班人确认一键静默")
    _human_reply_in_thread(
        _msg_ids["alert_1"],
        f"👨‍💻 [{_ONCALL_PERSON_NAME}]\n"
        "分析得对，这个节点昨晚有个大数据任务没清理干净，吃满了资源。"
        "一键静默吧，我去处理节点。")

    _wait(2)

    _pause("🤖 Agent 开始批量静默")
    _reply(_msg_ids["alert_1"], "🤖 收到，正在批量静默 5 条告警（2 小时）...")

    _wait(2)

    # --- 批量静默完成卡片 ---
    _pause("✅ 批量静默完成，发送执行结果卡片")
    silence_expire = time.strftime("%H:%M", time.localtime(time.time() + 7200))
    silence_result_md = (
        "| 告警 | Alert Group | 操作 |\n"
        "|------|------------|------|\n"
        "| NodeHighCPU | AG-40001 | ✅ 已静默 2h |\n"
        "| PodCrashLoopBackOff | AG-40002 | ✅ 已静默 2h |\n"
        "| ServiceHighErrorRate | AG-40003 | ✅ 已静默 2h |\n"
        "| PodOOMKilled | AG-40004 | ✅ 已静默 2h |\n"
        "| ServiceHighLatency | AG-40005 | ✅ 已静默 2h |\n\n"
        f"静默到期时间：{silence_expire}\n"
        "届时将自动恢复报警推送。"
    )
    _msg_ids["silence_card"] = _reply_card_in_thread(
        _msg_ids["alert_1"],
        {
            "config": {"update_multi": True, "wide_screen_mode": True},
            "header": {
                "template": "green",
                "title": {"tag": "plain_text", "content": "✅ 批量静默完成"},
            },
            "elements": [
                {"tag": "markdown", "content": silence_result_md},
            ],
        })

    _wait(3)

    # ================================================================
    # 🎬 ACT 3: 故障恢复 + 取消静默 (~30s base)
    # ================================================================
    print(f"\n  {'━' * 50}")
    print(f"  🎬 第三幕：故障恢复 + 取消静默")
    print(f"  {'━' * 50}")

    _wait(5, "值班人处理节点中...")

    # --- 值班人请求取消静默 ---
    _pause("👤 值班人请求提前取消静默")
    _human_reply_in_thread(
        _msg_ids["alert_1"],
        f"👨‍💻 [{_ONCALL_PERSON_NAME}]\n"
        "节点上的大数据任务已经清理了，Pod 在陆续恢复中。"
        "帮我提前取消静默，我看下恢复情况。")

    _wait(2)

    _pause("🤖 Agent 取消静默")
    _reply(_msg_ids["alert_1"], "🤖 收到，正在取消所有告警的静默...")

    _wait(2)

    # --- 静默已取消卡片 ---
    _pause("🔔 静默已取消")
    _msg_ids["unsilence_card"] = _reply_card_in_thread(
        _msg_ids["alert_1"],
        {
            "config": {"update_multi": True, "wide_screen_mode": True},
            "header": {
                "template": "blue",
                "title": {"tag": "plain_text", "content": "🔔 静默已取消"},
            },
            "elements": [
                {"tag": "markdown",
                 "content": "已取消 5 条告警的静默，恢复正常报警推送。\n\n开始恢复验证..."},
            ],
        })

    _wait(3, "开始恢复验证...")

    # --- 恢复验证第 1 轮 ---
    _pause("📉 恢复验证第 1 轮")
    round1_time = time.strftime("%H:%M:%S")
    verify_round1 = (
        f"**第 1 轮** ({round1_time})  ·  取消静默后 ~30s\n\n"
        "| 指标 | 故障时 | 当前 | 状态 |\n"
        "|------|--------|------|------|\n"
        "| 节点 CPU | 98.7% | 35.2% | ✅ |\n"
        "| 节点内存 | 96.2% | 52.1% | ✅ |\n"
        "| Pod 运行数 | 2/6 | 6/6 | ✅ |\n"
        "| checkout P99 | >5000ms | 180ms | ✅ |\n"
        "| adservice 错误率 | 45% | 0.2% | ✅ |"
    )
    _msg_ids["recovery_card"] = _reply_card_in_thread(
        _msg_ids["alert_1"],
        _build_recovery_card("P-2001", "恢复验证", verify_round1, "verifying"))

    _wait(5, "等待指标进一步稳定...")

    # --- 恢复验证第 2 轮 → 全部通过 ---
    _pause("✅ 恢复验证第 2 轮 → 全部通过")
    round2_time = time.strftime("%H:%M:%S")
    verify_rounds_all = (
        f"**第 1 轮** ({round1_time})  ·  取消静默后 ~30s\n\n"
        "| 指标 | 故障时 | 当前 | 状态 |\n"
        "|------|--------|------|------|\n"
        "| 节点 CPU | 98.7% | 35.2% | ✅ |\n"
        "| 节点内存 | 96.2% | 52.1% | ✅ |\n"
        "| Pod 运行数 | 2/6 | 6/6 | ✅ |\n"
        "| checkout P99 | >5000ms | 180ms | ✅ |\n"
        "| adservice 错误率 | 45% | 0.2% | ✅ |\n\n"
        "---\n\n"
        f"**第 2 轮** ({round2_time})  ·  取消静默后 ~2min\n\n"
        "| 指标 | 故障时 | 当前 | 状态 |\n"
        "|------|--------|------|------|\n"
        "| 节点 CPU | 98.7% | 33.8% | ✅ |\n"
        "| 节点内存 | 96.2% | 50.5% | ✅ |\n"
        "| Pod 运行数 | 2/6 | 6/6 | ✅ |\n"
        "| checkout P99 | >5000ms | 150ms | ✅ |\n"
        "| adservice 错误率 | 45% | 0.1% | ✅ |\n\n"
        "全部指标已恢复至正常水平 ✅"
    )
    _update_card(_msg_ids["recovery_card"],
                 _build_recovery_card("P-2001", "恢复验证",
                                      verify_rounds_all, "passed"))

    _wait(2)

    # --- 最终状态卡片 ---
    _pause("🎉 发送最终状态卡片：P-2001 已消除")
    total_minutes = int((time.time() - _start_time) / 60)
    final_body = (
        "告警 A~E: 全部已恢复 ✅\n"
        "节点 n128-052-031 资源已恢复正常\n\n"
        f"处理耗时：约 {total_minutes} 分钟\n"
        "处理方式：报警风暴检测 → 关联分析 → 批量静默 → 人工修复 → 恢复验证"
    )
    _reply_card_in_thread(_msg_ids["alert_1"], _build_status_card(
        "P-2001", "K8s 节点 n128-052-031 资源耗尽",
        "resolved", final_body))

    _wait(1)
    _reply(_msg_ids["alert_1"],
           "🎉 P-2001 已消除，5 条告警全部恢复，节点资源正常。")

    _wait(2)

    # --- 值班人点赞 ---
    _pause("👤 值班人回复")
    _human_reply_in_thread(_msg_ids["alert_1"],
                           f"👨‍💻 [{_ONCALL_PERSON_NAME}]\n👍")

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
    print(f"  场景: 报警风暴→关联分析→批量静默→恢复验证")
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
