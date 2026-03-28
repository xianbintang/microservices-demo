#!/usr/bin/env python3
"""
Grafana OnCall AlertGroup 操作库（oncall_api.py）

本模块是 grafana-oncall-alertgroup Skill 的核心执行引擎，封装了以下能力：
  1. 查看 AlertGroup 列表（支持按状态筛选）
  2. 查看 AlertGroup 详情
  3. ACK（确认）AlertGroup
  4. Resolve（解决）AlertGroup
  5. Silence（静默）AlertGroup（支持自定义静默时长）
  6. 取消 ACK（Unacknowledge）
  7. 取消静默（Unsilence）

认证说明：
  - 通过 Grafana Plugin Proxy 间接调用 OnCall API
  - 需要在项目 .env 文件中配置 GRAFANA_URL、GRAFANA_USER、GRAFANA_PASSWORD
  - .env 文件从 Skill 目录逐级向上搜索

使用方式：
  直接在终端用 python3 oncall_api.py <command> [args] 调用
  或在 Python 代码中 import 使用

依赖：仅使用 Python 标准库，无需安装第三方包
"""

import base64
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path


# ============================================================
# 配置与路径
# ============================================================

_SKILL_DIR = Path(__file__).resolve().parent

# 默认配置（可被 .env 覆盖）
_DEFAULTS = {
    "GRAFANA_URL": "http://47.83.217.162:3000/",
    "GRAFANA_USER": "admin",
    "GRAFANA_PASSWORD": "admin",
}


def _find_env_file() -> Path:
    """
    从 Skill 目录开始，逐级向上搜索 .env 文件，直到文件系统根目录。
    """
    current = _SKILL_DIR
    while True:
        candidate = current / ".env"
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            return None
        current = parent


def _load_env() -> dict:
    """从 .env 文件读取配置，返回 key-value 字典。"""
    env_path = _find_env_file()
    if not env_path:
        return {}
    result = {}
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                result[key] = value
    return result


def _get_config(key: str) -> str:
    """获取配置项：优先系统环境变量，其次 .env 文件，最后默认值。"""
    val = os.environ.get(key)
    if val:
        return val
    env = _load_env()
    return env.get(key, _DEFAULTS.get(key, ""))


# ============================================================
# OnCall API 核心请求函数
# ============================================================

def _oncall_request(method: str, path: str, body: dict = None, timeout: int = 15) -> dict:
    """
    通过 Grafana Plugin Proxy 调用 OnCall API。

    参数：
        method: HTTP 方法（GET / POST / DELETE 等）
        path: OnCall API 路径，例如 "alertgroups/" 或 "alertgroups/XXXX/acknowledge/"
        body: 请求体（可选）
        timeout: 超时时间（秒）

    返回：
        API 响应的 JSON 解析结果

    异常：
        urllib.error.HTTPError: HTTP 请求错误（包含状态码和响应体）
        Exception: 其他网络/解析异常
    """
    grafana_url = _get_config("GRAFANA_URL")
    grafana_user = _get_config("GRAFANA_USER")
    grafana_password = _get_config("GRAFANA_PASSWORD")

    url = f"{grafana_url}/api/plugins/grafana-oncall-app/resources/{path}"
    credentials = base64.b64encode(f"{grafana_user}:{grafana_password}".encode()).decode()
    headers = {
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode() if body else None

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_body = resp.read().decode("utf-8")
            return json.loads(resp_body) if resp_body.strip() else {}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        raise RuntimeError(
            f"OnCall API 调用失败: method={method}, path={path}, "
            f"status={e.code}, response={error_body[:500]}"
        ) from e
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"OnCall API 连接失败: method={method}, path={path}, error={e.reason}"
        ) from e


# ============================================================
# 辅助函数
# ============================================================

def _format_delay(seconds: int) -> str:
    """将秒数转换为人类可读的时间文本。"""
    if seconds >= 86400:
        return f"{seconds // 86400}天"
    if seconds >= 3600:
        return f"{seconds // 3600}小时"
    return f"{seconds // 60}分钟"


