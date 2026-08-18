"""带超时上限的 FFmpeg 子进程执行器，用于提取转写（transcription）所需的音频。"""

from __future__ import annotations

import asyncio
from pathlib import Path


class FFmpegError(RuntimeError):
    """与平台无关的 FFmpeg 执行失败的基类错误。"""


class FFmpegNotFoundError(FFmpegError):
    """配置的 FFmpeg 可执行文件无法启动。"""


class FFmpegTimeoutError(FFmpegError):
    """FFmpeg 超出了为其设定的预处理时限。"""


class FFmpegOutputUnavailableError(FFmpegError):
    """FFmpeg 执行失败或未生成预期的输出文件。"""


class FFmpegEmptyOutputError(FFmpegError):
    """FFmpeg 生成了空输出文件。"""


async def extract_transcription_audio(
    *,
    binary: str,
    input_path: Path,
    output_path: Path,
    bitrate_kbps: int,
    timeout: float,
) -> None:
    """沿用既有命令行参数，将视频输入转换为单声道 16 kHz 的 MP3 音频。

    参数：
        binary: FFmpeg 可执行文件路径或命令名。
        input_path: 输入视频文件路径。
        output_path: 输出音频文件路径。
        bitrate_kbps: 输出音频码率（kbps）。
        timeout: 子进程执行的最长秒数，超时后强制结束进程。

    异常：
        FFmpegNotFoundError: FFmpeg 可执行文件不存在。
        FFmpegTimeoutError: 执行超时。
        FFmpegOutputUnavailableError: 进程返回码非零或未生成输出文件。
        FFmpegEmptyOutputError: 输出文件为空。
    """
    try:
        process = await asyncio.create_subprocess_exec(
            binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-i",
            str(input_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            f"{bitrate_kbps}k",
            str(output_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        raise FFmpegNotFoundError from exc

    try:
        await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.communicate()
        raise FFmpegTimeoutError from exc

    if process.returncode != 0 or not output_path.is_file():
        raise FFmpegOutputUnavailableError
    if output_path.stat().st_size <= 0:
        raise FFmpegEmptyOutputError


__all__ = [
    "FFmpegEmptyOutputError",
    "FFmpegError",
    "FFmpegNotFoundError",
    "FFmpegOutputUnavailableError",
    "FFmpegTimeoutError",
    "extract_transcription_audio",
]
