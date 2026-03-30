#!/usr/bin/env python3
"""
值班虚拟员工 Mock 演示脚本

在飞书群中模拟完整的值班 Agent 交互流程（自然时序版）：
  - 告警交错到达，模拟真实值班场景
  - Agent 分析过程有中间状态消息
  - 审批等待期间新告警插入
  - 恢复验证 + 纠偏拆分

用法：
  python3 mock_demo.py                   # 标准模式（约 3-4 分钟）
  python3 mock_demo.py --duration 300    # 指定总时长 5 分钟
  python3 mock_demo.py --fast            # 快速模式（约 40s）
  python3 mock_demo.py --step            # 单步模式（每步按回车）

前置条件：
  1. .env 中配置了 app_id / app_secret / feishu_chat_id
  2. 飞书 App Bot 已加入目标群聊
"""

import json
import os
import sys
import time
from pathlib import Path

# ============================================================
# 路径初始化：定位项目根目录和 feishu_api
# ============================================================

_SKILL_DIR = Path(__file__).resolve().parent
_SKILLS_ROOT = _SKILL_DIR.parent
_FEISHU_API_DIR = _SKILLS_ROOT / "feishu-messenger"

if not _FEISHU_API_DIR.exists():
    print(f"  ❌ 未找到 feishu-messenger Skill: {_FEISHU_API_DIR}")
    print("  请确保 .trae/skills/feishu-messenger/ 存在")
    sys.exit(1)

if str(_FEISHU_API_DIR) not in sys.path:
    sys.path.insert(0, str(_FEISHU_API_DIR))

# 从 Skill 目录向上找项目根目录，加载 .env
_PROJECT_ROOT = _SKILLS_ROOT.parent.parent
_ENV_CANDIDATES = [
    _PROJECT_ROOT / ".env",
    _PROJECT_ROOT / "deploy" / "docker" / "alarm-service" / ".env",
]
for _env_path in _ENV_CANDIDATES:
    if _env_path.exists():
        with open(_env_path, "r") as _f:
            for _line in _f:
                _line = _line.strip()
                if not _line or _line.startswith("#"):
                    continue
                if "=" in _line:
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

# 所有 _wait() 调用的基准秒数之和（不含 step 暂停和网络延迟）
_BASE_TOTAL_SECONDS = 85.0

# 默认标准模式目标时长（秒）：约 3.5 分钟
_DEFAULT_DURATION = 210.0


def _parse_args():
    """解析命令行参数，返回 (mode, scale_factor)。"""
    fast = "--fast" in sys.argv
    step = "--step" in sys.argv
    duration = None

    for i, arg in enumerate(sys.argv):
        if arg == "--duration" and i + 1 < len(sys.argv):
            try:
                duration = float(sys.argv[i + 1])
            except ValueError:
                print(f"  ⚠️  --duration 参数无效: {sys.argv[i + 1]}，使用默认值")

    if step:
        # 单步模式：等待时间用最短的，用户自己控制节奏
        return "step", 1.0 / 3.0
    elif duration is not None:
        # 指定时长模式：自动算倍率
        scale = max(0.2, duration / _BASE_TOTAL_SECONDS)
        return f"duration({duration:.0f}s)", scale
    elif fast:
        return "fast", 1.0 / 3.0
    else:
        # 标准模式
        scale = _DEFAULT_DURATION / _BASE_TOTAL_SECONDS
        return "standard", scale


MODE, _SCALE = _parse_args()
STEP_MODE = MODE == "step"
_msg_ids = {}
_start_time = 0.0


def _t(seconds: float) -> float:
    """将基准等待秒数按倍率缩放。"""
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


def _reply(message_id: str, text: str) -> str:
    resp = feishu_api.reply_in_thread(message_id, text)
    return resp.get("data", {}).get("message_id", "")


def _send_text(text: str) -> str:
    resp = feishu_api.send_text(text=text)
    return resp.get("data", {}).get("message_id", "")