def _parse_delay(delay_str: str) -> int:
    """
    解析静默时长字符串为秒数。
    支持格式：纯数字（秒）、30m（分钟）、1h（小时）、1d（天）。
    """
    delay_str = delay_str.strip().lower()
    if delay_str.endswith("d"):
        return int(delay_str[:-1]) * 86400
    if delay_str.endswith("h"):
        return int(delay_str[:-1]) * 3600
    if delay_str.endswith("m"):
        return int(delay_str[:-1]) * 60
    return int(delay_str)


_STATUS_MAP = {0: "new (新建)", 1: "acknowledged (已确认)", 2: "resolved (已解决)", 3: "silenced (已静默)"}


def _format_alert_group_summary(ag: dict) -> str:
    """将单个 AlertGroup 格式化为可读摘要。"""
    ag_pk = ag.get("pk", "?")
    org_num = ag.get("inside_organization_number", "")
    render = ag.get("render_for_web", {})
    title = render.get("title", "无标题")
    raw_status = ag.get("status", "?")
    status_text = _STATUS_MAP.get(raw_status, str(raw_status))
    started_at = ag.get("started_at", "")
    alerts_count = ag.get("alerts_count", 0)
    channel = ag.get("alert_receive_channel", {})
    integration_name = channel.get("verbal_name", "")
    acknowledged = ag.get("acknowledged", False)
    ack_user = ag.get("acknowledged_by_user")
    resolved = ag.get("resolved", False)
    resolve_user = ag.get("resolved_by_user")
    silenced = ag.get("silenced", False)
    silenced_until = ag.get("silenced_until", "")

    lines = [
        f"  PK:          {ag_pk}",
    ]
    if org_num:
        lines.append(f"  编号:        #{org_num}")
    lines += [
        f"  标题:        {title}",
        f"  状态:        {status_text}",
        f"  告警数量:    {alerts_count}",
        f"  创建时间:    {started_at}",
    ]
    if integration_name:
        lines.append(f"  集成:        {integration_name}")
    if acknowledged and ack_user:
        lines.append(f"  ACK 操作人:  {ack_user.get('username', '?')}")
    if resolved and resolve_user:
        lines.append(f"  解决操作人:  {resolve_user.get('username', '?')}")
    if ag.get("resolved_at"):
        lines.append(f"  解决时间:    {ag['resolved_at']}")
    if silenced and silenced_until:
        lines.append(f"  静默到:      {silenced_until}")

    web_link = ag.get("permalinks", {}).get("web", "")
    if web_link:
        lines.append(f"  Web 链接:    {web_link}")

    return "\n".join(lines)


def _format_alert_group_detail(ag: dict) -> str:
    """将 AlertGroup 完整详情格式化为可读文本。"""
    lines = [_format_alert_group_summary(ag)]

    render = ag.get("render_for_web", {})
    message = render.get("message", "")
    if message:
        lines.append(f"\n  告警详情（HTML）:\n    {message[:800]}")

    alerts = ag.get("alerts", [])
    if alerts:
        lines.append(f"\n  包含的告警 ({len(alerts)} 条):")
        for i, alert in enumerate(alerts[:10], 1):
            alert_id = alert.get("id", alert.get("pk", "?"))
            payload = alert.get("payload", {})
            alert_title = payload.get("title", payload.get("alertname", "无标题"))
            alert_created = alert.get("created_at", "")
            lines.append(f"    [{i}] ID={alert_id}, 标题={alert_title}, 创建={alert_created}")
        if len(alerts) > 10:
            lines.append(f"    ... 还有 {len(alerts) - 10} 条告警未显示")

    labels = ag.get("labels", [])
    if labels:
        lines.append(f"\n  标签:")
        for label in labels:
            if isinstance(label, dict):
                lines.append(f"    {label.get('key', '?')}: {label.get('value', '?')}")
            else:
                lines.append(f"    {label}")

    return "\n".join(lines)


# ============================================================
# 公开 API 函数
# ============================================================

