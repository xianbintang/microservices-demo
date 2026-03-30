#!/usr/bin/env python3
"""
init_mock_data.py — 初始化 Problem 管理的 Mock 演示数据

将 6 条与 problem.html 前端 Mock 一致的问题数据，以 JSON 格式直接写入
data/problems.json，供 problem_manager.ProblemManager 加载使用。

为什么直接写 JSON 而非调用 manager API？
  - API 会自动生成 timestamp = time.time()，无法精确控制事件发生时间
  - 直接构造 JSON 可以完美还原"过去几天"的真实时间线

用法：
  python3 init_mock_data.py          # 生成 data/problems.json
  python3 init_mock_data.py --dry    # 仅打印 JSON 到控制台，不写文件
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# 常量：数据文件路径（与 problem_manager.py 保持一致）
# ---------------------------------------------------------------------------
DATA_DIR = Path(os.environ.get(
    "PROBLEM_DATA_DIR",
    Path(__file__).parent / "data",
))
DATA_FILE = DATA_DIR / "problems.json"


# ---------------------------------------------------------------------------
# 工具函数：将可读时间字符串转为 Unix 时间戳（浮点数）
# ---------------------------------------------------------------------------
def ts(time_str: str) -> float:
    """
    将 'YYYY-MM-DD HH:MM:SS' 格式的字符串转换为 Unix 时间戳。

    例如: ts("2026-03-28 12:06:05") → 1774933565.0
    如果解析失败，会打印警告并返回当前时间，避免脚本中断。
    """
    try:
        dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        return dt.timestamp()
    except ValueError as e:
        print(f"  ⚠️ 时间解析失败: '{time_str}' — {e}，使用当前时间替代")
        return time.time()


# ---------------------------------------------------------------------------
# 构造 ProblemEvent 字典（对应 problem_manager.ProblemEvent）
# ---------------------------------------------------------------------------
def evt(time_str: str, event_type: str, description: str,
        operator: str = "agent") -> dict:
    """
    快捷构造一条时间线事件。

    字段与 ProblemEvent dataclass 完全对齐：
      timestamp   — float，Unix 时间戳
      event_type  — 事件类型（created / rca / alert_merged / ...）
      description — 事件描述
      operator    — 操作人（agent / 具体用户名）
    """
    return {
        "timestamp": ts(time_str),
        "event_type": event_type,
        "description": description,
        "operator": operator,
    }


# ---------------------------------------------------------------------------
# 构造 Action 字典（对应 problem_manager.Action）
# ---------------------------------------------------------------------------
def act(action_id: str, description: str, status: str = "pending",
        approved_by: str = None, executed_at: str = None,
        result: str = None) -> dict:
    """
    快捷构造一条止损动作。

    字段与 Action dataclass 完全对齐：
      id          — 动作 ID（如 ACT-001）
      description — 动作描述
      status      — pending / approved / executing / completed / failed / rejected
      approved_by — 审批人（None 表示尚未审批）
      executed_at — 执行时间戳（None 表示尚未执行）
      result      — 执行结果描述
    """
    return {
        "id": action_id,
        "description": description,
        "status": status,
        "approved_by": approved_by,
        "executed_at": ts(executed_at) if executed_at else None,
        "result": result,
    }


# ---------------------------------------------------------------------------
# 6 条 Mock Problem 数据（与 problem.html MOCK_PROBLEMS 一一对应）
# ---------------------------------------------------------------------------
def build_mock_problems() -> list[dict]:
    """
    构造完整的 Problem 列表。

    每条 Problem 对应一个真实值班场景：
      P-1001  营销服务配置变更 → resolved（完整生命周期）
      P-1002  Redis 集群故障 → recovering（止损已执行，恢复验证中）
      P-1003  支付网关 TLS 证书 → pending（2 个 action 待审批）
      P-1004  数据库慢查询 → resolved（简单场景）
      P-1005  K8s 节点 NotReady → resolved（多告警归并）
      P-1006  Kafka 消费 lag → open（刚创建，分析中）
    """
    problems = []

    # ====================================================================
    # P-1001: 营销服务配置变更导致交易超时 — resolved（完整生命周期）
    # 场景：adservice 配置变更 → checkout 链路超时 → 回滚 + 删 Pod → 恢复
    # ====================================================================
    problems.append({
        "id": "P-1001",
        "title": "营销服务配置变更导致交易超时",
        "status": "resolved",
        "root_cause": (
            "线上发布服务未启动，MQ 存在问题，导致 TCE 实例进程批量退出报警。"
            "营销服务 adservice 的配置变更引发下游 checkout 链路延迟从 200ms 飙升至 8s，"
            "触发交易超时告警。"
        ),
        "alert_group_ids": ["AG-2001", "AG-2002", "AG-2003"],
        "message_ids": {},
        "actions": [
            act("ACT-001", "回滚 adservice 配置变更",
                status="completed", approved_by="张烨浩",
                executed_at="2026-03-28 12:09:15",
                result="配置已回滚至上一个稳定版本"),
            act("ACT-002", "删除 adservice 异常 Pod 触发重建",
                status="completed", approved_by="张烨浩",
                executed_at="2026-03-28 12:09:45",
                result="异常 Pod 已删除，新 Pod 启动正常"),
        ],
        "events": [
            evt("2026-03-28 12:06:05", "created",
                "收到告警「交易服务响应超时 P0」，自动创建问题 P-1001"),
            evt("2026-03-28 12:06:22", "root_cause_updated",
                "根因：营销服务 adservice 配置变更导致下游交易链路延迟飙升，"
                "Trace 显示 checkout→adservice 调用 P99 延迟从 200ms 升至 8.2s"),
            evt("2026-03-28 12:07:30", "alert_merged",
                "将告警「营销服务 Pod OOMKilled」(AG-2003) 归并至本问题"),
            evt("2026-03-28 12:08:15", "alert_merged",
                "将告警「交易服务成功率下跌」(AG-2002) 归并至本问题"),
            evt("2026-03-28 12:08:30", "action_added",
                "止损方案：回滚 adservice 配置变更 + 删除异常 Pod，已发送审批卡片"),
            evt("2026-03-28 12:08:30", "status_changed",
                "状态从 open 变更为 pending（有止损方案待审批）"),
            evt("2026-03-28 12:09:15", "approved",
                "止损动作「回滚 adservice 配置变更」已被 张烨浩 批准执行",
                operator="张烨浩"),
            evt("2026-03-28 12:09:15", "approved",
                "止损动作「删除 adservice 异常 Pod 触发重建」已被 张烨浩 批准执行",
                operator="张烨浩"),
            evt("2026-03-28 12:09:15", "status_changed",
                "所有动作已审批，进入恢复验证阶段"),
            evt("2026-03-28 12:09:45", "action_completed",
                "已完成配置回滚 + 异常 Pod 删除，进入恢复观察阶段"),
            evt("2026-03-28 12:12:00", "recovery_check",
                "第 5 次检查：AG-2001 ✅已恢复，AG-2002 ✅已恢复，AG-2003 ✅已恢复"),
            evt("2026-03-28 12:15:05", "status_changed",
                "所有关联告警已恢复，问题关闭。总恢复时长 10m9s"),
        ],
        "created_at": ts("2026-03-28 12:06:05"),
        "resolved_at": ts("2026-03-28 12:15:05"),
        "silenced_until": None,
        "taken_over_by": None,
        "linked_issues": [],
    })

    # ====================================================================
    # P-1002: Redis 集群主节点故障 — recovering（恢复验证中）
    # 场景：master-3 磁盘 I/O 错误 → Sentinel failover → 等待缓存预热
    # ====================================================================
    problems.append({
        "id": "P-1002",
        "title": "Redis 集群主节点故障导致缓存服务不可用",
        "status": "recovering",
        "root_cause": (
            "Redis 集群 master-3 节点发生磁盘 I/O 错误，触发 failover 但 "
            "sentinel 未能及时完成选主，导致缓存读写超时。"
        ),
        "alert_group_ids": ["AG-3001", "AG-3002"],
        "message_ids": {},
        "actions": [
            act("ACT-003", "手动触发 Redis Sentinel failover",
                status="completed", approved_by="刘伟",
                executed_at="2026-03-30 09:18:20",
                result="Sentinel failover 执行成功，master-2 已提升为新主节点"),
            act("ACT-004", "重启 master-3 节点并检查磁盘状态",
                status="executing", approved_by="刘伟",
                executed_at="2026-03-30 09:19:00"),
        ],
        "events": [
            evt("2026-03-30 09:15:05", "created",
                "收到告警「Redis 集群主节点不可达」，自动创建问题 P-1002"),
            evt("2026-03-30 09:15:28", "root_cause_updated",
                "根因：Redis master-3 节点磁盘 I/O 错误，"
                "Prometheus 指标显示 node_disk_io_time_seconds 异常飙升"),
            evt("2026-03-30 09:16:30", "alert_merged",
                "将告警「缓存命中率骤降至 20%」(AG-3002) 归并至本问题"),
            evt("2026-03-30 09:17:00", "action_added",
                "止损方案：手动触发 Sentinel failover + 重启故障节点"),
            evt("2026-03-30 09:17:00", "status_changed",
                "状态从 open 变更为 pending（有止损方案待审批）"),
            evt("2026-03-30 09:18:20", "approved",
                "止损动作「手动触发 Redis Sentinel failover」已被 刘伟 批准执行",
                operator="刘伟"),
            evt("2026-03-30 09:18:20", "approved",
                "止损动作「重启 master-3 节点并检查磁盘状态」已被 刘伟 批准执行",
                operator="刘伟"),
            evt("2026-03-30 09:18:20", "status_changed",
                "所有动作已审批，进入恢复验证阶段"),
            evt("2026-03-30 09:19:00", "action_completed",
                "Sentinel failover 执行成功，master-2 已提升为新主节点"),
            evt("2026-03-30 09:22:00", "recovery_check",
                "第 3 次检查：AG-3001 ⏳检查中，AG-3002 ⏳检查中，"
                "等待缓存预热完成"),
        ],
        "created_at": ts("2026-03-30 09:15:05"),
        "resolved_at": None,
        "silenced_until": None,
        "taken_over_by": None,
        "linked_issues": [],
    })

    # ====================================================================
    # P-1003: 支付网关 TLS 证书过期 — pending（2 个 action 待审批）
    # 场景：证书过期 → HTTPS 连接被拒 → 等待值班人审批更新证书
    # ====================================================================
    problems.append({
        "id": "P-1003",
        "title": "支付网关 TLS 证书过期导致支付失败",
        "status": "pending",
        "root_cause": (
            "支付网关 payment-gateway 的 TLS 证书于 2026-03-30 00:00 过期，"
            "未提前告警，导致所有 HTTPS 连接被拒绝。"
        ),
        "alert_group_ids": ["AG-4001"],
        "message_ids": {},
        "actions": [
            # 两个 action 都是 pending，模拟"等待值班人审批"的场景
            act("ACT-007", "更新 payment-gateway TLS 证书并重新部署",
                status="pending"),
            act("ACT-008", "重启 payment-gateway 全部 Pod",
                status="pending"),
        ],
        "events": [
            evt("2026-03-30 10:30:08", "created",
                "收到告警「支付服务 5xx 错误率 > 50%」，自动创建问题 P-1003"),
            evt("2026-03-30 10:30:45", "root_cause_updated",
                "根因：payment-gateway TLS 证书过期（过期时间 2026-03-30 00:00:00 UTC），"
                "Loki 日志显示大量 'certificate has expired' 错误"),
            evt("2026-03-30 10:31:00", "action_added",
                "止损方案：更新 TLS 证书 + 重启 payment-gateway Pod，"
                "已发送审批卡片，等待值班人确认"),
            evt("2026-03-30 10:31:00", "status_changed",
                "状态从 open 变更为 pending（有止损方案待审批）"),
        ],
        "created_at": ts("2026-03-30 10:30:08"),
        "resolved_at": None,
        "silenced_until": None,
        "taken_over_by": None,
        "linked_issues": [],
    })

    # ====================================================================
    # P-1004: 数据库慢查询 — resolved（简单场景：加索引解决）
    # 场景：orders 表缺索引 → P99 飙升 → Online DDL 加索引 → 恢复
    # ====================================================================
    problems.append({
        "id": "P-1004",
        "title": "数据库慢查询导致订单列表页加载超时",
        "status": "resolved",
        "root_cause": (
            "orderservice 的订单列表查询缺少索引，当数据量超过 100 万后，"
            "全表扫描导致 P99 延迟从 500ms 飙升至 12s。"
        ),
        "alert_group_ids": ["AG-5001"],
        "message_ids": {},
        "actions": [
            act("ACT-005", "添加 orders 表 user_id+created_at 复合索引",
                status="completed", approved_by="朱永泰",
                executed_at="2026-03-27 16:25:00",
                result="索引添加完成，P99 延迟降至 380ms"),
        ],
        "events": [
            evt("2026-03-27 16:20:05", "created",
                "收到告警「订单服务 P99 延迟 > 5s」"),
            evt("2026-03-27 16:20:30", "root_cause_updated",
                "根因：orders 表缺少 user_id+created_at 复合索引，"
                "Tempo 链路显示 DB 查询耗时 11.8s"),
            evt("2026-03-27 16:21:00", "action_added",
                "止损方案：在线添加复合索引（Online DDL）"),
            evt("2026-03-27 16:21:00", "status_changed",
                "状态从 open 变更为 pending（有止损方案待审批）"),
            evt("2026-03-27 16:25:00", "approved",
                "止损动作「添加 orders 表 user_id+created_at 复合索引」"
                "已被 朱永泰 批准执行",
                operator="朱永泰"),
            evt("2026-03-27 16:25:00", "status_changed",
                "所有动作已审批，进入恢复验证阶段"),
            evt("2026-03-27 16:28:00", "recovery_check",
                "AG-5001 ✅已恢复，P99 延迟降至 380ms"),
            evt("2026-03-27 16:30:00", "status_changed",
                "告警已恢复，问题关闭"),
        ],
        "created_at": ts("2026-03-27 16:20:05"),
        "resolved_at": ts("2026-03-27 16:30:00"),
        "silenced_until": None,
        "taken_over_by": None,
        "linked_issues": [],
    })

    # ====================================================================
    # P-1005: K8s 节点 NotReady — resolved（多告警归并场景）
    # 场景：worker-node-03 OOM → Pod 被驱逐 → drain + 重启 → 恢复
    # ====================================================================
    problems.append({
        "id": "P-1005",
        "title": "K8s 节点 NotReady 导致多服务 Pod 被驱逐",
        "status": "resolved",
        "root_cause": (
            "worker-node-03 内存耗尽（OOM），kubelet 上报 NotReady，"
            "该节点上的 12 个 Pod 被驱逐并触发重调度。"
        ),
        "alert_group_ids": ["AG-6001", "AG-6002", "AG-6003"],
        "message_ids": {},
        "actions": [
            act("ACT-006", "手动 drain worker-node-03 并重启",
                status="completed", approved_by="张烨浩",
                executed_at="2026-03-26 08:48:00",
                result="worker-node-03 已 drain 并重启，节点状态恢复 Ready"),
        ],
        "events": [
            evt("2026-03-26 08:45:05", "created",
                "收到告警「K8s 节点 NotReady」"),
            evt("2026-03-26 08:45:25", "root_cause_updated",
                "根因：worker-node-03 内存耗尽，Prometheus 显示 "
                "node_memory_MemAvailable_bytes = 0"),
            evt("2026-03-26 08:46:00", "alert_merged",
                "归并「多服务 Pod 重启次数异常」(AG-6002)"),
            evt("2026-03-26 08:47:00", "alert_merged",
                "归并「frontend 服务可用性下降」(AG-6003)"),
            evt("2026-03-26 08:47:30", "action_added",
                "止损方案：手动 drain worker-node-03 并重启"),
            evt("2026-03-26 08:47:30", "status_changed",
                "状态从 open 变更为 pending（有止损方案待审批）"),
            evt("2026-03-26 08:48:00", "approved",
                "止损动作「手动 drain worker-node-03 并重启」已被 张烨浩 批准执行",
                operator="张烨浩"),
            evt("2026-03-26 08:48:00", "status_changed",
                "所有动作已审批，进入恢复验证阶段"),
            evt("2026-03-26 08:48:00", "action_completed",
                "drain + 重启 worker-node-03 完成"),
            evt("2026-03-26 08:55:00", "status_changed",
                "所有告警恢复，问题关闭。恢复时长 10m"),
        ],
        "created_at": ts("2026-03-26 08:45:05"),
        "resolved_at": ts("2026-03-26 08:55:00"),
        "silenced_until": None,
        "taken_over_by": None,
        "linked_issues": [],
    })

    # ====================================================================
    # P-1006: Kafka 消费 lag — open（刚创建，RCA 分析中）
    # 场景：consumer-group-order lag 飙升 → Agent 正在分析根因
    # ====================================================================
    problems.append({
        "id": "P-1006",
        "title": "Kafka 消费组 lag 持续增长导致消息积压",
        "status": "open",
        "root_cause": (
            "consumer-group-order 消费能力不足，Kafka topic order-events 的 "
            "lag 从 0 飙升至 50 万+，疑似消费者线程死锁。"
        ),
        "alert_group_ids": ["AG-7001"],
        "message_ids": {},
        "actions": [],
        "events": [
            evt("2026-03-30 11:05:05", "created",
                "收到告警「Kafka 消费 lag > 10 万」，自动创建问题 P-1006"),
            evt("2026-03-30 11:05:30", "root_cause_updated",
                "正在分析根因，查询 Prometheus 消费者指标和 Loki 消费者日志..."),
        ],
        "created_at": ts("2026-03-30 11:05:05"),
        "resolved_at": None,
        "silenced_until": None,
        "taken_over_by": None,
        "linked_issues": [],
    })

    return problems


# ---------------------------------------------------------------------------
# 主逻辑：构造完整的 JSON 并写入文件
# ---------------------------------------------------------------------------
def main():
    """
    构造 mock 数据并写入 data/problems.json。

    JSON 顶层结构与 ProblemManager._save() 保持一致：
      {
        "id_counter": 1006,        # 当前最大 ID 数字部分
        "problems": [ ... ]        # Problem 列表
      }

    --dry 参数：仅打印到控制台，不写入文件（调试用）
    """
    dry_run = "--dry" in sys.argv

    print("=" * 60)
    print("🔧 Problem Mock 数据初始化工具")
    print("=" * 60)

    # 构造 6 条 mock 数据
    problems = build_mock_problems()

    # id_counter 设为 1006，对应最后一个 Problem ID P-1006
    # ProblemManager._next_id() 会先 +1 再生成，所以下一次创建将得到 P-1007
    data = {
        "id_counter": 1006,
        "problems": problems,
    }

    json_str = json.dumps(data, ensure_ascii=False, indent=2)

    if dry_run:
        # 仅打印到控制台，不写文件
        print(f"\n📋 生成了 {len(problems)} 条 Problem（dry-run 模式，不写文件）\n")
        print(json_str)
        return

    # 确保目录存在
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 写入 JSON 文件
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        f.write(json_str)

    print(f"\n✅ 已生成 {len(problems)} 条 Mock Problem 数据")
    print(f"   文件路径: {DATA_FILE}")
    print(f"   id_counter: {data['id_counter']}")
    print()

    # 打印摘要
    status_counts = {}
    for p in problems:
        s = p["status"]
        status_counts[s] = status_counts.get(s, 0) + 1

    print("📊 数据摘要:")
    for pid_data in problems:
        action_count = len(pid_data["actions"])
        event_count = len(pid_data["events"])
        print(f"   {pid_data['id']}  [{pid_data['status']:^12}]  "
              f"{pid_data['title'][:30]}...  "
              f"({action_count} 个动作, {event_count} 个事件)")
    print()
    print(f"   状态分布: {status_counts}")
    print()
    print(f"💡 提示: ProblemManager 加载此文件后，下一个新 Problem 的 ID 将是 P-1007")
    print("=" * 60)


if __name__ == "__main__":
    main()
