"""本机 Chrome/Edge 的查找、空闲端口选择与 CDP 子进程启动。"""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
from pathlib import Path

from crawler.bootstrap.settings import Settings
from crawler.browser.errors import CDPConnectionError
from playwright.async_api import Playwright

_PORT_SCAN_SPAN = 100
_BIND_HOST = "127.0.0.1"
_READY_POLL_INTERVAL = 0.5
_PROBE_TIMEOUT = 0.5


class LocalChromeLauncher:
    """查找本机浏览器并启动一个开启 CDP 调试端口的进程，等待其就绪。

    仅负责"找到可执行文件并拉起进程"，附加连接由会话/连接器完成。
    """

    def __init__(self, config: Settings) -> None:
        """初始化启动器。

        参数：
            config: 应用配置对象，读取浏览器路径、无头模式与就绪超时等设置。
        """
        self.config = config

    def find_executable(self) -> str | None:
        """按配置与常见安装路径查找本机 Chrome/Edge 可执行文件。"""
        configured = self.config.DOUYIN_CDP_BROWSER_PATH.strip()
        if configured:
            return configured
        candidates = [
            shutil.which("google-chrome"),
            shutil.which("google-chrome-stable"),
            shutil.which("chromium"),
            shutil.which("chromium-browser"),
            shutil.which("msedge"),
        ]
        if os.name == "nt":
            roots = [
                os.getenv("PROGRAMFILES"),
                os.getenv("PROGRAMFILES(X86)"),
                os.getenv("LOCALAPPDATA"),
            ]
            for root in filter(None, roots):
                candidates.extend(
                    [
                        str(Path(root) / "Google/Chrome/Application/chrome.exe"),
                        str(Path(root) / "Microsoft/Edge/Application/msedge.exe"),
                    ]
                )
        return next(
            (str(path) for path in candidates if path and Path(path).is_file()), None
        )

    def find_free_port(self, start: int) -> int:
        """从起始端口向后寻找可用端口，找不到时抛出 CDPConnectionError。"""
        for port in range(start, min(start + _PORT_SCAN_SPAN, 65536)):
            with socket.socket() as candidate:
                try:
                    candidate.bind((_BIND_HOST, port))
                except OSError:
                    continue
                return port
        raise CDPConnectionError("没有可用的 CDP 调试端口")

    async def launch(
        self,
        *,
        playwright: Playwright,
        debug_port: int,
        user_data_dir: Path,
    ) -> subprocess.Popen[bytes]:
        """启动开启 CDP 调试端口的 Chrome/Edge 进程并等待其就绪。

        参数：
            playwright: 已启动的 Playwright 驱动实例（用于兜底的可执行文件路径）。
            debug_port: CDP 调试端口。
            user_data_dir: 浏览器用户数据目录。

        返回：
            已就绪的浏览器进程。

        异常：
            CDPConnectionError: 找不到浏览器、进程提前退出或等待就绪超时时抛出。
        """
        executable = self.find_executable() or playwright.chromium.executable_path
        if not executable or not Path(executable).is_file():
            raise CDPConnectionError(
                "未找到 Chrome/Edge。请设置 DOUYIN_CDP_BROWSER_PATH，或连接已开启 CDP 的浏览器"
            )
        resolved_dir = user_data_dir.resolve()
        resolved_dir.mkdir(parents=True, exist_ok=True)
        command = [
            executable,
            "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={debug_port}",
            f"--user-data-dir={resolved_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
        ]
        if self.config.DOUYIN_CDP_HEADLESS:
            command.append("--headless=new")
        creationflags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
        )
        process = subprocess.Popen(command, creationflags=creationflags)
        deadline = (
            asyncio.get_running_loop().time() + self.config.DOUYIN_CDP_CONNECT_TIMEOUT
        )
        try:
            while asyncio.get_running_loop().time() < deadline:
                if process.poll() is not None:
                    raise CDPConnectionError(
                        f"浏览器进程提前退出，退出码: {process.returncode}"
                    )
                if await self._port_open(debug_port):
                    return process
                await asyncio.sleep(_READY_POLL_INTERVAL)
        except BaseException:
            # 等待就绪失败时确保不再遗留半启动的浏览器进程。
            if process.poll() is None:
                process.terminate()
            raise
        raise CDPConnectionError("等待 CDP 浏览器启动超时")

    async def _port_open(self, port: int) -> bool:
        """探测本机指定 CDP 端口是否可建立 TCP 连接。"""
        return await asyncio.to_thread(self._connect_probe, port)

    def _connect_probe(self, port: int) -> bool:
        try:
            with socket.create_connection(
                (self.config.DOUYIN_CDP_HOST, port), timeout=_PROBE_TIMEOUT
            ):
                return True
        except OSError:
            return False