def _resolve_alert_group_id(id_or_number: str) -> str:
    """
    将用户输入的 ID 解析为 OnCall 的 pk。
    如果输入看起来像编号（纯数字），则通过列表查找对应 pk；
    如果输入包含字母（看起来像 pk），直接返回。
    """
    if not id_or_number.isdigit():
        return id_or_number

    number = int(id_or_number)
    result = _oncall_request("GET", "alertgroups/?perpage=50")
    for ag in result.get("results", []):
        if ag.get("inside_organization_number") == number:
            return ag["pk"]

    raise RuntimeError(
        f"找不到编号为 #{number} 的 AlertGroup。"
        f"请使用 'list' 命令查看现有 AlertGroup。"
    )


def list_alert_groups(status: str = None, limit: int = 25) -> dict:
    """
    列出 AlertGroup。

    参数：
        status: 按状态筛选（new / acknowledged / resolved / silenced），None 表示全部
        limit: 返回数量上限

    返回：
        OnCall API 响应（包含 results 数组）
    """
    path = f"alertgroups/?perpage={limit}"
    if status:
        path += f"&status={status}"
    return _oncall_request("GET", path)


def get_alert_group(alert_group_id: str) -> dict:
    """
    获取单个 AlertGroup 的完整详情。

    参数：
        alert_group_id: AlertGroup 的 ID

    返回：
        AlertGroup 详情字典
    """
    return _oncall_request("GET", f"alertgroups/{alert_group_id}/")


def acknowledge(alert_group_id: str) -> dict:
    """
    ACK（确认）一个 AlertGroup。

    参数：
        alert_group_id: AlertGroup 的 ID

    返回：
        API 响应
    """
    return _oncall_request("POST", f"alertgroups/{alert_group_id}/acknowledge/")


def unacknowledge(alert_group_id: str) -> dict:
    """
    取消 ACK 一个 AlertGroup。

    参数：
        alert_group_id: AlertGroup 的 ID

    返回：
        API 响应
    """
    return _oncall_request("POST", f"alertgroups/{alert_group_id}/unacknowledge/")


def resolve(alert_group_id: str) -> dict:
    """
    Resolve（解决）一个 AlertGroup。

    参数：
        alert_group_id: AlertGroup 的 ID

    返回：
        API 响应
    """
    return _oncall_request("POST", f"alertgroups/{alert_group_id}/resolve/")


def unresolve(alert_group_id: str) -> dict:
    """
    取消 Resolve 一个 AlertGroup（重新打开）。

    参数：
        alert_group_id: AlertGroup 的 ID

    返回：
        API 响应
    """
    return _oncall_request("POST", f"alertgroups/{alert_group_id}/unresolve/")


def silence(alert_group_id: str, delay: int = 1800) -> dict:
    """
    Silence（静默）一个 AlertGroup。

    参数：
        alert_group_id: AlertGroup 的 ID
        delay: 静默时长（秒），默认 1800（30 分钟）

    返回：
        API 响应
    """
    return _oncall_request("POST", f"alertgroups/{alert_group_id}/silence/", {"delay": delay})


def unsilence(alert_group_id: str) -> dict:
    """
    取消静默一个 AlertGroup。

    参数：
        alert_group_id: AlertGroup 的 ID

    返回：
        API 响应
    """
    return _oncall_request("POST", f"alertgroups/{alert_group_id}/unsilence/")


def add_resolution_note(alert_group_id: str, text: str) -> dict:
    """
    为 AlertGroup 添加一条 Resolution Note。

    参数：
        alert_group_id: AlertGroup 的 pk
        text: note 内容

    返回：
        创建的 note 详情（包含 id, author, created_at, text 等）
    """
    return _oncall_request("POST", "resolution_notes/", {
        "alert_group": alert_group_id,
        "text": text,
    })


def list_resolution_notes(alert_group_id: str) -> list:
    """
    列出 AlertGroup 的所有 Resolution Note。

    参数：
        alert_group_id: AlertGroup 的 pk

    返回：
        note 列表
    """
    return _oncall_request("GET", f"resolution_notes/?alert_group_id={alert_group_id}")


# ============================================================
# CLI 入口
# ============================================================

