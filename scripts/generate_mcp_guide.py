"""生成《MCP 使用指南》里的「接口 ↔ MCP 工具 ↔ 前端调用点」对照表。

表格插入 ``docs/MCP使用指南.md`` 中
``<!-- BEGIN GENERATED INVENTORY -->`` 与 ``<!-- END GENERATED INVENTORY -->``
之间；其余部分（概念、鉴权、示例、约定）为手写内容，脚本不覆盖。

用法::

    uv run python scripts/generate_mcp_guide.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "modules" / "mcp" / "src" / "crawler" / "mcp" / "tools_spec.json"
SDK = ROOT / "frontend" / "src" / "client" / "sdk.gen.ts"
GUIDE = ROOT / "docs" / "MCP使用指南.md"
FRONTEND_SRC = ROOT / "frontend" / "src"
BEGIN = "<!-- BEGIN GENERATED INVENTORY -->"
END = "<!-- END GENERATED INVENTORY -->"

# 域名 → 中文分组标题（按路径前缀匹配，未命中的归到「其它接口」）
GROUP_TITLES: list[tuple[str, str]] = [
    ("/douyin/accounts", "抖音 · 账号与浏览器"),
    ("/douyin/tasks", "抖音 · 采集任务"),
    ("/douyin/media-tasks", "抖音 · 下载与字幕任务"),
    ("/douyin/library", "抖音 · 视频资源库"),
    ("/douyin/creators", "抖音 · 达人名单"),
    ("/douyin/keywords", "抖音 · 关键词"),
    ("/douyin/tracks", "抖音 · 赛道"),
    ("/douyin/categories", "抖音 · 内容分类"),
    ("/douyin/my", "抖音 · 我的（关注/点赞/收藏）"),
    ("/douyin/interactions", "抖音 · 互动"),
    ("/douyin/comments", "抖音 · 评论管理"),
    ("/douyin/tags", "抖音 · 标签"),
    ("/douyin/request-logs", "抖音 · 请求日志"),
    ("/douyin/ui-labels", "抖音 · 界面文案"),
    ("/douyin/source-options", "抖音 · 来源筛选"),
    ("/douyin", "抖音 · 其它"),
    ("/users", "用户与账号"),
    ("/login", "登录与密码"),
    ("/password-recovery", "登录与密码"),
    ("/reset-password", "登录与密码"),
    ("/items", "示例 Items"),
    ("/system", "系统管理"),
    ("/utils", "运维工具"),
    ("/private", "本地私有路由"),
]


def sdk_methods() -> dict[tuple[str, str], str]:
    """从生成的 TypeScript 客户端里取 {(method, path): sdkMethodName}。"""
    text = SDK.read_text(encoding="utf-8")
    mapping: dict[tuple[str, str], str] = {}
    pattern = re.compile(
        r"public static (\w+)\(.*?method: '(\w+)',\s*url: '([^']+)'",
        re.DOTALL,
    )
    for match in pattern.finditer(text):
        name, method, url = match.groups()
        mapping[(method.upper(), url)] = name
    return mapping


def frontend_callers(method_name: str) -> list[str]:
    """找出前端源码里调用该 SDK 方法的文件（最多 3 个，便于定位）。"""
    if not method_name:
        return []
    call = re.compile(rf"\.{re.escape(method_name)}\(")
    hits: list[str] = []
    for path in sorted(FRONTEND_SRC.rglob("*.ts*")):
        if "client/" in path.as_posix():
            continue
        if call.search(path.read_text(encoding="utf-8", errors="ignore")):
            hits.append(path.relative_to(ROOT / "frontend").as_posix())
    return hits


def group_of(path: str) -> str:
    for prefix, title in GROUP_TITLES:
        if path.startswith(prefix):
            return title
    return "其它接口"


def params_summary(operation: dict) -> str:
    """参数摘要：必填加粗标记，最多列 6 个，其余折叠。"""
    parts: list[str] = []
    for group in ("path_params", "query_params", "body_params"):
        for param in operation.get(group, []):
            label = param["name"]
            if param.get("required"):
                label = f"**{label}**"
            if param.get("enum"):
                label = f"{label}（{'/'.join(param['enum'][:6])}）"
            parts.append(label)
    if not parts:
        return "—"
    if len(parts) > 6:
        return "、".join(parts[:6]) + f" …共 {len(parts)} 个"
    return "、".join(parts)


def build_table() -> str:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    methods = sdk_methods()
    grouped: dict[str, list[dict]] = {}
    for operation in spec["operations"]:
        grouped.setdefault(group_of(operation["path"]), []).append(operation)

    lines: list[str] = []
    order = [title for _, title in GROUP_TITLES] + ["其它接口"]
    for title in dict.fromkeys(order):
        operations = grouped.get(title)
        if not operations:
            continue
        lines.append(f"### {title}")
        lines.append("")
        lines.append(
            "| 后端接口 | MCP 工具 | 参数（**加粗**=必填） | 前端 SDK / 调用位置 |"
        )
        lines.append("| --- | --- | --- | --- |")
        for operation in operations:
            endpoint = f"`{operation['method']} /api/v1{operation['path']}`"
            tool = f"`{operation['name']}`"
            sdk_name = methods.get((operation["method"], f"/api/v1{operation['path']}"))
            if sdk_name:
                callers = frontend_callers(sdk_name)
                where = (
                    "、".join(f"`{item}`" for item in callers[:2])
                    or "（生成客户端，未见直接调用）"
                )
                if len(callers) > 2:
                    where += f" 等 {len(callers)} 处"
                frontend = f"`{sdk_name}` · {where}"
            else:
                frontend = "—"
            lines.append(
                f"| {endpoint} | {tool} | {params_summary(operation)} | {frontend} |"
            )
        lines.append("")
    lines.append(
        f"合计 **{spec['operation_count']}** 个接口 / 工具（另有 32 个参数经过裁剪的"
        "便捷工具，见指南正文「两套工具」一节）。"
    )
    return "\n".join(lines)


def main() -> None:
    table = build_table()
    text = GUIDE.read_text(encoding="utf-8")
    start = text.index(BEGIN) + len(BEGIN)
    end = text.index(END)
    GUIDE.write_text(
        text[:start] + "\n\n" + table + "\n\n" + text[end:], encoding="utf-8"
    )
    sys.stdout.write(
        f"已更新 {GUIDE.relative_to(ROOT)} 的对照表（{len(table.splitlines())} 行）\n"
    )


if __name__ == "__main__":
    main()
