"""Windows SendInput — vpis v že odprt Chrome (brez CDP / vtičnika)."""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
SW_RESTORE = 9
VK_TAB = 0x09
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_DOWN = 0x28
VK_A = 0x41
VK_F4 = 0x73

ULONG_PTR = ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = (
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    )


class MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    )


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = (
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    )


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = (("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT))

    _anonymous_ = ("u",)
    _fields_ = (("type", wintypes.DWORD), ("u", _U))


def _send(inp: INPUT) -> None:
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def _vk(vk: int, *, up: bool = False) -> None:
    flags = KEYEVENTF_KEYUP if up else 0
    ev = INPUT(type=INPUT_KEYBOARD)
    ev.ki = KEYBDINPUT(vk, 0, flags, 0, 0)
    _send(ev)


def press_tab() -> None:
    _vk(VK_TAB)
    time.sleep(0.02)
    _vk(VK_TAB, up=True)
    time.sleep(0.28)


def press_enter() -> None:
    _vk(VK_RETURN)
    time.sleep(0.02)
    _vk(VK_RETURN, up=True)
    time.sleep(0.25)


def press_down() -> None:
    _vk(VK_DOWN)
    time.sleep(0.02)
    _vk(VK_DOWN, up=True)
    time.sleep(0.18)


def press_alt_down() -> None:
    _vk(VK_MENU)
    time.sleep(0.02)
    _vk(VK_DOWN)
    time.sleep(0.02)
    _vk(VK_DOWN, up=True)
    _vk(VK_MENU, up=True)
    time.sleep(0.4)


def press_f4() -> None:
    _vk(VK_F4)
    time.sleep(0.03)
    _vk(VK_F4, up=True)
    time.sleep(0.45)


def press_escape() -> None:
    _vk(VK_ESCAPE)
    time.sleep(0.02)
    _vk(VK_ESCAPE, up=True)
    time.sleep(0.12)


def press_ctrl_a() -> None:
    _vk(VK_CONTROL)
    time.sleep(0.02)
    _vk(VK_A)
    time.sleep(0.02)
    _vk(VK_A, up=True)
    _vk(VK_CONTROL, up=True)
    time.sleep(0.08)


def type_text(text: str) -> None:
    for ch in str(text or ""):
        if ch in "\r\n":
            continue
        ev_down = INPUT(type=INPUT_KEYBOARD)
        ev_down.ki = KEYBDINPUT(0, ord(ch), KEYEVENTF_UNICODE, 0, 0)
        ev_up = INPUT(type=INPUT_KEYBOARD)
        ev_up.ki = KEYBDINPUT(0, ord(ch), KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, 0)
        _send(ev_down)
        _send(ev_up)
        time.sleep(0.018)
    time.sleep(0.12)


def replace_text(text: str) -> None:
    press_ctrl_a()
    type_text(text)


def list_windows() -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd: int, _lp: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value.strip()
        if title:
            found.append((int(hwnd), title))
        return True

    user32.EnumWindows(_cb, 0)
    return found


def find_os_edit_window() -> tuple[int, str] | None:
    ranked: list[tuple[int, int, str]] = []
    for hwnd, title in list_windows():
        low = title.casefold()
        if "osnovna sredstva" in low or "osnovnosredstvo" in low:
            ranked.append((0, hwnd, title))
        elif "minimax" in low and "chrome" in low:
            ranked.append((1, hwnd, title))
        elif "minimax" in low:
            ranked.append((2, hwnd, title))
    if not ranked:
        return None
    ranked.sort(key=lambda row: row[0])
    return ranked[0][1], ranked[0][2]


def focus_window(hwnd: int) -> bool:
    if not hwnd:
        return False
    try:
        user32.AllowSetForegroundWindow(-1)
    except Exception:
        pass
    user32.ShowWindow(hwnd, SW_RESTORE)
    fg = user32.GetForegroundWindow()
    if fg == hwnd:
        return True
    fg_tid = user32.GetWindowThreadProcessId(fg, None)
    cur_tid = kernel32.GetCurrentThreadId()
    user32.AttachThreadInput(cur_tid, fg_tid, True)
    user32.BringWindowToTop(hwnd)
    ok = bool(user32.SetForegroundWindow(hwnd))
    user32.AttachThreadInput(cur_tid, fg_tid, False)
    time.sleep(0.35)
    return ok or user32.GetForegroundWindow() == hwnd
