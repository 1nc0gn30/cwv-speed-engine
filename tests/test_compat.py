"""Comprehensive test suite for compat.py multi-OS module."""

from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from cwv_speed_engine.compat import (
    atomic_write_text,
    configure_utf8_streams,
    get_platform_info,
    is_linux,
    is_macos,
    is_termux,
    is_windows,
    open_browser,
    resolve_path,
    safe_print,
    to_posix_path,
)


def test_configure_utf8_streams():
    """Ensure configure_utf8_streams runs safely without crashing."""
    configure_utf8_streams()

    # Test with mock stream
    mock_stdout = MagicMock()
    with patch.object(sys, "stdout", mock_stdout):
        configure_utf8_streams()
        mock_stdout.reconfigure.assert_called_once_with(encoding="utf-8", errors="replace")


def test_safe_print_basic():
    """Test safe_print with custom StringIO file."""
    buf = io.StringIO()
    safe_print("Hello", "CWV", 100, sep="|", end="!\n", file=buf, flush=True)
    assert buf.getvalue() == "Hello|CWV|100!\n"


def test_safe_print_unicode_resilience():
    """Test safe_print handling when stream raises UnicodeEncodeError."""
    class StrictStream:
        def __init__(self):
            self.written = []
            self.encoding = "ascii"

        def write(self, s: str):
            if any(ord(c) > 127 for c in s):
                raise UnicodeEncodeError("ascii", s, 0, 1, "ordinal not in range")
            self.written.append(s)

        def flush(self):
            pass

    stream = StrictStream()
    safe_print("Fast 🚀 Speed", file=stream)
    assert len(stream.written) > 0


def test_atomic_write_text(tmp_path: Path):
    """Test atomic file writing and parent dir creation."""
    target = tmp_path / "deep" / "nested" / "output.txt"
    content = "Core Web Vitals Test Content 🚀"

    written = atomic_write_text(target, content)
    assert written == target
    assert target.exists()
    assert target.read_text(encoding="utf-8") == content

    # Overwrite test
    new_content = "Updated content"
    atomic_write_text(target, new_content)
    assert target.read_text(encoding="utf-8") == new_content


def test_resolve_path():
    """Test path resolution with env var expansion."""
    os.environ["CWV_TEST_DIR"] = "speed_test"
    p = resolve_path("$CWV_TEST_DIR/subfolder")
    assert "speed_test" in str(p)
    assert p.is_absolute()


def test_to_posix_path():
    """Test converting Windows or mixed paths to POSIX."""
    assert to_posix_path("src\\cwv\\analyzer.py") == "src/cwv/analyzer.py"
    assert to_posix_path(Path("src/cwv/analyzer.py")) == "src/cwv/analyzer.py"


def test_open_browser_empty():
    """Empty target returns False."""
    assert open_browser("") is False
    assert open_browser("   ") is False


def test_open_browser_mocked():
    """Test open_browser with mocked subprocess/webbrowser."""
    with patch("webbrowser.open", return_value=True) as mock_web:
        with patch("shutil.which", return_value=None):
            res = open_browser("https://example.com")
            assert res is True
            mock_web.assert_called_once_with("https://example.com")


def test_open_browser_local_file(tmp_path: Path):
    """Test open_browser with existing local file."""
    test_file = tmp_path / "preview.html"
    test_file.write_text("<h1>Preview</h1>", encoding="utf-8")

    with patch("webbrowser.open", return_value=True) as mock_web:
        with patch("shutil.which", return_value=None):
            res = open_browser(str(test_file))
            assert res is True
            assert mock_web.called
            called_arg = mock_web.call_args[0][0]
            assert called_arg.startswith("file://")


def test_open_browser_platform_subprocesses():
    """Test open_browser subprocess dispatch across platforms."""
    # Test Linux xdg-open
    with patch("cwv_speed_engine.compat.is_linux", return_value=True), \
         patch("cwv_speed_engine.compat.is_termux", return_value=False), \
         patch("cwv_speed_engine.compat.is_macos", return_value=False), \
         patch("cwv_speed_engine.compat.is_windows", return_value=False), \
         patch("shutil.which", return_value="/usr/bin/xdg-open"), \
         patch("subprocess.Popen") as mock_popen:
        assert open_browser("https://example.com") is True
        mock_popen.assert_called_once()

    # Test macOS open
    with patch("cwv_speed_engine.compat.is_linux", return_value=False), \
         patch("cwv_speed_engine.compat.is_termux", return_value=False), \
         patch("cwv_speed_engine.compat.is_macos", return_value=True), \
         patch("cwv_speed_engine.compat.is_windows", return_value=False), \
         patch("shutil.which", return_value="/usr/bin/open"), \
         patch("subprocess.Popen") as mock_popen:
        assert open_browser("https://example.com") is True
        mock_popen.assert_called_once()


def test_platform_info_and_flags():
    """Test platform detection metadata and boolean flags."""
    info = get_platform_info()
    assert isinstance(info, dict)
    assert "os_name" in info
    assert "system" in info
    assert "python_version" in info
    assert "is_termux" in info
    assert "is_windows" in info
    assert "is_macos" in info
    assert "is_linux" in info

    # Consistency checks
    assert isinstance(is_termux(), bool)
    assert isinstance(is_windows(), bool)
    assert isinstance(is_macos(), bool)
    assert isinstance(is_linux(), bool)


def test_atomic_write_text_error_cleanup(tmp_path: Path):
    """Test atomic write cleans up temp file if write fails."""
    target = tmp_path / "broken.txt"

    with patch("os.fsync", side_effect=OSError("Disk write failed")):
        with pytest.raises(OSError):
            atomic_write_text(target, "some data")

    assert not target.exists()
    # Ensure no leftover temporary files in dir
    temp_files = list(tmp_path.glob(".tmp_*"))
    assert len(temp_files) == 0
