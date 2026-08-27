"""Subprocess execution utilities.

Provides helpers to run subprocesses with real-time output streaming while
still capturing stdout/stderr for downstream parsing, as well as simple
shell-command wrappers (formerly ``utils.shell``).
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any, cast

from .logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Simple shell-command wrappers (migrated from utils/shell.py)
# ---------------------------------------------------------------------------


@dataclass
class Result:
    """Holds the execution result of a subprocess command."""

    stdout: str
    stderr: str
    exit_code: int

    def __init__(self, stdout: str | bytes, stderr: str | bytes, exit_code: int):
        self.stdout = (
            stdout.decode("utf-8", "ignore")
            if isinstance(stdout, bytes)
            else cast(str, stdout)
        )
        self.stderr = (
            stderr.decode("utf-8", "ignore")
            if isinstance(stderr, bytes)
            else cast(str, stderr)
        )
        self.exit_code = exit_code


def run_command(
    command: str | list[str], cwd: str | None = None, timeout: int | None = None
) -> Result:
    """Runs a command and returns the output and error.

    Args:
        command: The command to run. Pass a ``list[str]`` whenever the
            arguments may originate from external input — the list form is
            executed with ``shell=False`` to avoid shell-injection. Plain
            ``str`` is still supported for trusted, hard-coded commands and
            is executed with ``shell=True`` for backward compatibility.
        cwd: The working directory to run the command in.
        timeout: The timeout for the command in seconds.

    Returns:
        A Result containing stdout, stderr, and exit code.
    """
    use_shell = isinstance(command, str)
    try:
        logging.info("Running command: %s, cwd=%s, shell=%s", command, cwd, use_shell)
        result: subprocess.CompletedProcess[str] = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            cwd=cwd,
            shell=use_shell,
            timeout=timeout,
        )
        return Result(
            stdout=result.stdout, stderr=result.stderr, exit_code=result.returncode
        )
    except subprocess.CalledProcessError as e:
        logging.error(
            f"Command {command} failed, error: {e.stderr}, exit code: {e.returncode}."
        )
        return Result(e.output or b"", e.stderr or b"", e.returncode)
    except subprocess.TimeoutExpired as e:
        logging.error(f"Command {command} timed out after {e.timeout} seconds.")
        return Result(e.output or b"", e.stderr or b"", 1)


def run_command_async(
    command: str | list[str], cwd: str | None = None
) -> subprocess.Popen[Any]:
    """Runs a command asynchronously and returns the Popen object.

    Args:
        command: Same semantics as :func:`run_command` — prefer a
            ``list[str]`` when arguments include external input so that the
            subprocess runs with ``shell=False``.
        cwd: The working directory to run the command in.

    Returns:
        A subprocess.Popen object representing the running child process.
    """
    use_shell = isinstance(command, str)
    return subprocess.Popen(
        command,
        cwd=cwd,
        shell=use_shell,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# ---------------------------------------------------------------------------
# Streaming subprocess execution
# ---------------------------------------------------------------------------


@dataclass
class StreamingResult:
    """Result from a streaming subprocess execution."""

    returncode: int
    stdout: str
    stderr: str
    duration: float  # seconds
    timed_out: bool = False


def _kill_process_group(proc: subprocess.Popen) -> None:
    """Kill a process and its entire process group.

    Since we use start_new_session=True, the subprocess is the leader of its
    own process group. Sending SIGKILL to the negative PID kills all processes
    in that group, including any children spawned by the subprocess (e.g.
    Claude CLI agents, file watchers).
    """
    pgid = None
    try:
        pgid = os.getpgid(proc.pid)
    except (OSError, ProcessLookupError) as e:
        logger.debug("获取 pgid 失败，退化为单进程杀量 (pid=%s): %s", proc.pid, e)

    if pgid and pgid != os.getpgid(os.getpid()):
        # Kill the entire process group
        try:
            os.killpg(pgid, signal.SIGTERM)
        except (OSError, ProcessLookupError) as e:
            logger.debug("SIGTERM 进程组失败 (pgid=%s): %s", pgid, e)
        # Give processes a moment to terminate gracefully
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            # Force kill if SIGTERM didn't work
            try:
                os.killpg(pgid, signal.SIGKILL)
            except (OSError, ProcessLookupError) as e:
                logger.debug("SIGKILL 进程组失败 (pgid=%s): %s", pgid, e)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("进程组 %s 在 SIGKILL 后仍未退出", pgid)
    else:
        # Fallback: kill just the process
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logger.warning("进程 %s 在 kill 后仍未退出", proc.pid)


def _reader_thread(
    stream,
    collected: list[str],
    prefix: str,
    stream_enabled: bool,
) -> None:
    """Read lines from a stream, optionally logging them in real time."""
    try:
        for line in stream:
            collected.append(line)
            if stream_enabled:
                # Print to stdout for real-time console output (task_runner reads this)
                print(f"[{prefix}] {line.rstrip(chr(10))}", flush=True)
    except (OSError, ValueError) as e:
        logger.debug("_reader_thread 读取 stream 失败 (prefix=%s): %s", prefix, e)
    finally:
        stream.close()


def run_streaming(
    cmd: list[str],
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 3600,
    stream: bool = False,
    prefix: str = "proc",
    stdin_text: str | None = None,
) -> StreamingResult:
    """Run a subprocess with optional real-time output streaming.

    When *stream* is True, stdout and stderr lines are logged via the
    module logger as they arrive.  Regardless of the *stream* flag, the
    full stdout/stderr text is captured and returned for parsing.

    Args:
        cmd: Command and arguments to execute.
        cwd: Working directory for the subprocess.
        env: Environment variables.  If ``None`` the current environment
            (minus ``CLAUDECODE``) is used.
        timeout: Maximum execution time in seconds.
        stream: Whether to print output lines in real time.
        prefix: Label shown in the ``[prefix]`` log tag when streaming.

    Returns:
        A :class:`StreamingResult` with captured output and timing.
    """
    if env is None:
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    
    # Force line buffering by setting PYTHONUNBUFFERED and other env vars
    env["PYTHONUNBUFFERED"] = "1"
    env["FORCE_COLOR"] = "1"  # Some tools use this to detect TTY

    start = time.time()

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE if stdin_text else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=cwd,
            env=env,
            bufsize=1,  # Line buffered
            start_new_session=True,  # Create new process group so we can kill all children
        )
    except FileNotFoundError:
        # subprocess.Popen 招 FileNotFoundError 有两种原因：
        #   1. cwd 指向的工作目录不存在；
        #   2. cmd[0] 对应的可执行文件不存在。
        # 此前一律报 "Command not found: {cmd[0]}"，造成误导。这里区分
        # 两种场景给出可诊断信息。
        if cwd is not None and not os.path.isdir(cwd):
            err_msg = f"Working directory does not exist: {cwd}"
        else:
            err_msg = f"Command not found: {cmd[0]}"
        return StreamingResult(
            returncode=-1,
            stdout="",
            stderr=err_msg,
            duration=time.time() - start,
        )

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    stdout_thread = threading.Thread(
        target=_reader_thread,
        args=(proc.stdout, stdout_lines, prefix, stream),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_reader_thread,
        args=(proc.stderr, stderr_lines, f"{prefix}:err", stream),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()

    # Feed stdin text if provided (e.g. auto-confirm prompts)
    if stdin_text and proc.stdin:
        try:
            proc.stdin.write(stdin_text)
            proc.stdin.flush()
            proc.stdin.close()
        except (OSError, BrokenPipeError) as e:
            logger.debug("向子进程 stdin 写入失败: %s", e)

    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_process_group(proc)
        stderr_lines.append(f"\nCommand timed out after {timeout}s")

    # Ensure reader threads finish draining
    stdout_thread.join(timeout=5)
    stderr_thread.join(timeout=5)

    duration = time.time() - start
    return StreamingResult(
        returncode=proc.returncode if proc.returncode is not None else 124,
        stdout="".join(stdout_lines),
        stderr="".join(stderr_lines),
        duration=duration,
        timed_out=timed_out,
    )
