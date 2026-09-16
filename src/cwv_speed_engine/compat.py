"""Cross-platform compatibility layer for CWV Speed Engine.

Provides multi-OS support across Linux, Termux (Android), macOS, and Windows.
Zero external dependencies - pure Python stdlib.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any, Dict, Optional, Union


def is_termux() -> bool:
    """Return True if executing inside a Termux Android environment."""
    if "TERMUX_VERSION" in os.environ:
        return True
    prefix = os.environ.get("PREFIX", "")
    if prefix.startswith("/data/data/com.termux") or prefix.startswith("/data/user/0/com.termux"):
        return True
    if os.path.exists("/data/data/com.termux"):
        return True
    return False


def is_windows() -> bool:
    """Return True if running on Windows OS."""
    return platform.system() == "Windows" or sys.platform.startswith("win")


def is_macos() -> bool:
    """Return True if running on macOS (Darwin)."""
    return platform.system() == "Darwin" or sys.platform == "darwin"


def is_linux() -> bool:
    """Return True if running on standard Linux (excluding Termux)."""
    return (platform.system() == "Linux" or sys.platform.startswith("linux")) and not is_termux()


def configure_utf8_streams() -> None:
    """Configure sys.stdout and sys.stderr for UTF-8 encoding safely across platforms.

    Handles detached streams, already-wrapped streams, or environments where
    reconfigure is not supported or raises an exception.
    """
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError, io_error_types()):
                pass


def io_error_types() -> tuple:
    """Helper returning tuple of standard IO error classes."""
    return (OSError, IOError, ValueError)


def safe_print(*args: Any, sep: str = " ", end: str = "\n", file: Optional[Any] = None, flush: bool = False) -> None:
    """Print output safely, falling back to safe Unicode replacement if terminal encoding fails.

    Args:
        *args: Values to print.
        sep: String separator between arguments.
        end: String to append at the end.
        file: Output stream (defaults to sys.stdout).
        flush: Whether to forcibly flush the stream.
    """
    out = file if file is not None else sys.stdout
    text = sep.join(str(arg) for arg in args) + end

    try:
        out.write(text)
    except (UnicodeEncodeError, UnicodeError):
        # Fallback for restrictive console encodings (e.g., cp1252 / ascii)
        target_encoding = getattr(out, "encoding", None) or "utf-8"
        safe_bytes = text.encode(target_encoding, errors="backslashreplace")
        safe_str = safe_bytes.decode(target_encoding, errors="replace")
        try:
            out.write(safe_str)
        except Exception:
            # Last resort ascii
            out.write(text.encode("ascii", errors="replace").decode("ascii"))
    except Exception:
        # Avoid crashing application if stdout/stderr was closed
        pass

    if flush:
        try:
            out.flush()
        except Exception:
            pass


def resolve_path(path_str: Union[str, Path]) -> Path:
    """Resolve a filesystem path expanding user tilde and environment variables.

    Args:
        path_str: Path string or Path object.

    Returns:
        Fully resolved Path object.
    """
    if isinstance(path_str, Path):
        expanded = os.path.expanduser(os.path.expandvars(str(path_str)))
    else:
        expanded = os.path.expanduser(os.path.expandvars(str(path_str)))
    return Path(expanded).resolve()


def to_posix_path(path_or_str: Union[str, Path]) -> str:
    """Convert any Windows or POSIX path to normalized forward-slash POSIX format.

    Args:
        path_or_str: File or directory path.

    Returns:
        Forward-slash formatted string path.
    """
    if isinstance(path_or_str, Path):
        return path_or_str.as_posix()
    p = str(path_or_str).replace("\\", "/")
    return p


def atomic_write_text(file_path: Union[str, Path], content: str, encoding: str = "utf-8") -> Path:
    """Atomically write text content to a file via a temporary file and atomic replace.

    Ensures that partial or crashed writes never leave corrupt files on disk.
    Automatically creates parent directories if they do not exist.

    Args:
        file_path: Target destination path.
        content: String content to write.
        encoding: File character encoding (default utf-8).

    Returns:
        Resolved Path to the written file.
    """
    target = resolve_path(file_path)
    parent_dir = target.parent
    parent_dir.mkdir(parents=True, exist_ok=True)

    # Use NamedTemporaryFile in the same directory to guarantee same-filesystem atomic rename
    temp_file = tempfile.NamedTemporaryFile(
        mode="w",
        encoding=encoding,
        dir=parent_dir,
        delete=False,
        prefix=f".tmp_{target.stem}_",
        suffix=".tmp",
    )
    temp_path = Path(temp_file.name)

    try:
        temp_file.write(content)
        temp_file.flush()
        os.fsync(temp_file.fileno())
        temp_file.close()

        # Atomic replacement
        os.replace(temp_path, target)
        return target
    except Exception as exc:
        temp_file.close()
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        raise exc


def open_browser(url_or_path: str) -> bool:
    """Open a URL or local HTML file in the default browser across all supported OSs.

    Supports:
      - Termux Android (via termux-open-url / termux-open)
      - macOS (via open command)
      - Windows (via os.startfile / start command)
      - Linux (via xdg-open)
      - Python webbrowser stdlib module fallback

    Args:
        url_or_path: Web URL (http://, https://) or local filesystem file path.

    Returns:
        True if browser invocation succeeded without error, False otherwise.
    """
    target = url_or_path.strip()
    if not target:
        return False

    # Check if this is a local file path
    if not (target.startswith("http://") or target.startswith("https://") or target.startswith("file://")):
        local_path = Path(target).expanduser().resolve()
        if local_path.exists():
            target = local_path.as_uri()

    # 1. Termux Android
    if is_termux():
        for cmd in ("termux-open-url", "termux-open"):
            if shutil.which(cmd):
                try:
                    proc = subprocess.Popen(
                        [cmd, target],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    return True
                except Exception:
                    pass

    # 2. macOS
    if is_macos():
        if shutil.which("open"):
            try:
                proc = subprocess.Popen(
                    ["open", target],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return True
            except Exception:
                pass

    # 3. Windows
    if is_windows():
        if hasattr(os, "startfile"):
            try:
                os.startfile(target)
                return True
            except Exception:
                pass
        try:
            subprocess.Popen(
                ["cmd", "/c", "start", "", target],
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception:
            pass

    # 4. Standard Linux / Unix with xdg-open
    if shutil.which("xdg-open"):
        try:
            subprocess.Popen(
                ["xdg-open", target],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception:
            pass

    # 5. Standard library fallback
    try:
        return webbrowser.open(target)
    except Exception:
        return False


def get_platform_info() -> Dict[str, Any]:
    """Retrieve detailed platform and operating system metadata.

    Returns:
        Dict containing platform name, release, python version, OS flags, and default encodings.
    """
    sys_name = platform.system()
    termux_active = is_termux()

    if termux_active:
        os_name = "Android (Termux)"
    elif sys_name == "Darwin":
        os_name = "macOS"
    elif sys_name == "Windows":
        os_name = "Windows"
    elif sys_name == "Linux":
        os_name = "Linux"
    else:
        os_name = sys_name or "Unknown"

    return {
        "os_name": os_name,
        "system": sys_name,
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "is_termux": termux_active,
        "is_windows": is_windows(),
        "is_macos": is_macos(),
        "is_linux": is_linux(),
        "default_encoding": sys.getdefaultencoding(),
        "filesystem_encoding": sys.getfilesystemencoding(),
        "path_separator": os.sep,
    }
