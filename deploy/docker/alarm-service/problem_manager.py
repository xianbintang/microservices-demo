"""
problem_manager.py — Problem 管理模块

提供 Problem（问题）的 CRUD、状态机、告警归并/拆分、时间线事件记录，
以及 JSON 文件持久化。

数据存储: 内存 dict + data/problems.json 文件
线程安全: 通过 threading.Lock 保证并发写入安全
"""

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger("problem-manager")

# 持久化文件路径，默认在 data/problems.json
DATA_DIR = Path(os.environ.get("PROBLEM_DATA_DIR", Path(__file__).parent / "data"))
DATA_FILE = DATA_DIR / "problems.json"

# Problem 状态常量
STATUS_OPEN = "open"
STATUS_PENDING = "pending"
STATUS_RECOVERING = "recovering"
STATUS_RESOLVED = "resolved"
STATUS_TAKEOVER = "takeover"
STATUS_SILENCED = "silenced"

ALL_STATUSES = {STATUS_OPEN, STATUS_PENDING, STATUS_RECOVERING,
                STATUS_RESOLVED, STATUS_TAKEOVER, STATUS_SILENCED}

# Action 状态常量
ACTION_PENDING = "pending"
ACTION_APPROVED = "approved"
ACTION_EXECUTING = "executing"
ACTION_COMPLETED = "completed"
ACTION_FAILED = "failed"
ACTION_REJECTED = "rejected"


@dataclass
class ProblemEvent:
    """问题处理时间线事件。"""
    timestamp: float
    event_type: str
    description: str
    operator: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ProblemEvent":
        return cls(**data)


@dataclass
class Action:
    """止损动作。"""
    id: str
    description: str
    status: str = ACTION_PENDING
    approved_by: Optional[str] = None
    executed_at: Optional[float] = None
    result: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Action":
        return cls(**data)


@dataclass
class Problem:
    """问题实体，包含告警关联、止损动作、时间线事件等。"""
    id: str
    title: str
    status: str = STATUS_OPEN
    root_cause: str = ""
    alert_group_ids: list = field(default_factory=list)
    message_ids: dict = field(default_factory=dict)
    actions: list = field(default_factory=list)
    events: list = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    resolved_at: Optional[float] = None
    silenced_until: Optional[float] = None
    taken_over_by: Optional[str] = None
    linked_issues: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "root_cause": self.root_cause,
            "alert_group_ids": self.alert_group_ids,
            "message_ids": self.message_ids,
            "actions": [a.to_dict() if isinstance(a, Action) else a for a in self.actions],
            "events": [e.to_dict() if isinstance(e, ProblemEvent) else e for e in self.events],
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "silenced_until": self.silenced_until,
            "taken_over_by": self.taken_over_by,
            "linked_issues": self.linked_issues,
        }
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "Problem":
        actions = [Action.from_dict(a) if isinstance(a, dict) else a for a in data.get("actions", [])]
        events = [ProblemEvent.from_dict(e) if isinstance(e, dict) else e for e in data.get("events", [])]
        return cls(
            id=data["id"],
            title=data["title"],
            status=data.get("status", STATUS_OPEN),
            root_cause=data.get("root_cause", ""),
            alert_group_ids=data.get("alert_group_ids", []),
            message_ids=data.get("message_ids", {}),
            actions=actions,
            events=events,
            created_at=data.get("created_at", time.time()),
            resolved_at=data.get("resolved_at"),
            silenced_until=data.get("silenced_until"),
            taken_over_by=data.get("taken_over_by"),
            linked_issues=data.get("linked_issues", []),
        )