# ============================================================
# 卡片构建
# ============================================================

def _build_alert_card(alert_name, service, severity, summary,
                      status="firing", alert_id=""):
    color_map = {"critical": "red", "warning": "orange", "info": "blue"}
    emoji_map = {"critical": "🔴", "warning": "🟡", "info": "🔵"}
    header_color = color_map.get(severity, "red")
    emoji = emoji_map.get(severity, "🚨")
    status_text = "已恢复" if status == "resolved" else "触发中"
    header_text = f"{emoji} [{status_text}] {alert_name}"
    if status == "resolved":
        header_color = "green"

    return {
        "config": {"update_multi": True, "wide_screen_mode": True},
        "header": {
            "template": header_color,
            "title": {"tag": "plain_text", "content": header_text},
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
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "✅ 同意执行"},
                    "type": "primary",
                    "behaviors": [{"type": "callback", "value": {
                        "action": "approval_confirm",
                        "approval_id": f"ACT-{problem_id}",
                    }}],
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "❌ 拒绝"},
                    "type": "danger",
                    "behaviors": [{"type": "callback", "value": {
                        "action": "approval_reject",
                        "approval_id": f"ACT-{problem_id}",
                    }}],
                },
            ]},
            {"tag": "hr"},
            {"tag": "markdown", "content": "🔔 已加急通知值班人"},
        ],
    }


def _build_summary_card(problem_id, title, status, alerts_summary):
    if status == "resolved":
        color, emoji, status_text = "green", "🎉", "已消除"
    else:
        color, emoji, status_text = "blue", "📋", "处理中"

    return {
        "config": {"update_multi": True, "wide_screen_mode": True},
        "header": {
            "template": color,
            "title": {"tag": "plain_text", "content": f"{emoji} {problem_id} {status_text}"},
        },
        "elements": [
            {"tag": "markdown", "content": f"**问题**: {title}"},
            {"tag": "hr"},
            {"tag": "markdown", "content": alerts_summary},
        ],
    }


# ============================================================
# 演示主流程 — 按自然时间线展开
# ============================================================

