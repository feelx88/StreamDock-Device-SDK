from base_handler import BaseHandler
import os
import sys
import dbus

CMD = 'cmd'


# Module-level ctypes cursor structs, defined ONCE (see _wake_display).
#
# These were previously declared inside _wake_display()'s Windows branch, so
# every unlock call rebuilt MOUSEINPUT/INPUTUNION/INPUT from scratch. They are
# pure ctypes type definitions — no dependencies, no side effects — so they are
# hoisted here to module scope: each is created exactly one time at import and
# reused on every wake. Defining a class is not free at runtime, and doing it on
# every method call is wasteful, so we deliberately moved the class definitions
# out of the function and into a single, inner-class module-level definition.
import ctypes
from ctypes import wintypes


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ('dx', wintypes.LONG),
        ('dy', wintypes.LONG),
        ('mouseData', wintypes.DWORD),
        ('dwFlags', wintypes.DWORD),
        ('time', wintypes.DWORD),
        ('dwExtraInfo', ctypes.POINTER(wintypes.ULONG)),
    ]


class INPUTUNION(ctypes.Union):
    _fields_ = [('mi', MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [('type', wintypes.DWORD), ('u', INPUTUNION)]


def _run(cmdline):
    """Run a shell command, ignoring failures and non-zero exits."""
    try:
        os.system(cmdline)
    except Exception:
        pass


def _wake_display():
    """Cursor-movement-only wake of a sleeping/blanked display, cross-platform.

    Everything that is NOT a synthetic mouse-cursor movement has been removed
    on purpose: no `xset dpms force on`, no `wlopm --on`, no `caffeinate -u`,
    and no `SetThreadExecutionState` — only a tiny synthetic cursor nudge
    remains. That is the one truly universal wake primitive: any pointer
    activity re-enables a blanked/DPMS panel on every OS, needs no pip library,
    and dispatches to whatever the platform already ships.

    Every call is wrapped in try/except and non-zero exits ignored: on unlock
    the nudge is best-effort, and if the display is already awake these all
    no-op.

    The ctypes INPUT/MOUSEINPUT structs are module-level (defined once above),
    not re-built here, so this stays lean on each call.
    """
    plat = sys.platform.lower()

    if plat.startswith('linux'):
        # X11: xdotool relative move 1,0 then back.
        _run('xdotool mousemove_relative 1 0 >/dev/null 2>&1 && '
             'xdotool mousemove_relative -- -1 0 >/dev/null 2>&1')
        # Wayland (wlroots compositors); a uinput/ydotool cursor nudge.
        _run('ydotool mousemove 1 0 >/dev/null 2>&1 && '
             'ydotool mousemove -- -1 0 >/dev/null 2>&1')
    elif plat.startswith('darwin'):
        # cliclick: macOS synthetic-cursor CLI — move +1,0 then back.
        _run('cliclick m:+1,0 >/dev/null 2>&1 && '
             'cliclick m:-1,0 >/dev/null 2>&1')
    elif plat.startswith('win'):
        # SendInput MOUSEEVENTF_MOVE using the module-level INPUT struct.
        try:
            inp = INPUT()
            inp.type = 0               # INPUT_MOUSE
            inp.u.mi.dwFlags = 0x0001  # MOUSEEVENTF_MOVE
            inp.u.mi.dx = 1
            inp.u.mi.dy = 0
            ctypes.windll.user32.SendInput(
                1, ctypes.byref(inp), ctypes.sizeof(inp))

            inp.u.mi.dx = -1
            ctypes.windll.user32.SendInput(
                1, ctypes.byref(inp), ctypes.sizeof(inp))
        except Exception:
            pass


class LoginCtlHandler(BaseHandler):

    def __init__(self, cmd_lock):
        super().__init__({
            CMD: cmd_lock,
        })
        self.session_bus = dbus.SessionBus()

    def toggle_lock(self):

        def locked():
            screensaver_active = self.session_bus.get_object(
                'org.freedesktop.ScreenSaver', '/ScreenSaver').get_dbus_method('GetActive')

            return screensaver_active()

        def cmd():
            with self._acquire_timeout(CMD):
                if locked():
                    os.system('loginctl unlock-session')
                    _wake_display()
                else:
                    os.system('loginctl lock-session')

        return (
            lambda: cmd(),
            lambda: 'images/locked.png' if locked() else 'images/unlocked.png'
        )