_COMMANDS = {
    "list":          ("list [status] [limit]", "列出 AlertGroup，可选按状态筛选"),
    "get":           ("get <alert_group_id>", "查看 AlertGroup 详情"),
    "ack":           ("ack <alert_group_id>", "ACK（确认）AlertGroup"),
    "unack":         ("unack <alert_group_id>", "取消 ACK"),
    "resolve":       ("resolve <alert_group_id>", "Resolve（解决）AlertGroup"),
    "unresolve":     ("unresolve <alert_group_id>", "取消 Resolve（重新打开）"),
    "silence":       ("silence <alert_group_id> [delay]", "Silence（静默）AlertGroup"),
    "unsilence":     ("unsilence <alert_group_id>", "取消静默"),
    "note":          ("note <alert_group_id> <text>", "添加 Resolution Note"),
    "notes":         ("notes <alert_group_id>", "查看 Resolution Notes"),
}


def _print_usage():
    """打印 CLI 使用帮助。"""
    print("Grafana OnCall AlertGroup 操作工具")
    print()
    print("用法: python3 oncall_api.py <command> [args...]")
    print()
    print("可用命令:")
    for cmd, (usage, desc) in _COMMANDS.items():
        print(f"  {usage:<45} {desc}")
    print()
    print("静默时长格式: 纯数字（秒）、30m（分钟）、1h（小时）、1d（天）")
    print()
    print("环境配置（.env 文件）:")
    print("  GRAFANA_URL=http://grafana:3000")
    print("  GRAFANA_USER=admin")
    print("  GRAFANA_PASSWORD=admin")


def _cli_list(args: list):
    """CLI: 列出 AlertGroup。"""
    status = None
    limit = 25
    if args:
        if args[0] in ("new", "acknowledged", "resolved", "silenced"):
            status = args[0]
            if len(args) > 1:
                limit = int(args[1])
        else:
            limit = int(args[0])

    result = list_alert_groups(status=status, limit=limit)
    groups = result.get("results", [])

    if not groups:
        print(f"没有找到 AlertGroup" + (f"（状态: {status}）" if status else ""))
        return

    print(f"共 {len(groups)} 个 AlertGroup" + (f"（状态: {status}）" if status else "") + ":\n")
    for ag in groups:
        print(_format_alert_group_summary(ag))
        print()


def _cli_get(args: list):
    """CLI: 查看 AlertGroup 详情。"""
    if not args:
        print("错误: 缺少 alert_group_id 参数", file=sys.stderr)
        print("用法: python3 oncall_api.py get <alert_group_id 或 编号>", file=sys.stderr)
        sys.exit(1)

    pk = _resolve_alert_group_id(args[0])
    ag = get_alert_group(pk)
    print("AlertGroup 详情:\n")
    print(_format_alert_group_detail(ag))

    print("\n原始 JSON:")
    print(json.dumps(ag, indent=2, ensure_ascii=False))


def _cli_ack(args: list):
    """CLI: ACK AlertGroup。"""
    if not args:
        print("错误: 缺少 alert_group_id 参数", file=sys.stderr)
        sys.exit(1)

    pk = _resolve_alert_group_id(args[0])
    result = acknowledge(pk)
    print(f"✅ ACK 成功: {args[0]} (pk={pk})")
    if result:
        print(json.dumps(result, indent=2, ensure_ascii=False))


def _cli_unack(args: list):
    """CLI: 取消 ACK。"""
    if not args:
        print("错误: 缺少 alert_group_id 参数", file=sys.stderr)
        sys.exit(1)

    pk = _resolve_alert_group_id(args[0])
    result = unacknowledge(pk)
    print(f"✅ 取消 ACK 成功: {args[0]} (pk={pk})")
    if result:
        print(json.dumps(result, indent=2, ensure_ascii=False))


def _cli_resolve(args: list):
    """CLI: Resolve AlertGroup。"""
    if not args:
        print("错误: 缺少 alert_group_id 参数", file=sys.stderr)
        sys.exit(1)

    pk = _resolve_alert_group_id(args[0])
    result = resolve(pk)
    print(f"✅ Resolve 成功: {args[0]} (pk={pk})")
    if result:
        print(json.dumps(result, indent=2, ensure_ascii=False))


