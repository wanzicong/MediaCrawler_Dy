"""Bounded FFmpeg subprocess execution for transcription audio extraction."""

from __future__ import annotations

import asyncio
from pathlib import Path


class FFmpegError(RuntimeError):
    """Base error for neutral FFmpeg execution failures."""


class FFmpegNotFoundError(FFmpegError):
    """The configured FFmpeg binary could not be executed."""


class FFmpegTimeoutError(FFmpegError):
    """FFmpeg exceeded its bounded preprocessing deadline."""


class FFmpegOutputUnavailableError(FFmpegError):
    """FFmpeg failed or did not create the requested output file."""


class FFmpegEmptyOutputError(FFmpegError):
    """FFmpeg created an empty output file."""


async def extract_transcription_audio(
    *,
    binary: str,
    input_path: Path,
    output_path: Path,
    bitrate_kbps: int,
    timeout: float,
) -> None:
    """Convert video input to mono 16 kHz MP3 with the existing exact command."""
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