class ProblemManager:
    """
    Problem 管理器：CRUD + 状态机 + JSON 持久化。

    所有写操作自动持久化到 data/problems.json。
    通过 threading.Lock 保证线程安全。
    """

    def __init__(self, data_file: Path = DATA_FILE):
        self._data_file = data_file
        self._problems: dict[str, Problem] = {}
        self._lock = threading.Lock()
        self._id_counter = 1000
        self._load()

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def _load(self):
        """从 JSON 文件恢复数据，文件不存在则初始化空数据。"""
        if self._data_file.exists():
            try:
                with open(self._data_file, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                for item in raw.get("problems", []):
                    p = Problem.from_dict(item)
                    self._problems[p.id] = p
                self._id_counter = raw.get("id_counter", 1000)
                logger.info("从 %s 恢复了 %d 个问题, id_counter=%d",
                            self._data_file, len(self._problems), self._id_counter)
            except Exception as e:
                logger.error("加载 %s 失败: %s, 将使用空数据", self._data_file, e)
                self._problems = {}
        else:
            logger.info("数据文件 %s 不存在，初始化空数据", self._data_file)

    def _save(self):
        """将当前数据序列化到 JSON 文件。调用方需已持有 _lock。"""
        try:
            self._data_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "id_counter": self._id_counter,
                "problems": [p.to_dict() for p in self._problems.values()],
            }
            with open(self._data_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("持久化到 %s 失败: %s", self._data_file, e, exc_info=True)

    # ------------------------------------------------------------------
    # ID 生成
    # ------------------------------------------------------------------

    def _next_id(self) -> str:
        self._id_counter += 1
        return f"P-{self._id_counter}"

    def _next_action_id(self) -> str:
        return f"ACT-{uuid.uuid4().hex[:8].upper()}"

    # ------------------------------------------------------------------
    # 读操作
    # ------------------------------------------------------------------

    def get_problem(self, problem_id: str) -> Optional[Problem]:
        """获取指定问题。"""
        return self._problems.get(problem_id)

    def get_all_problems(self) -> list[Problem]:
        """获取所有问题，按创建时间倒序。"""
        return sorted(
            self._problems.values(),
            key=lambda p: (0 if p.status != "resolved" else 1, -p.created_at),
        )

    def get_problems_by_status(self, status: str) -> list[Problem]:
        """按状态筛选问题。"""
        return [p for p in self.get_all_problems() if p.status == status]

    def get_open_problems(self) -> list[Problem]:
        """获取所有未解决的问题（非 resolved）。"""
        return [p for p in self.get_all_problems() if p.status != STATUS_RESOLVED]

    # ------------------------------------------------------------------
    # 写操作
    # ------------------------------------------------------------------

    def create_problem(self, title: str, root_cause: str = "",
                       alert_group_id: str = "", message_id: str = "") -> Problem:
        """创建新问题，自动分配 P-XXXX ID，记录创建事件。"""
        with self._lock:
            pid = self._next_id()
            now = time.time()

            alert_group_ids = [alert_group_id] if alert_group_id else []
            message_ids = {alert_group_id: message_id} if alert_group_id and message_id else {}

            event = ProblemEvent(
                timestamp=now,
                event_type="created",
                description=f"问题创建：{title}",
                operator="agent",
            )

            problem = Problem(
                id=pid,
                title=title,
                status=STATUS_OPEN,
                root_cause=root_cause,
                alert_group_ids=alert_group_ids,
                message_ids=message_ids,
                actions=[],
                events=[event],
                created_at=now,
            )

            self._problems[pid] = problem
            self._save()
            logger.info("创建问题 %s: %s", pid, title)
            return problem

    def merge_alert(self, problem_id: str, alert_group_id: str, message_id: str = ""):
        """将告警归并到已有问题。"""
        with self._lock:
            p = self._problems.get(problem_id)
            if not p:
                logger.warning("归并告警失败：问题 %s 不存在", problem_id)
                return

            if alert_group_id not in p.alert_group_ids:
                p.alert_group_ids.append(alert_group_id)
            if message_id:
                p.message_ids[alert_group_id] = message_id

            p.events.append(ProblemEvent(
                timestamp=time.time(),
                event_type="alert_merged",
                description=f"告警 {alert_group_id} 已归并至本问题",
                operator="agent",
            ))
            self._save()
            logger.info("告警 %s 已归并到问题 %s", alert_group_id, problem_id)

    def update_status(self, problem_id: str, status: str, operator: str = "agent"):
        """更新问题状态。"""
        if status not in ALL_STATUSES:
            logger.error("无效状态: %s", status)
            return

        with self._lock:
            p = self._problems.get(problem_id)
            if not p:
                logger.warning("更新状态失败：问题 %s 不存在", problem_id)
                return

            old_status = p.status
            p.status = status

            if status == STATUS_RESOLVED and p.resolved_at is None:
                p.resolved_at = time.time()

            p.events.append(ProblemEvent(
                timestamp=time.time(),
                event_type="status_changed",
                description=f"状态从 {old_status} 变更为 {status}",
                operator=operator,
            ))
            self._save()
            logger.info("问题 %s 状态: %s → %s", problem_id, old_status, status)

    def update_root_cause(self, problem_id: str, new_root_cause: str, operator: str = "agent"):
        """纠偏：修改根因描述。"""
        with self._lock:
            p = self._problems.get(problem_id)
            if not p:
                return

            old_cause = p.root_cause
            p.root_cause = new_root_cause
            p.events.append(ProblemEvent(
                timestamp=time.time(),
                event_type="root_cause_updated",
                description=f"根因更新：{new_root_cause}",
                operator=operator,
            ))
            self._save()
            logger.info("问题 %s 根因更新: %s → %s", problem_id, old_cause[:50], new_root_cause[:50])

    def add_action(self, problem_id: str, description: str, action_id: str = "") -> Optional[Action]:
        """添加止损动作。"""
        with self._lock:
            p = self._problems.get(problem_id)
            if not p:
                return None

            aid = action_id or self._next_action_id()
            action = Action(id=aid, description=description)
            p.actions.append(action)
            p.events.append(ProblemEvent(
                timestamp=time.time(),
                event_type="action_added",
                description=f"新增止损动作: {description}",
                operator="agent",
            ))

            # 如果有待审批的 action，问题状态应进入 pending
            if p.status == STATUS_OPEN:
                p.status = STATUS_PENDING
                p.events.append(ProblemEvent(
                    timestamp=time.time(),
                    event_type="status_changed",
                    description=f"状态从 open 变更为 pending（有止损方案待审批）",
                    operator="agent",
                ))

            self._save()
            logger.info("问题 %s 新增动作 %s: %s", problem_id, aid, description)
            return action

    def approve_action(self, problem_id: str, action_id: str, operator: str = "user") -> Optional[Action]:
        """审批通过止损动作，状态流转到 executing → 进入 recovering。"""
        with self._lock:
            p = self._problems.get(problem_id)
            if not p:
                logger.warning("审批失败：问题 %s 不存在", problem_id)
                return None

            action = None
            for a in p.actions:
                act = a if isinstance(a, Action) else Action.from_dict(a)
                if act.id == action_id:
                    action = act
                    break

            if not action:
                logger.warning("审批失败：动作 %s 不存在", action_id)
                return None

            if action.status != ACTION_PENDING:
                logger.warning("审批失败：动作 %s 状态为 %s，非 pending", action_id, action.status)
                return None

            action.status = ACTION_EXECUTING
            action.approved_by = operator
            action.executed_at = time.time()

            # 更新 actions 列表中的引用
            for i, a in enumerate(p.actions):
                aid = a.id if isinstance(a, Action) else a.get("id")
                if aid == action_id:
                    p.actions[i] = action
                    break

            p.events.append(ProblemEvent(
                timestamp=time.time(),
                event_type="approved",
                description=f"止损动作「{action.description}」已被 {operator} 批准执行",
                operator=operator,
            ))

            # 检查是否所有 pending action 都已审批，如果是则进入 recovering
            all_handled = all(
                (a.status if isinstance(a, Action) else a.get("status")) != ACTION_PENDING
                for a in p.actions
            )
            if all_handled and p.status == STATUS_PENDING:
                p.status = STATUS_RECOVERING
                p.events.append(ProblemEvent(
                    timestamp=time.time(),
                    event_type="status_changed",
                    description="所有动作已审批，进入恢复验证阶段",
                    operator="agent",
                ))

            self._save()
            logger.info("问题 %s 动作 %s 已审批通过 by %s", problem_id, action_id, operator)
            return action

    def reject_action(self, problem_id: str, action_id: str, operator: str = "user") -> Optional[Action]:
        """拒绝/取消止损动作。"""
        with self._lock:
            p = self._problems.get(problem_id)
            if not p:
                return None

            action = None
            for a in p.actions:
                act = a if isinstance(a, Action) else Action.from_dict(a)
                if act.id == action_id:
                    action = act
                    break

            if not action or action.status != ACTION_PENDING:
                return None

            action.status = ACTION_REJECTED

            for i, a in enumerate(p.actions):
                aid = a.id if isinstance(a, Action) else a.get("id")
                if aid == action_id:
                    p.actions[i] = action
                    break

            p.events.append(ProblemEvent(
                timestamp=time.time(),
                event_type="rejected",
                description=f"止损动作「{action.description}」已被 {operator} 取消",
                operator=operator,
            ))

            # 如果所有 action 都被取消，回到 open
            all_handled = all(
                (a.status if isinstance(a, Action) else a.get("status")) != ACTION_PENDING
                for a in p.actions
            )
            any_approved = any(
                (a.status if isinstance(a, Action) else a.get("status")) in (ACTION_EXECUTING, ACTION_COMPLETED, ACTION_APPROVED)
                for a in p.actions
            )
            if all_handled and not any_approved and p.status == STATUS_PENDING:
                p.status = STATUS_OPEN
                p.events.append(ProblemEvent(
                    timestamp=time.time(),
                    event_type="status_changed",
                    description="所有动作已取消，退回未解决状态",
                    operator="agent",
                ))

            self._save()
            logger.info("问题 %s 动作 %s 已取消 by %s", problem_id, action_id, operator)
            return action

    def add_event(self, problem_id: str, event: ProblemEvent):
        """添加时间线事件。"""
        with self._lock:
            p = self._problems.get(problem_id)
            if not p:
                return
            p.events.append(event)
            self._save()

    def takeover_problem(self, problem_id: str, operator: str):
        """人工接管问题，Agent 暂停自动操作。"""
        with self._lock:
            p = self._problems.get(problem_id)
            if not p:
                return

            p.status = STATUS_TAKEOVER
            p.taken_over_by = operator
            p.events.append(ProblemEvent(
                timestamp=time.time(),
                event_type="takeover",
                description=f"问题已被 {operator} 接管，Agent 暂停自动操作",
                operator=operator,
            ))
            self._save()
            logger.info("问题 %s 已被 %s 接管", problem_id, operator)

    def silence_problem(self, problem_id: str, duration_seconds: float, operator: str = "user"):
        """静默问题一段时间。"""
        with self._lock:
            p = self._problems.get(problem_id)
            if not p:
                return

            p.status = STATUS_SILENCED
            p.silenced_until = time.time() + duration_seconds
            p.events.append(ProblemEvent(
                timestamp=time.time(),
                event_type="silenced",
                description=f"问题已静默 {int(duration_seconds / 3600)}h by {operator}",
                operator=operator,
            ))
            self._save()
            logger.info("问题 %s 已静默 %.0f 秒 by %s", problem_id, duration_seconds, operator)

    def link_issue(self, problem_id: str, issue_url: str):
        """关联外部 Issue。"""
        with self._lock:
            p = self._problems.get(problem_id)
            if not p:
                return
            if issue_url not in p.linked_issues:
                p.linked_issues.append(issue_url)
            p.events.append(ProblemEvent(
                timestamp=time.time(),
                event_type="issue_linked",
                description=f"关联外部 Issue: {issue_url}",
                operator="user",
            ))
            self._save()

    def resolve_problem(self, problem_id: str, operator: str = "agent"):
        """解决问题。"""
        self.update_status(problem_id, STATUS_RESOLVED, operator)


# 全局单例
_manager: Optional[ProblemManager] = None
_manager_lock = threading.Lock()


def get_manager() -> ProblemManager:
    """获取全局 ProblemManager 单例。"""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = ProblemManager()
    return _manager