def _cli_unresolve(args: list):
    """CLI: 取消 Resolve。"""
    if not args:
        print("错误: 缺少 alert_group_id 参数", file=sys.stderr)
        sys.exit(1)

    pk = _resolve_alert_group_id(args[0])
    result = unresolve(pk)
    print(f"✅ 取消 Resolve 成功: {args[0]} (pk={pk})")
    if result:
        print(json.dumps(result, indent=2, ensure_ascii=False))


def _cli_silence(args: list):
    """CLI: Silence AlertGroup。"""
    if not args:
        print("错误: 缺少 alert_group_id 参数", file=sys.stderr)
        sys.exit(1)

    pk = _resolve_alert_group_id(args[0])
    delay = 1800
    if len(args) > 1:
        delay = _parse_delay(args[1])

    result = silence(pk, delay=delay)
    print(f"✅ Silence 成功: {args[0]} (pk={pk}), 时长={_format_delay(delay)}")
    if result:
        print(json.dumps(result, indent=2, ensure_ascii=False))


def _cli_unsilence(args: list):
    """CLI: 取消静默。"""
    if not args:
        print("错误: 缺少 alert_group_id 参数", file=sys.stderr)
        sys.exit(1)

    pk = _resolve_alert_group_id(args[0])
    result = unsilence(pk)
    print(f"✅ 取消静默成功: {args[0]} (pk={pk})")
    if result:
        print(json.dumps(result, indent=2, ensure_ascii=False))


def _cli_note(args: list):
    """CLI: 添加 Resolution Note。"""
    if len(args) < 2:
        print("错误: 需要 alert_group_id 和 note 文本", file=sys.stderr)
        print("用法: python3 oncall_api.py note <alert_group_id 或 编号> <文本内容>", file=sys.stderr)
        sys.exit(1)

    pk = _resolve_alert_group_id(args[0])
    text = " ".join(args[1:])
    result = add_resolution_note(pk, text)
    print(f"✅ Resolution Note 添加成功: {args[0]} (pk={pk})")
    print(f"  Note ID:   {result.get('id', '?')}")
    print(f"  作者:      {result.get('author', {}).get('username', '?')}")
    print(f"  创建时间:  {result.get('created_at', '?')}")
    print(f"  内容:      {result.get('text', '')}")


def _cli_notes(args: list):
    """CLI: 查看 Resolution Notes。"""
    if not args:
        print("错误: 缺少 alert_group_id 参数", file=sys.stderr)
        sys.exit(1)

    pk = _resolve_alert_group_id(args[0])
    notes = list_resolution_notes(pk)

    if not notes:
        print(f"AlertGroup {args[0]} (pk={pk}) 没有 Resolution Notes")
        return

    print(f"AlertGroup {args[0]} (pk={pk}) 的 Resolution Notes ({len(notes)} 条):\n")
    for i, note in enumerate(notes, 1):
        author = note.get("author", {}).get("username", "?")
        created = note.get("created_at", "?")
        text = note.get("text", "")
        source = note.get("source", {}).get("display_name", "?")
        print(f"  [{i}] {created} | {author} ({source})")
        print(f"      {text}")
        print()


_CLI_HANDLERS = {
    "list": _cli_list,
    "get": _cli_get,
    "ack": _cli_ack,
    "unack": _cli_unack,
    "resolve": _cli_resolve,
    "unresolve": _cli_unresolve,
    "silence": _cli_silence,
    "unsilence": _cli_unsilence,
    "note": _cli_note,
    "notes": _cli_notes,
    "help": lambda _: _print_usage(),
}


def main():
    if len(sys.argv) < 2:
        _print_usage()
        sys.exit(0)

    command = sys.argv[1].lower()
    args = sys.argv[2:]

    handler = _CLI_HANDLERS.get(command)
    if not handler:
        print(f"错误: 未知命令 '{command}'", file=sys.stderr)
        print(f"可用命令: {', '.join(_CLI_HANDLERS.keys())}", file=sys.stderr)
        sys.exit(1)

    try:
        handler(args)
    except RuntimeError as e:
        print(f"❌ 操作失败: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n操作已取消", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"❌ 未预期的错误: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
