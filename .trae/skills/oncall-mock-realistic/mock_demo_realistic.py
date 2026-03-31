#!/usr/bin/env python3
"""
值班虚拟员工 Mock 演示 — 真实场景版

模拟 Agent 犯错、卡住、人类纠偏和接管的完整人机协作流程。

四幕场景：
  Act 1: RCA 分析错误 → 值班人给出新方向 → Agent 重新分析
  Act 2: 止损方案有风险 → 值班人修改方案 → 重新审批
  Act 3: 新告警 Agent 分析卡住 → 主动求助 → 值班人告知已知问题 → 静默
  Act 4: 恢复验证不彻底 → 值班人决定接管

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

_BASE_TOTAL_SECONDS = 95.0
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
    """在群里直接发送卡片（顶级消息）。"""
    resp = feishu_api.send_card(card=card)
    msg_id = resp.get("data", {}).get("message_id", "")
    print(f"         📨 卡片已发送 [{msg_id[:20]}...]")
    return msg_id


def _reply_card_in_thread(parent_msg_id: str, card: dict) -> str:
    """在话题下回复卡片消息。"""
    card_json = json.dumps(card, ensure_ascii=False)
    resp = feishu_api.reply_message(
        parent_msg_id, card_json, msg_type="interactive", reply_in_thread=True)
    msg_id = resp.get("data", {}).get("message_id", "")
    print(f"         📨 话题内卡片已发送 [{msg_id[:20]}...]")
    return msg_id


def _reply(message_id: str, text: str) -> str:
    """在话题下回复纯文本。"""
    resp = feishu_api.reply_in_thread(message_id, text)
    return resp.get("data", {}).get("message_id", "")


def _reply_at_oncall(parent_msg_id: str, text: str) -> str:
    """在话题下回复并 @值班人。"""
    if _oncall_open_id:
        resp = feishu_api.reply_at_message(
            parent_msg_id, _oncall_open_id, text, in_thread=True)
        return resp.get("data", {}).get("message_id", "")
    else:
        return _reply(parent_msg_id, f"@{_ONCALL_PERSON_NAME} {text}")


def _human_reply_in_thread(parent_msg_id: str, text: str) -> str:
    """模拟人类值班人在话题下回复。"""
    return _reply(parent_msg_id, text)


def _update_approval_card(card_msg_id: str, problem_id: str, title: str,
                          root_cause: str, action_plan: str,
                          result: str = "approved") -> None:
    """审批后更新卡片为已审批状态，按钮替换为结果标记。"""
    if result == "approved":
        status_text = "✅ 已批准"
        color = "green"
    else:
        status_text = "❌ 已拒绝"
        color = "red"

    updated_card = {
        "config": {"update_multi": True, "wide_screen_mode": True},
        "header": {
            "template": color,
            "title": {"tag": "plain_text",
                      "content": f"🧾 止损审批 - {problem_id}  [{status_text}]"},
        },
        "elements": [
            {"tag": "markdown", "content": f"**问题**: {title}"},
            {"tag": "markdown", "content": f"**根因**: {root_cause}"},
            {"tag": "hr"},
            {"tag": "markdown", "content": f"**止损方案**: {action_plan}"},
            {"tag": "hr"},
            {"tag": "markdown",
             "content": f"**审批结果**：{status_text}\n\n"
                        f"审批人：{_ONCALL_PERSON_NAME} | 时间：{time.strftime('%H:%M:%S')}"},
        ],
    }
    feishu_api.update_card(card_msg_id, updated_card)
    print(f"         📝 卡片已更新为 [{status_text}]")


# ============================================================
# 卡片构建
# ============================================================

def _build_alert_card(alert_name, service, severity, summary,
                      alert_id=""):
    color_map = {"critical": "red", "warning": "orange", "info": "blue"}
    emoji_map = {"critical": "🔴", "warning": "🟡", "info": "🔵"}
    return {
        "config": {"update_multi": True, "wide_screen_mode": True},
        "header": {
            "template": color_map.get(severity, "red"),
            "title": {"tag": "plain_text",
                      "content": f"{emoji_map.get(severity, '🚨')} [触发中] {alert_name}"},
        },
        "elements": [
            {"tag": "column_set", "flex_mode": "bisect", "columns": [
                {"tag": "column", "width": "weighted", "weight": 1, "elements": [
                    {"tag": "markdown", "content": f"**服务**: {service}"},
                ]},
                {"tag": "column", "width": "weighted", "weight": 1, "elements": [
                    {"tag": "markdown", "content": f"**级别**: {severity}"},
                ]},
            ]},
            {"tag": "column_set", "flex_mode": "bisect", "columns": [
                {"tag": "column", "width": "weighted", "weight": 1, "elements": [
                    {"tag": "markdown", "content": f"**时间**: {time.strftime('%H:%M:%S')}"},
                ]},
                {"tag": "column", "width": "weighted", "weight": 1, "elements": [
                    {"tag": "markdown", "content": f"**Alert Group**: {alert_id or 'N/A'}"},
                ]},
            ]},
            {"tag": "hr"},
            {"tag": "markdown", "content": f"**摘要**: {summary}"},
        ],
    }


def _build_approval_card(problem_id, title, root_cause, action_plan):
    return {
        "config": {"update_multi": True, "wide_screen_mode": True},
        "header": {
            "template": "orange",
            "title": {"tag": "plain_text", "content": f"🧾 止损审批 - {problem_id}"},
        },
        "elements": [
            {"tag": "markdown", "content": f"**问题**: {title}"},
            {"tag": "markdown", "content": f"**根因**: {root_cause}"},
            {"tag": "hr"},
            {"tag": "markdown", "content": f"**止损方案**: {action_plan}"},
            {"tag": "hr"},
            {"tag": "markdown", "content": "⚠️ 请值班人确认是否执行以上止损方案："},
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

    # 查找值班人的 open_id，用于 @
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
        alert_id="AG-30001"))

    _wait(3, "Agent 检测到新告警...")

    _pause("🤖 Agent 回复：收到，开始分析")
    _reply(_msg_ids["alert_a"],
           "🤖 收到告警，我来处理。正在分析根因...\n\n"
           "将查询以下数据源：\n"
           "- Tempo: payment-gateway 调用链路\n"
           "- Prometheus: 服务指标\n"
           "- Loki: 错误日志")

    _wait(5, "Agent 正在查询链路和指标数据...")

    _reply(_msg_ids["alert_a"],
           "🔍 **分析进度**：\n"
           "- ✅ Trace 查询完成：payment-gateway 外部调用耗时异常\n"
           "- ✅ Loki 发现 `TLS handshake timeout` 错误日志\n"
           "- ⏳ 正在关联变更记录...")

    _wait(4, "Agent 基于日志关键词推导根因...")

    # Agent 给出了 **错误的** RCA，并 @值班人 请确认
    _pause("🤖 Agent 给出 RCA（❌ 错误的），@值班人请确认")
    _reply_at_oncall(_msg_ids["alert_a"],
                     "\n🧠 **RCA 分析完成**\n\n"
                     "**根因定位**：\n"
                     "Loki 日志中发现大量 `TLS handshake timeout` 错误。\n"
                     "推断 payment-gateway 的 **TLS 证书可能过期**，"
                     "导致与上游支付渠道的 HTTPS 握手失败。\n\n"
                     "**置信度**：⭐⭐⭐ (60%) — 中等\n\n"
                     "📝 已创建问题 **P-1003**：「支付网关 TLS 证书过期导致交易超时」\n\n"
                     "⚠️ 置信度中等，请确认根因是否正确。如判断有误请随时纠正。")

    _wait(5, "等待值班人确认或纠偏...")

    # 值班人在话题下回复纠偏
    _pause("👤 值班人在话题下纠偏：根因不对")
    _human_reply_in_thread(_msg_ids["alert_a"],
                           "👤 根因不对。TLS 证书上周刚换过，不可能过期。\n"
                           "你查一下是不是 **上游 DNS 解析** 的问题，"
                           "我记得 CoreDNS 最近有点不稳定。")

    _wait(2)

    _pause("🤖 Agent 接受纠偏，重新分析")
    _reply(_msg_ids["alert_a"],
           "🔄 **接受纠偏，正在重新分析**\n\n"
           "感谢值班人提示！已排除 TLS 证书原因。\n"
           "重新聚焦方向：**CoreDNS / DNS 解析异常**\n"
           "正在查询相关指标...")

    _wait(5, "Agent 重新查询 DNS 相关指标和日志...")

    _reply(_msg_ids["alert_a"],
           "🔍 **重新分析进度**：\n"
           "- ✅ Prometheus: CoreDNS 请求延迟从 5ms → 3200ms\n"
           "- ✅ Loki: CoreDNS 日志发现 `OOMKilled` 事件 (15:23)\n"
           "- ✅ K8s Events: coredns-5d78c9869d-xk7m2 被 OOMKill 重启了 3 次")

    _wait(3)

    _pause("🤖 Agent 给出更新后的 RCA（✅ 正确的）")
    _reply(_msg_ids["alert_a"],
           "🧠 **RCA 更新（基于值班人反馈重新分析）**\n\n"
           "**根因定位**：\n"
           "CoreDNS Pod `coredns-5d78c9869d-xk7m2` 于 15:23 因内存不足被 OOMKill。\n"
           "集群仅剩 1 个 CoreDNS 副本承载全部 DNS 解析，导致解析延迟飙升至 3200ms。\n"
           "payment-gateway 连接上游支付渠道时 DNS 解析超时 → TLS 握手超时 → 请求失败。\n\n"
           "**置信度**：⭐⭐⭐⭐⭐ (95%)\n"
           "**修正记录**：~~TLS 证书过期~~ → CoreDNS OOMKill 导致 DNS 解析超时\n\n"
           "_💡 TLS handshake timeout 日志是 DNS 超时的下游表现，并非根因本身。感谢值班人指出方向！_")

    _wait(3)

    # ================================================================
    # 🎬 ACT 2: 止损方案有风险 → 值班人修改
    # ================================================================
    print(f"\n  {'━' * 50}")
    print(f"  🎬 第二幕：止损方案有风险 → 值班人修改")
    print(f"  {'━' * 50}")

    _pause("🤖 Agent 生成止损方案（⚠️ 有风险的方案）")
    _reply(_msg_ids["alert_a"],
           "🔧 **止损方案（P-1003）**\n\n"
           "根因为 CoreDNS Pod OOMKill，建议执行：\n"
           "1. **删除异常 Pod** `coredns-5d78c9869d-xk7m2`，触发重建\n"
           "2. 重建后 CoreDNS 恢复正常内存状态\n\n"
           "⚠️ 需要值班人授权，正在发送审批请求...")

    _wait(2)

    # 审批卡片在话题下发送
    _pause("🧾 在话题下发送审批卡片 + @值班人")
    approval_v1_card = _build_approval_card(
        "P-1003", "CoreDNS OOMKill 导致 DNS 解析超时",
        "CoreDNS Pod OOMKill → 集群 DNS 解析延迟飙升 → payment-gateway 超时",
        "删除 CoreDNS Pod coredns-5d78c9869d-xk7m2，触发 K8s 重建")
    _msg_ids["approval_v1"] = _reply_card_in_thread(
        _msg_ids["alert_a"], approval_v1_card)

    _reply_at_oncall(_msg_ids["alert_a"],
                     "\n🔔 止损方案已生成，请审批上方卡片。")

    _wait(4, "值班人审阅止损方案...")

    # 值班人在话题下拒绝方案
    _pause("👤 值班人在话题下拒绝方案，提出修改")
    _human_reply_in_thread(_msg_ids["alert_a"],
                           "👤 ❌ 这个方案我不同意！CoreDNS 是集群核心组件，"
                           "现在只剩 1 个副本了，你直接删 Pod 的话整个集群 DNS 都会挂！\n\n"
                           "正确的做法是：**先给 CoreDNS 扩容到 3 副本**，"
                           "等新副本 Ready 之后再处理异常 Pod。\n"
                           "另外还要把 CoreDNS 的内存 limit 从 170Mi 调到 256Mi，防止再次 OOM。")

    _wait(1)

    # 更新第一张审批卡片为"已拒绝"
    _update_approval_card(
        _msg_ids["approval_v1"], "P-1003",
        "CoreDNS OOMKill 导致 DNS 解析超时",
        "CoreDNS Pod OOMKill → 集群 DNS 解析延迟飙升",
        "删除 CoreDNS Pod coredns-5d78c9869d-xk7m2",
        result="rejected")

    _wait(2)

    _pause("🤖 Agent 接受修改，更新方案")
    _reply(_msg_ids["alert_a"],
           "✅ **方案已更新（基于值班人反馈修改）**\n\n"
           "原方案风险点：直接删除唯一 CoreDNS Pod 会导致集群 DNS 中断。\n"
           "已采纳值班人建议，更新为：\n\n"
           "1. ~~删除异常 Pod~~ → **扩容 CoreDNS Deployment 副本数到 3**\n"
           "2. 等待新副本 Ready (约 30s)\n"
           "3. **调整内存 limit**: 170Mi → 256Mi（防止再次 OOM）\n\n"
           "📝 方案修改记录已写入 P-1003 时间线。")

    _wait(2)

    # 在话题下发送更新后的审批卡片
    _pause("🧾 在话题下发送更新后的审批卡片")
    approval_v2_card = _build_approval_card(
        "P-1003（v2）", "CoreDNS OOMKill 导致 DNS 解析超时",
        "CoreDNS Pod OOMKill → DNS 解析延迟飙升 → payment-gateway 超时",
        "① 扩容 CoreDNS 到 3 副本  ② 调整内存 limit 170Mi→256Mi  ③ 等待新副本 Ready")
    _msg_ids["approval_v2"] = _reply_card_in_thread(
        _msg_ids["alert_a"], approval_v2_card)

    _reply_at_oncall(_msg_ids["alert_a"],
                     "\n🔔 方案已更新，请审批上方新卡片。")

    _wait(4, "等待值班人审批...")

    # 值班人批准
    _pause("✅ 值班人批准更新后的方案")
    _update_approval_card(
        _msg_ids["approval_v2"], "P-1003（v2）",
        "CoreDNS OOMKill 导致 DNS 解析超时",
        "CoreDNS Pod OOMKill → DNS 解析延迟飙升",
        "① 扩容 CoreDNS 到 3 副本  ② 调整内存 limit  ③ 等新副本 Ready",
        result="approved")

    _reply(_msg_ids["alert_a"],
           "✅ **审批已通过**（方案v2）\n\n值班人已批准更新后的止损方案，正在执行...")

    _wait(2)

    _reply(_msg_ids["alert_a"],
           "🔧 **执行进度**：\n"
           "- ✅ 步骤1: CoreDNS 副本数已扩容至 3\n"
           "- ⏳ 步骤2: 等待新副本启动...")

    _wait(4, "K8s 正在创建新的 CoreDNS Pod...")

    _reply(_msg_ids["alert_a"],
           "🔧 **执行进度**：\n"
           "- ✅ 步骤1: CoreDNS 副本数已扩容至 3\n"
           "- ✅ 步骤2: 3 个副本均已 Ready (1/1)\n"
           "- ✅ 步骤3: 内存 limit 已调整为 256Mi\n\n"
           "⏳ 进入 **Recovering** 状态，开始恢复验证...")

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
        "Kafka consumer group order-events 消费 lag 从 50 飙升至 8500+，且持续增长",
        alert_id="AG-30002"))

    _wait(2)

    _reply(_msg_ids["alert_b"],
           "🤖 收到告警，正在分析。\n\n"
           "_💡 当前正在处理 P-1003（DNS 解析超时），同时并行分析此告警。_")

    _wait(5, "Agent 查询 Kafka 相关指标和日志...")

    _reply(_msg_ids["alert_b"],
           "🔍 **分析进度**：\n"
           "- ✅ 消费者实例状态正常，无报错\n"
           "- ✅ 生产端 QPS 无明显变化（稳定 ~2000 msg/s）\n"
           "- ✅ Kafka Broker 指标正常\n"
           "- ❌ 未发现 consumer 异常堆栈或重启记录")

    _wait(4, "Agent 尝试关联变更记录...")

    _reply(_msg_ids["alert_b"],
           "🔍 **继续排查**：\n"
           "- ✅ 近 24h 无相关 Deployment 变更\n"
           "- ✅ Kafka 集群配置无变更\n"
           "- ⚠️ 但 consumer 的每条消息处理耗时从 5ms → 200ms\n"
           "- ❌ 无法确定处理耗时变长的原因")

    _wait(3)

    # Agent 卡住了，主动 @值班人 求助
    _pause("❓ Agent 分析无果，@值班人 求助")
    _reply_at_oncall(_msg_ids["alert_b"],
                     "\n❓ **需要协助**\n\n"
                     "我暂时无法确定根因。目前排查结论：\n"
                     "- 消费者本身没有异常，没有报错也没有重启\n"
                     "- 生产端 QPS 没有变化，Kafka Broker 也正常\n"
                     "- 唯一发现：每条消息处理耗时从 5ms 增加到 200ms，但原因不明\n\n"
                     "**能否提供以下线索？**\n"
                     "1. order-processor 最近是否有发版或配置变更？\n"
                     "2. 是否有已知的 bug 或 issue 与此相关？\n"
                     "3. 是否需要我查看特定服务或组件的指标？\n\n"
                     "📝 已创建问题 **P-1004**：「Kafka 消费延迟异常增长」（待定根因）")

    _wait(5, "等待值班人提供线索...")

    # 值班人在话题下回复
    _pause("👤 值班人在话题下告知：已知 bug，静默")
    _human_reply_in_thread(_msg_ids["alert_b"],
                           "👤 这个我知道，是上周三发版引入的性能 bug，"
                           "order-processor 的批量查询逻辑改出了 N+1 问题。\n"
                           "修复 MR 已经提交了（#ISSUE-456），预计下周一发版修复。\n\n"
                           "不用止损了，**关联 ISSUE-456，然后静默 7 天**就行。")

    _wait(3)

    _pause("🤖 Agent 执行值班人指令：关联 Issue + 静默")
    _reply(_msg_ids["alert_b"],
           "✅ **已按值班人指令处理**\n\n"
           "1. ✅ 已关联 Issue: [ISSUE-456](https://jira.example.com/ISSUE-456) "
           "— order-processor N+1 查询性能 bug\n"
           "2. ✅ P-1004 已静默 7 天（至 2026-04-07）\n"
           "3. ✅ 关联 OnCall AlertGroup AG-30002 已静默\n\n"
           "📝 根因更新为：「已知 bug（ISSUE-456），"
           "order-processor 批量查询 N+1 问题，预计下周一修复」")

    _wait(1)

    # P-1004 静默卡片在话题下发
    _reply_card_in_thread(_msg_ids["alert_b"], _build_status_card(
        "P-1004", "Kafka 消费延迟异常增长",
        "silenced",
        "**处理结果**：已知 bug（ISSUE-456），静默至 2026-04-07\n\n"
        "**根因**: order-processor 批量查询 N+1 问题\n"
        "**修复计划**: 下周一发版修复"))

    _wait(3)

    # ================================================================
    # 🎬 ACT 4: 恢复验证不彻底 → 值班人接管
    # ================================================================
    print(f"\n  {'━' * 50}")
    print(f"  🎬 第四幕：恢复验证不彻底 → 值班人接管")
    print(f"  {'━' * 50}")

    _pause("📉 回到 P-1003：恢复验证第 1 轮")
    _reply(_msg_ids["alert_a"],
           "📉 **恢复验证 — 第 1/3 轮**\n\n"
           "| 指标 | 止损前 | 当前 | 状态 |\n"
           "|------|--------|------|------|\n"
           "| CoreDNS 请求延迟 | 3200ms | 850ms | ⏳ 好转中 |\n"
           "| CoreDNS 副本数 | 1 (OOMKill) | 3 (Ready) | ✅ 正常 |\n"
           "| payment-gateway P99 | 8000ms | 2100ms | ⏳ 好转中 |\n"
           "| 支付成功率 | 62.3% | 88.7% | ⏳ 好转中 |\n\n"
           "整体在好转，但尚未恢复到正常水位。继续观察...")

    _wait(6, "恢复验证第 2 轮（模拟等待 30s）...")

    _pause("📉 恢复验证第 2 轮 → 好转但未达标，@值班人")
    _reply_at_oncall(_msg_ids["alert_a"],
                     "\n📉 **恢复验证 — 第 2/3 轮**\n\n"
                     "| 指标 | 止损前 | 当前 | 正常值 | 状态 |\n"
                     "|------|--------|------|--------|------|\n"
                     "| CoreDNS 请求延迟 | 3200ms | 120ms | <10ms | ⚠️ 偏高 |\n"
                     "| CoreDNS 副本数 | 1 | 3 | 3 | ✅ 正常 |\n"
                     "| payment-gateway P99 | 8000ms | 950ms | <400ms | ⚠️ 偏高 |\n"
                     "| 支付成功率 | 62.3% | 96.1% | >99.5% | ⚠️ 未达标 |\n\n"
                     "🟡 各项指标**大幅好转**，但仍未完全恢复到正常水位：\n"
                     "- CoreDNS 延迟 120ms 仍远高于正常值 <10ms\n"
                     "- 支付成功率 96.1%，低于 SLO 阈值 99.5%\n\n"
                     "可能还有其他因素影响。建议进一步排查或人工介入。")

    _wait(5, "等待值班人决定...")

    # 值班人在话题下接管
    _pause("👤 值班人在话题下宣布接管")
    _human_reply_in_thread(_msg_ids["alert_a"],
                           "👤 好的，我来接管这个问题。\n"
                           "CoreDNS 延迟还是偏高，我怀疑是 CoreDNS 的 Corefile 配置里"
                           "缓存参数不对，需要我手动排查一下。\n"
                           "你先不要自动操作了。")

    _wait(3)

    _pause("🤖 Agent 确认移交，停止自动操作")
    _reply(_msg_ids["alert_a"],
           "👤 **问题已移交人工处理**\n\n"
           f"P-1003 已标记为 **人工处理中**（处理人：{_ONCALL_PERSON_NAME}），"
           "我将停止自动操作。\n\n"
           "**当前状态汇总**：\n"
           "- 根因：CoreDNS OOMKill → DNS 解析超时（已确认）\n"
           "- 已执行：扩容 CoreDNS 到 3 副本 + 调整内存 limit\n"
           "- 恢复情况：大幅好转但未完全恢复\n"
           "- 待排查：CoreDNS Corefile 缓存配置\n\n"
           "后续排查中有需要数据查询或分析的，随时 @我。🫡")

    _wait(3)

    # ================================================================
    # 📋 最终汇总
    # ================================================================
    _pause("📋 发送值守汇总卡片")
    _send_card(_build_status_card(
        "P-1003", "CoreDNS OOMKill 导致 DNS 解析超时",
        "takeover",
        "**处理时间线**：\n"
        "1. 🚨 告警到达 → Agent 分析\n"
        "2. ❌ Agent 初判 TLS 证书过期（错误）\n"
        f"3. 👤 {_ONCALL_PERSON_NAME} 纠偏 → 引导查 DNS\n"
        "4. ✅ Agent 重新分析 → CoreDNS OOMKill（正确）\n"
        "5. ⚠️ Agent 方案：删 Pod（有风险）→ ❌ 被拒绝\n"
        f"6. 👤 {_ONCALL_PERSON_NAME} 修改方案 → 扩容 + 调内存\n"
        "7. ✅ 执行止损 → 指标大幅好转\n"
        "8. ⚠️ 恢复验证未达标\n"
        f"9. 👤 {_ONCALL_PERSON_NAME} 接管，手动排查 Corefile\n\n"
        "---\n"
        "**其他问题**：\n"
        "🔇 P-1004（Kafka 消费延迟）— 已知 bug #ISSUE-456，静默 7 天"))

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
