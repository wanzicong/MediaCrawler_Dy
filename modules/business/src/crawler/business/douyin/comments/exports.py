"""抖音评论与字幕导出模块。

负责将数据库中的评论、字幕数据组装为可下载的 txt/srt/vtt/zip 临时文件，
供 API 层以文件流形式返回给前端用户。
"""

import json
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from crawler.business.douyin.comments.models import DouyinComment
from crawler.business.douyin.content.models import DouyinAweme
from crawler.business.douyin.media.models import DouyinSubtitle
from crawler.business.douyin.tasks.models import CrawlTask
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import Session, col, select

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _time_text(timestamp: int | None) -> str:
    """将 Unix 秒级时间戳格式化为上海时区的时间字符串，空值返回「未知」。"""
    if not timestamp:
        return "未知"
    return (
        datetime.fromtimestamp(timestamp, tz=timezone.utc)
        .astimezone(SHANGHAI)
        .strftime("%Y-%m-%d %H:%M:%S")
    )


def build_comments_export(
    session: Session, *, task_id: uuid.UUID, aweme_ids: list[str]
) -> tuple[Path, str]:
    """按任务导出指定作品的全部已保存评论，生成单个 txt 文件。

    参数：
        session: 数据库会话。
        task_id: 采集任务 ID，限定导出范围。
        aweme_ids: 待导出的作品号列表（自动去空白与去重）。

    返回：
        二元组 (临时文件路径, 建议下载文件名)。文件按作品分节，
        评论按发布时间升序排列，使用 utf-8-sig 编码便于 Excel 直接打开。
    """
    selected = list(
        dict.fromkeys(value.strip() for value in aweme_ids if value.strip())
    )
    awemes = session.exec(
        select(DouyinAweme)
        .where(
            DouyinAweme.task_id == task_id,
            col(DouyinAweme.aweme_id).in_(selected),
        )
        .order_by(col(DouyinAweme.create_time).desc())
    ).all()
    comments = session.exec(
        select(DouyinComment)
        .where(
            DouyinComment.task_id == task_id,
            col(DouyinComment.aweme_id).in_(selected),
        )
        .order_by(
            col(DouyinComment.aweme_id),
            col(DouyinComment.create_time).asc(),
        )
    ).all()
    grouped: dict[str, list[DouyinComment]] = {item.aweme_id: [] for item in awemes}
    for comment in comments:
        grouped.setdefault(comment.aweme_id, []).append(comment)

    text_handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8-sig",
        newline="",
        prefix="douyin-comments-",
        suffix=".txt",
        delete=False,
    )
    with text_handle:
        text_handle.write("抖音视频评论导出\r\n")
        text_handle.write(f"导出时间：{datetime.now(SHANGHAI):%Y-%m-%d %H:%M:%S}\r\n")
        text_handle.write(f"视频数量：{len(awemes)}\r\n\r\n")
        for aweme in awemes:
            rows = grouped.get(aweme.aweme_id, [])
            text_handle.write("=" * 72 + "\r\n")
            text_handle.write(f"视频：{aweme.title or aweme.aweme_id}\r\n")
            text_handle.write(f"作品号：{aweme.aweme_id}\r\n")
            text_handle.write(f"作者：{aweme.nickname or '未知'}\r\n")
            text_handle.write(f"发布时间：{_time_text(aweme.create_time)}\r\n")
            text_handle.write(f"已保存评论：{len(rows)} 条\r\n")
            text_handle.write("-" * 72 + "\r\n")
            if not rows:
                text_handle.write("（暂无已保存评论）\r\n")
            for index, comment in enumerate(rows, 1):
                prefix = "回复" if comment.parent_comment_id != "0" else "评论"
                content = comment.content.replace("\r", " ").replace("\n", " ")
                text_handle.write(
                    f"[{index}] {prefix}时间：{_time_text(comment.create_time)} | "
                    f"用户：{comment.nickname or '匿名'} | 点赞：{comment.like_count}\r\n"
                )
                text_handle.write(f"{content}\r\n\r\n")
    return Path(text_handle.name), f"douyin-comments-{task_id}.txt"


