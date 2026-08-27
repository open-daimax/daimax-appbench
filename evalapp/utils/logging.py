"""Logging configuration for EvalApp."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from rich.logging import RichHandler

_configured = False
_file_handler: logging.FileHandler | None = None
_log_file_path: Path | None = None


def setup_logging(verbose: bool = False) -> None:
    """Configure logging with Rich handler.

    Uses explicit root-logger manipulation instead of ``basicConfig`` so
    that the configuration always takes effect even when a third-party
    library has already added a handler to the root logger (which makes
    ``basicConfig`` a silent no-op).
    """
    global _configured
    if _configured:
        return

    level = logging.DEBUG if verbose else logging.INFO
    root = logging.getLogger()
    # Set root to DEBUG so per-handler levels do the real filtering.
    root.setLevel(logging.DEBUG)

    handler = RichHandler(rich_tracebacks=True, show_path=False)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter("%(message)s", datefmt="[%X]"))
    root.addHandler(handler)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Get a named logger."""
    return logging.getLogger(name)


def start_file_logging(log_dir: Path, filename: str = "eval.log") -> Path:
    """Add a file handler to the root logger.

    Returns the path to the log file.
    """
    global _file_handler, _log_file_path
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / filename
    _log_file_path = log_path

    _file_handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    _file_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s  %(name)-36s  %(levelname)-7s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    _file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.addHandler(_file_handler)

    # Ensure the root logger level is permissive enough for the file
    # handler to receive messages.  When setup_logging() was skipped or
    # basicConfig silently failed, the root level stays at WARNING (30)
    # which blocks all INFO/DEBUG records before they reach any handler.
    if root.level > logging.DEBUG:
        # Pin existing handlers to their current effective level so they
        # don't suddenly start emitting DEBUG noise on the console.
        for h in root.handlers:
            if h is not _file_handler and h.level == logging.NOTSET:
                h.setLevel(root.level)
        root.setLevel(logging.DEBUG)

    return log_path


def stop_file_logging() -> Path | None:
    """Remove the file handler and return the log file path."""
    global _file_handler, _log_file_path
    if _file_handler is not None:
        _file_handler.flush()
        _file_handler.close()
        logging.getLogger().removeHandler(_file_handler)
        _file_handler = None
    path = _log_file_path
    _log_file_path = None
    return path


def copy_log_to(dest_dir: Path, filename: str = "eval.log") -> Path | None:
    """Flush the current log file and copy it to *dest_dir*.

    The file handler keeps writing to the original location.
    Returns the destination path, or None if no active log.
    """
    if _file_handler is None or _log_file_path is None:
        return None
    _file_handler.flush()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    shutil.copy2(_log_file_path, dest)
    return dest