def run_demo():
    global _start_time
    _start_time = time.time()

    # ── 🚨 告警 A 到达 ──
    _pause("🚨 告警A到达：交易服务响应超时 (Critical)")
    _msg_ids["alert_a"] = _send_card(_build_alert_card(
        "ServiceHighErrorRate", "checkoutservice", "critical",
        "交易服务响应超时，P99 延迟从 200ms 飙升至 5000ms，影响交易链路",
        alert_id="AG-20001"))

    _wait(2, "Agent 检测到新告警...")

    _pause("🤖 Agent 回复告警A：收到，开始分析")
    _reply(_msg_ids["alert_a"], "🤖 收到告警，我来处理。正在分析根因...")

    _wait(4, "Agent 正在查询 Grafana Tempo 链路数据...")

    _reply(_msg_ids["alert_a"],
           "🔍 **分析进度**：\n"
           "- ✅ 已查询 Trace：发现 checkoutservice → adservice 调用链 P99=4800ms\n"
           "- ⏳ 正在排查 adservice 异常原因...")

    _wait(5, "Agent 正在关联近期变更记录...")

    # ── 🚨 告警 B 到达（A 还在分析中） ──
    _pause("🚨 告警B到达：交易服务成功率下跌 (Warning) ← A还在分析中")
    _msg_ids["alert_b"] = _send_card(_build_alert_card(
        "ServiceSuccessRateDrop", "checkoutservice", "warning",
        "交易服务接口成功率从 99.9% 跌至 85.2%",
        alert_id="AG-20002"))

    _wait(2)

    _reply(_msg_ids["alert_b"],
           "🤖 收到告警，正在分析。\n\n"
           "_💡 注意：当前已有一个关联的 critical 告警（AG-20001: checkoutservice 响应超时）正在分析中，"
           "将优先完成该分析后统一研判。_")

    _wait(4, "Agent 继续分析告警A：查询 Loki 日志 + 变更记录...")

    # ── 🧠 告警 A 的 RCA 完成 ──
    _pause("🧠 Agent 完成告警A的 RCA 分析")
    _reply(_msg_ids["alert_a"],
           "🧠 **RCA 分析完成**\n\n"
           "**根因定位**：\n"
           "Trace 显示 checkoutservice → **adservice（营销服务）** 调用延迟极高（P99=4800ms）。\n"
           "排查发现 adservice 于 **15:32** 执行了一次配置变更（变更ID: CHG-2026-0331-007），"
           "该变更引入了一个异常的促销规则计算逻辑，导致 adservice 处理耗时从 50ms 飙升至 4800ms，"
           "进而导致下游 checkoutservice 调用超时。\n\n"
           "**影响范围**：checkoutservice → adservice 调用链路\n"
           "**影响时长**：已持续约 15 分钟\n\n"
           "📝 已创建问题 **P-1001**：「营销服务配置变更导致交易超时」")

    _wait(3)

    # ── 🔗 告警 B 归并 ──
    _pause("🔗 Agent 分析告警B → 判定为 P-1001 的衍生影响")
    _reply(_msg_ids["alert_b"],
           "🧠 **RCA 分析结果**：\n\n"
           "该告警为 checkoutservice 接口成功率下跌，"
           "与 P-1001（营销服务配置变更导致交易超时）直接相关 —— "
           "adservice 响应超时导致请求失败，成功率随之下降。\n\n"
           "🔗 已归并至 **P-1001**，无需单独处理。")

    _wait(3)

    # ── 🔧 止损方案 + 审批 ──
    _pause("🔧 Agent 为 P-1001 生成止损方案")
    _reply(_msg_ids["alert_a"],
           "🔧 **止损方案（P-1001）**\n\n"
           "根因为 adservice 配置变更导致异常，建议执行以下操作：\n"
           "1. **删除异常 Pod** `adservice-7d8f6b9c4-x2k9m`，触发 K8s 自动重建\n"
           "2. 新 Pod 启动后将加载上一个正常版本的配置\n"
           "3. 预计恢复时间：Pod 重建约 30s\n\n"
           "⚠️ 该操作需要值班人授权，正在发送审批请求...")

    _wait(2)

    _pause("🧾 发送审批卡片 + 加急通知值班人")
    _msg_ids["approval"] = _send_card(_build_approval_card(
        "P-1001", "营销服务配置变更导致交易超时",
        "adservice 15:32 配置变更（CHG-2026-0331-007）引入异常促销规则",
        "删除异常 Pod adservice-7d8f6b9c4-x2k9m，触发 K8s 自动重建（预计恢复 30s）"))

    _wait(5, "等待值班人审批...")

    # ── 🚨 告警 C 到达（审批等待中） ──
    _pause("🚨 告警C到达：用户中心服务超时 (Warning) ← 审批等待中")
    _msg_ids["alert_c"] = _send_card(_build_alert_card(
        "ServiceHighLatency", "userservice", "warning",
        "用户中心服务响应超时，P99 延迟从 150ms 升至 3200ms",
        alert_id="AG-20003"))

    _wait(2)

    _reply(_msg_ids["alert_c"], "🤖 收到告警，正在分析根因...")

    _wait(4, "Agent 正在分析告警C...")

    _pause("🔗 Agent 分析告警C → 初判归并到 P-1001")
    _reply(_msg_ids["alert_c"],
           "🧠 **RCA 分析结果（初判）**：\n\n"
           "userservice 与 checkoutservice 共享部分下游依赖（adservice），"
           "且时间窗口与 P-1001 高度重合。\n"
           "初步判断为 P-1001（营销服务配置变更导致交易超时）的衍生影响。\n\n"
           "🔗 已将该告警归并至 **P-1001**，统一处理。\n\n"
           "_⚠️ 置信度中等，将在止损完成后验证此归因是否正确。_")

    _wait(4, "继续等待审批...")

    # ── ✅ 审批通过 → 执行止损 ──
    _pause("✅ 值班人批准了审批")
    _reply(_msg_ids["alert_a"],
           "✅ **审批已通过**\n\n值班人已批准止损方案，正在执行...")

    _wait(2)

    _reply(_msg_ids["alert_a"],
           "🔧 **执行中**：正在删除 Pod `adservice-7d8f6b9c4-x2k9m`...")

    _wait(5, "K8s 正在重建 Pod...")

    _pause("✅ 止损执行完成，进入恢复观察")
    _reply(_msg_ids["alert_a"],
           "✅ **止损操作已完成**\n\n"
           "- 旧 Pod `adservice-7d8f6b9c4-x2k9m` 已删除\n"
           "- 新 Pod `adservice-7d8f6b9c4-m3n7p` 已启动 (Ready 1/1)\n"
           "- adservice 响应时间已降至 60ms\n\n"
           "⏳ P-1001 进入 **Recovering** 状态，开始恢复验证...\n"
           "将每 30s 检查一次关联告警状态（共 3 轮）")

    _wait(8, "恢复验证第 1 轮（模拟等待 30s）...")

    # ── 📉 恢复验证 ──
    _pause("📉 恢复验证：第 1 轮")
    _reply(_msg_ids["alert_a"],
           "📉 **恢复验证 — 第 1/3 轮**\n\n"
           "| 告警 | 服务 | 指标 | 状态 |\n"
           "|------|------|------|------|\n"
           "| A: ServiceHighErrorRate | checkoutservice | P99=1200ms (↓) | ⏳ 恢复中 |\n"
           "| B: ServiceSuccessRateDrop | checkoutservice | 成功率 92.1% (↑) | ⏳ 恢复中 |\n"
           "| C: ServiceHighLatency | userservice | P99=3100ms (→) | ❌ 未恢复 |\n\n"
           "A/B 指标在好转，C 暂无变化。继续观察...")

    _wait(8, "恢复验证第 2 轮（模拟等待 30s）...")

    _pause("📉 恢复验证：第 2 轮")
    _reply(_msg_ids["alert_a"],
           "📉 **恢复验证 — 第 2/3 轮**\n\n"
           "| 告警 | 服务 | 指标 | 状态 |\n"
           "|------|------|------|------|\n"
           "| A: ServiceHighErrorRate | checkoutservice | P99=180ms ✅ | ✅ **已恢复** |\n"
           "| B: ServiceSuccessRateDrop | checkoutservice | 成功率 99.8% ✅ | ✅ **已恢复** |\n"
           "| C: ServiceHighLatency | userservice | P99=3050ms ❌ | ❌ **未恢复** |\n\n"
           "🟢 A/B 已恢复正常\n"
           "🔴 C 仍然异常 — 止损方案对 C 无效\n\n"
           "⚡ **触发纠偏分析**：C 的归因可能有误...")

    _wait(5, "Agent 正在重新分析告警C...")

    # ── ⚡ 纠偏 ──
    _pause("⚡ 纠偏机制触发：重新分析告警C")
    _reply(_msg_ids["alert_a"],
           "⚡ **纠偏机制触发**\n\n"
           "营销服务已恢复正常，但 userservice（告警C）持续异常。\n\n"
           "**Agent 反思**：\n"
           "初判将告警C归并到 P-1001 是基于「共享下游依赖」的推理，"
           "但止损后 C 仍未恢复，说明该归因有误。userservice 的超时与营销服务配置变更无关。\n\n"
           "**重新分析告警C**：\n"
           "- Prometheus 显示 userservice CPU 使用率持续 > 95%\n"
           "- Loki 日志发现大量 `GC overhead limit exceeded` 警告\n"
           "- 根因：userservice JVM 内存不足导致频繁 Full GC → 服务超时\n\n"
           "📤 已将告警C从 P-1001 拆出\n"
           "📝 创建新问题 **P-1002**：「用户中心 JVM 内存不足导致 GC 风暴」")

    _wait(3)

    # ── 🎉 P-1001 消除 ──
    _pause("🎉 P-1001 消除，通知各关联告警话题")

    _reply(_msg_ids["alert_a"],
           "🎉 **P-1001 已消除**\n\n"
           "「营销服务配置变更导致交易超时」已彻底恢复。\n"
           "- 告警A: checkoutservice P99=180ms ✅\n"
           "- 告警B: checkoutservice 成功率 99.8% ✅\n\n"
           "处理耗时：约 12 分钟")

    _wait(1)

    _reply(_msg_ids["alert_b"],
           "🎉 **P-1001 已消除**\n\n交易服务接口成功率已恢复至 99.8%。")

    _wait(1)

    _reply(_msg_ids["alert_c"],
           "⚡ **纠偏通知**\n\n"
           "经验证，该告警（userservice 超时）与 P-1001（营销服务故障）**无关**。\n\n"
           "已拆分为独立问题 **P-1002**（用户中心 JVM 内存不足导致 GC 风暴）。\n"
           "正在为 P-1002 生成止损方案...")

    _wait(3)

    # ── 📋 汇总卡片 ──
    _pause("📋 发送问题处理汇总卡片")
    _send_card(_build_summary_card(
        "P-1001", "营销服务配置变更导致交易超时", "resolved",
        "**处理结果**：\n"
        "- ✅ 告警A (ServiceHighErrorRate / checkoutservice) — 已恢复\n"
        "- ✅ 告警B (ServiceSuccessRateDrop / checkoutservice) — 已恢复\n"
        "- ⚡ 告警C (ServiceHighLatency / userservice) — **纠偏**：与 P-1001 无关，已拆分至 P-1002\n\n"
        "---\n"
        "**后续跟踪**：\n"
        "🟡 **P-1002**（用户中心 JVM 内存不足导致 GC 风暴）— 正在处理中"))

    _wait(5)

    # ── 💬 @Agent 对话 ──
    _pause("💬 值班人在群里 @Agent 提问")
    question_id = _send_text(
        "👤 [模拟值班人提问]\n@值班Agent P-1002 现在情况怎么样了？有止损方案了吗？")

    _wait(3, "Agent 正在查询 P-1002 状态和相关数据...")

    _pause("🤖 Agent 回复值班人")
    _reply(question_id,
           "📋 **P-1002 当前状态**\n\n"
           "**问题**：用户中心 JVM 内存不足导致 GC 风暴\n"
           "**状态**：🟡 处理中（止损方案已生成，待审批）\n\n"
           "**最新数据**：\n"
           "- userservice CPU: 96.2% (仍然偏高)\n"
           "- JVM Heap 使用率: 94.8%\n"
           "- Full GC 频率: 每分钟 12 次\n\n"
           "**止损方案**：\n"
           "1. **紧急**：重启 userservice Pod（清理 GC 状态，预计恢复约 15s）\n"
           "2. **后续**：调整 JVM 堆内存参数 `-Xmx` 从 512m → 1024m\n\n"
           "是否需要我发送审批卡片？")

    # ── 结束 ──
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
    mode_desc = {
        "step": "单步模式（每步按回车继续）",
        "fast": f"快速模式（约 {estimated:.0f}s）",
        "standard": f"标准模式（约 {estimated:.0f}s / {estimated / 60:.1f} 分钟）",
    }
    # duration(Ns) 模式
    if MODE.startswith("duration"):
        desc = f"自定义时长模式（约 {estimated:.0f}s / {estimated / 60:.1f} 分钟）"
    else:
        desc = mode_desc.get(MODE, MODE)

    print(f"\n{'=' * 60}")
    print("🤖 值班虚拟员工 Mock 演示")
    print(f"{'=' * 60}")
    print(f"  模式: {desc}")
    print(f"  飞书群: {feishu_api._resolve_chat_id(None)}")
    print(f"  时间倍率: {_SCALE:.2f}x")
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