def build_comment_selection_export(
    session: Session,
    *,
    owner_id: uuid.UUID | None,
    comment_ids: list[uuid.UUID],
) -> tuple[Path, str, int]:
    """按选中的评论 ID 导出评论精选（跨任务），生成单个 txt 文件。

    参数：
        session: 数据库会话。
        owner_id: 数据归属用户 ID；非 None 时限定只能导出本人任务的评论。
        comment_ids: 待导出的评论记录 ID 列表（自动去重）。

    返回：
        三元组 (临时文件路径, 建议下载文件名, 实际导出条数)。
    """
    selected = list(dict.fromkeys(comment_ids))
    filters: list[ColumnElement[bool]] = [col(DouyinComment.id).in_(selected)]
    if owner_id is not None:
        filters.append(col(CrawlTask.owner_id) == owner_id)
    rows = session.exec(
        select(DouyinComment, DouyinAweme)
        .join(
            DouyinAweme,
            (col(DouyinAweme.task_id) == col(DouyinComment.task_id))
            & (col(DouyinAweme.aweme_id) == col(DouyinComment.aweme_id)),
        )
        .join(CrawlTask, col(CrawlTask.id) == col(DouyinComment.task_id))
        .where(*filters)
        .order_by(
            col(DouyinComment.create_time).desc(),
            col(DouyinComment.fetched_at).desc(),
        )
    ).all()

    text_handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8-sig",
        newline="",
        prefix="douyin-selected-comments-",
        suffix=".txt",
        delete=False,
    )
    with text_handle:
        text_handle.write("抖音评论精选导出\r\n")
        text_handle.write(f"导出时间：{datetime.now(SHANGHAI):%Y-%m-%d %H:%M:%S}\r\n")
        text_handle.write(f"评论数量：{len(rows)}\r\n\r\n")
        for index, (comment, aweme) in enumerate(rows, 1):
            comment_type = (
                "回复" if comment.parent_comment_id not in {"", "0"} else "主评论"
            )
            content = comment.content.replace("\r", " ").replace("\n", " ")
            text_handle.write("=" * 72 + "\r\n")
            text_handle.write(
                f"[{index}] {comment_type} · 点赞：{comment.like_count}\r\n"
            )
            text_handle.write(f"评论人：{comment.nickname or '匿名'}\r\n")
            text_handle.write(f"评论时间：{_time_text(comment.create_time)}\r\n")
            text_handle.write(f"作品：{aweme.title or aweme.aweme_id}\r\n")
            text_handle.write(f"作品号：{aweme.aweme_id}\r\n")
            text_handle.write(f"视频作者：{aweme.nickname or '未知'}\r\n")
            text_handle.write(
                f"视频链接：https://www.douyin.com/video/{aweme.aweme_id}\r\n"
            )
            text_handle.write("-" * 72 + "\r\n")
            text_handle.write(f"{content}\r\n\r\n")
    return (
        Path(text_handle.name),
        f"douyin-selected-comments-{datetime.now(SHANGHAI):%Y%m%d-%H%M%S}.txt",
        len(rows),
    )


