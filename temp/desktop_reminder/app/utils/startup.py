"""'Start with Windows' via the per-user Run key (HKCU) - no admin rights needed."""
import logging
import sys
from pathlib import Path
from typing import Optional

try:
    import winreg  # type: ignore
except ImportError:  # pragma: no cover - non-Windows
    winreg = None

log = logging.getLogger(__name__)
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "DesktopReminder"


def build_command(root: Path, python_exe: Optional[str] = None) -> str:
    """Command line registered at login. Prefers pythonw.exe so no console appears."""
    exe = Path(python_exe or sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    if pythonw.exists():
        exe = pythonw
    return '"%s" "%s"' % (exe, Path(root) / "run.py")


def is_enabled() -> bool:
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
            return True
    except OSError:
        return False


def set_enabled(enabled: bool, root: Path) -> bool:
    """Returns True on success. Never raises."""
    if winreg is None:
        log.warning("Start-with-Windows is only supported on Windows")
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, build_command(root))
            else:
                try:
                    winreg.DeleteValue(key, VALUE_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        log.exception("Could not update the Windows startup entry")
        return False