def build_subtitles_export(
    session: Session,
    *,
    task_id: uuid.UUID,
    aweme_ids: list[str],
    export_format: str,
) -> tuple[Path, str, str]:
    """按任务导出指定作品的字幕，支持 txt/srt/vtt 格式。

    仅导出状态为 completed 的字幕；单个作品时直接返回字幕文件，
    多个作品时打包为 zip 并附「导出说明.txt」清单。

    参数：
        session: 数据库会话。
        task_id: 采集任务 ID，限定导出范围。
        aweme_ids: 待导出的作品号列表（自动去空白与去重）。
        export_format: 导出格式，取值为 txt、srt 或 vtt。

    返回：
        三元组 (临时文件路径, 建议下载文件名, 响应 Content-Type)。
    """
    selected = list(
        dict.fromkeys(value.strip() for value in aweme_ids if value.strip())
    )
    subtitles = session.exec(
        select(DouyinSubtitle).where(
            DouyinSubtitle.task_id == task_id,
            col(DouyinSubtitle.aweme_id).in_(selected),
        )
    ).all()
    by_aweme = {subtitle.aweme_id: subtitle for subtitle in subtitles}
    completed = [
        by_aweme[aweme_id]
        for aweme_id in selected
        if aweme_id in by_aweme and by_aweme[aweme_id].status == "completed"
    ]
    missing = [
        aweme_id
        for aweme_id in selected
        if aweme_id not in {x.aweme_id for x in completed}
    ]
    if len(selected) == 1 and completed:
        subtitle = completed[0]
        content = _subtitle_content(subtitle, export_format)
        subtitle_handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8-sig" if export_format == "txt" else "utf-8",
            newline="",
            prefix="douyin-subtitle-",
            suffix=f".{export_format}",
            delete=False,
        )
        with subtitle_handle:
            subtitle_handle.write(content)
        return (
            Path(subtitle_handle.name),
            f"douyin-{subtitle.aweme_id}.{export_format}",
            "text/plain; charset=utf-8",
        )

    zip_handle = tempfile.NamedTemporaryFile(
        prefix="douyin-subtitles-", suffix=".zip", delete=False
    )
    zip_handle.close()
    path = Path(zip_handle.name)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for subtitle in completed:
            archive.writestr(
                f"douyin-{subtitle.aweme_id}.{export_format}",
                _subtitle_content(subtitle, export_format).encode("utf-8-sig"),
            )
        manifest = [
            "抖音字幕批量导出",
            f"成功：{len(completed)} 个",
            f"未完成或不存在：{len(missing)} 个",
        ]
        if missing:
            manifest.extend(["", "未导出的作品号：", *missing])
        archive.writestr("导出说明.txt", "\r\n".join(manifest).encode("utf-8-sig"))
    return path, f"douyin-subtitles-{task_id}.zip", "application/zip"


def _subtitle_content(subtitle: DouyinSubtitle, export_format: str) -> str:
    """把单条字幕记录渲染为 txt/srt/vtt 文本内容；分段数据缺失时回退为整段全文。"""
    if export_format == "txt":
        return (subtitle.full_text or "").strip() + "\n"
    try:
        raw = json.loads(subtitle.segments_json or "[]")
    except json.JSONDecodeError:
        raw = []
    segments = [value for value in raw if isinstance(value, dict)]
    if not segments and subtitle.full_text:
        segments = [
            {"start": 0.0, "end": subtitle.duration_seconds, "text": subtitle.full_text}
        ]
    if export_format == "vtt":
        blocks = ["WEBVTT", ""]
        for segment in segments:
            blocks.extend(
                [
                    f"{_cue_time(segment.get('start'), vtt=True)} --> {_cue_time(segment.get('end'), vtt=True)}",
                    str(segment.get("text") or "").strip(),
                    "",
                ]
            )
        return "\n".join(blocks)
    blocks = []
    for index, segment in enumerate(segments, 1):
        blocks.extend(
            [
                str(index),
                f"{_cue_time(segment.get('start'))} --> {_cue_time(segment.get('end'))}",
                str(segment.get("text") or "").strip(),
                "",
            ]
        )
    return "\n".join(blocks)


def _cue_time(value: object, *, vtt: bool = False) -> str:
    """将秒数转换为字幕时间码；vtt 用「.」分隔毫秒，srt 用「,」，非法值按 0 处理。"""
    try:
        milliseconds = max(0, round(float(str(value or 0)) * 1000))
    except (TypeError, ValueError):
        milliseconds = 0
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    separator = "." if vtt else ","
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{millis:03d}"
