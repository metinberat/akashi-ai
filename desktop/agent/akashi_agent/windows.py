"""Bounded native Windows perception and input primitives.

This module deliberately exposes typed operations rather than a generic shell or
an arbitrary executable path.  Every mutating operation returns a fresh desktop
observation so callers can distinguish "input was sent" from "the requested UI
state was actually observed".
"""
from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from typing import Any, Dict, List, Optional, Sequence


class WindowsDesktopError(RuntimeError):
    pass


if sys.platform == "win32":
    user32 = ctypes.WinDLL("user32", use_last_error=True)

    ULONG_PTR = wintypes.WPARAM

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]


    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]


    class INPUT_UNION(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


    class INPUT(ctypes.Structure):
        _anonymous_ = ("value",)
        _fields_ = [("type", wintypes.DWORD), ("value", INPUT_UNION)]


    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.LONG),
        ]


    class POINT(ctypes.Structure):
        _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x01000
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
SW_HIDE = 0
SW_SHOWNORMAL = 1
SW_SHOWMINIMIZED = 2
SW_SHOWMAXIMIZED = 3
SW_RESTORE = 9
WM_CLOSE = 0x0010

_BUTTON_FLAGS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}
_KEYS = {
    "backspace": 0x08,
    "tab": 0x09,
    "enter": 0x0D,
    "shift": 0x10,
    "ctrl": 0x11,
    "control": 0x11,
    "alt": 0x12,
    "pause": 0x13,
    "capslock": 0x14,
    "escape": 0x1B,
    "esc": 0x1B,
    "space": 0x20,
    "pageup": 0x21,
    "pagedown": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "insert": 0x2D,
    "delete": 0x2E,
}
for _number in range(10):
    _KEYS[str(_number)] = 0x30 + _number
for _offset, _letter in enumerate("abcdefghijklmnopqrstuvwxyz"):
    _KEYS[_letter] = 0x41 + _offset
for _number in range(1, 13):
    _KEYS[f"f{_number}"] = 0x6F + _number


def _require_windows() -> None:
    if sys.platform != "win32":
        raise WindowsDesktopError("Native desktop control is available only on Windows.")


def _virtual_screen() -> Dict[str, int]:
    _require_windows()
    return {
        "x": int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN)),
        "y": int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN)),
        "width": int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)),
        "height": int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)),
    }


def _send(inputs: Sequence["INPUT"]) -> None:
    _require_windows()
    array_type = INPUT * len(inputs)
    sent = user32.SendInput(len(inputs), array_type(*inputs), ctypes.sizeof(INPUT))
    if sent != len(inputs):
        raise WindowsDesktopError("Windows rejected an input event.")


def _mouse_input(flags: int, x: int = 0, y: int = 0, data: int = 0) -> "INPUT":
    return INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(x, y, data, flags, 0, 0))


def _key_input(vk: int = 0, scan: int = 0, flags: int = 0) -> "INPUT":
    return INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(vk, scan, flags, 0, 0))


def _absolute_point(x: int, y: int) -> tuple[int, int]:
    bounds = _virtual_screen()
    if not (
        bounds["x"] <= x < bounds["x"] + bounds["width"]
        and bounds["y"] <= y < bounds["y"] + bounds["height"]
    ):
        raise ValueError("Pointer coordinates are outside the virtual desktop.")
    width = max(1, bounds["width"] - 1)
    height = max(1, bounds["height"] - 1)
    return (
        round((x - bounds["x"]) * 65535 / width),
        round((y - bounds["y"]) * 65535 / height),
    )


def _move_pointer(x: int, y: int) -> None:
    absolute_x, absolute_y = _absolute_point(x, y)
    _send([
        _mouse_input(
            MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
            absolute_x,
            absolute_y,
        )
    ])


def _press_virtual_key(vk: int, down: bool) -> None:
    _send([_key_input(vk=vk, flags=0 if down else KEYEVENTF_KEYUP)])


def _resolve_key(value: str) -> int:
    normalized = value.strip().casefold()
    if normalized in {"win", "windows", "meta", "super", "cmd", "command"}:
        raise ValueError("The Windows key is not exposed to remote actions.")
    key = _KEYS.get(normalized)
    if key is None:
        raise ValueError(f"Unsupported key '{value}'.")
    return key


def list_windows(limit: int = 100) -> Dict[str, Any]:
    """Return bounded real top-level window state and the current foreground."""
    _require_windows()
    foreground = int(user32.GetForegroundWindow() or 0)
    records: List[Dict[str, Any]] = []
    try:
        import psutil
    except ImportError:
        psutil = None  # type: ignore[assignment]

    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def callback(hwnd: int, _lparam: int) -> bool:
        if len(records) >= max(1, min(limit, 200)) or not user32.IsWindowVisible(hwnd):
            return True
        title_length = int(user32.GetWindowTextLengthW(hwnd))
        if title_length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(min(title_length + 1, 1025))
        user32.GetWindowTextW(hwnd, buffer, len(buffer))
        title = buffer.value.strip()
        if not title:
            return True
        rect = RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        client_rect = RECT()
        client_origin = POINT()
        has_client = bool(user32.GetClientRect(hwnd, ctypes.byref(client_rect))) and bool(
            user32.ClientToScreen(hwnd, ctypes.byref(client_origin))
        )
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process_name = "unknown"
        if psutil is not None:
            try:
                process_name = psutil.Process(pid.value).name()
            except (psutil.Error, OSError):
                pass
        records.append(
            {
                "window_id": int(hwnd),
                "title": title[:1000],
                "process_id": int(pid.value),
                "process_name": process_name[:260],
                "foreground": int(hwnd) == foreground,
                "minimized": bool(user32.IsIconic(hwnd)),
                "maximized": bool(user32.IsZoomed(hwnd)),
                "bounds": {
                    "x": int(rect.left),
                    "y": int(rect.top),
                    "width": max(0, int(rect.right - rect.left)),
                    "height": max(0, int(rect.bottom - rect.top)),
                },
                "client_bounds": {
                    "x": int(client_origin.x),
                    "y": int(client_origin.y),
                    "width": max(0, int(client_rect.right - client_rect.left)),
                    "height": max(0, int(client_rect.bottom - client_rect.top)),
                } if has_client else None,
            }
        )
        return True

    user32.EnumWindows(callback, 0)
    cursor = POINT()
    user32.GetCursorPos(ctypes.byref(cursor))
    return {
        "platform": "windows",
        "virtual_screen": _virtual_screen(),
        "cursor": {"x": int(cursor.x), "y": int(cursor.y)},
        "foreground_window_id": foreground or None,
        "windows": records,
    }


def _select_window(window_id: Optional[int], title: str) -> Dict[str, Any]:
    state = list_windows(200)
    windows = state["windows"]
    if window_id is not None:
        matches = [item for item in windows if item["window_id"] == window_id]
    else:
        query = title.strip().casefold()
        if not query:
            raise ValueError("window_id or a title fragment is required.")
        exact = [item for item in windows if item["title"].casefold() == query]
        matches = exact or [item for item in windows if query in item["title"].casefold()]
    if not matches:
        raise ValueError("The requested window is not open.")
    if len(matches) > 1:
        raise ValueError("Window title is ambiguous; use a window_id from get_desktop_state.")
    return matches[0]


def _focus_window(hwnd: int) -> bool:
    """Bring a known top-level window forward without invoking a shell."""
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    foreground = int(user32.GetForegroundWindow() or 0)
    target_thread = int(user32.GetWindowThreadProcessId(hwnd, None))
    foreground_thread = int(user32.GetWindowThreadProcessId(foreground, None)) if foreground else 0
    attached = False
    try:
        if target_thread and foreground_thread and target_thread != foreground_thread:
            attached = bool(user32.AttachThreadInput(foreground_thread, target_thread, True))
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetFocus(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(foreground_thread, target_thread, False)
    if int(user32.GetForegroundWindow() or 0) != hwnd:
        # Windows foreground-lock rules allow a process that has just received
        # user input to request focus. A neutral Alt press is the standard,
        # bounded fallback and does not invoke the shell or the Windows key.
        _press_virtual_key(_KEYS["alt"], True)
        _press_virtual_key(_KEYS["alt"], False)
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if int(user32.GetForegroundWindow() or 0) == hwnd:
            return True
        time.sleep(0.03)
    return False


def control_window(arguments: Dict[str, Any]) -> Dict[str, Any]:
    operation = str(arguments.get("operation") or "").strip().casefold()
    selected = _select_window(arguments.get("window_id"), str(arguments.get("title") or ""))
    hwnd = selected["window_id"]
    if operation == "focus":
        success = _focus_window(hwnd)
    elif operation in {"minimize", "maximize", "restore"}:
        command = {"minimize": SW_SHOWMINIMIZED, "maximize": SW_SHOWMAXIMIZED, "restore": SW_RESTORE}[operation]
        success = bool(user32.ShowWindow(hwnd, command))
    elif operation == "move":
        x = int(arguments.get("x"))
        y = int(arguments.get("y"))
        width = int(arguments.get("width"))
        height = int(arguments.get("height"))
        if width < 200 or height < 120 or width > 16_384 or height > 16_384:
            raise ValueError("Window dimensions are outside the safe range.")
        success = bool(user32.MoveWindow(hwnd, x, y, width, height, True))
    elif operation == "close":
        success = bool(user32.PostMessageW(hwnd, WM_CLOSE, 0, 0))
    else:
        raise ValueError("Unsupported window operation.")
    time.sleep(0.12)
    after = list_windows(200)
    current = next((item for item in after["windows"] if item["window_id"] == hwnd), None)
    verified = False
    if operation == "focus":
        verified = after["foreground_window_id"] == hwnd
    elif operation == "minimize":
        verified = bool(current and current["minimized"])
    elif operation == "maximize":
        verified = bool(current and current["maximized"])
    elif operation == "restore":
        verified = bool(current and not current["minimized"] and not current["maximized"])
    elif operation == "move":
        verified = bool(
            current
            and abs(current["bounds"]["x"] - int(arguments["x"])) <= 2
            and abs(current["bounds"]["y"] - int(arguments["y"])) <= 2
        )
    elif operation == "close":
        verified = current is None
    return {
        "operation": operation,
        "window": selected,
        "api_accepted": success,
        "verified": verified,
        "after": current,
        "foreground_window_id": after["foreground_window_id"],
    }


def computer_input(arguments: Dict[str, Any]) -> Dict[str, Any]:
    operation = str(arguments.get("operation") or "").strip().casefold()
    before = list_windows(100)
    before_foreground = before["foreground_window_id"]
    if operation in {"click", "double_click", "right_click", "move"}:
        x, y = int(arguments.get("x")), int(arguments.get("y"))
        _move_pointer(x, y)
        if operation != "move":
            button = "right" if operation == "right_click" else str(arguments.get("button") or "left").casefold()
            if button not in _BUTTON_FLAGS:
                raise ValueError("Unsupported mouse button.")
            count = 2 if operation == "double_click" else 1
            down, up = _BUTTON_FLAGS[button]
            for _ in range(count):
                _send([_mouse_input(down), _mouse_input(up)])
                if count > 1:
                    time.sleep(0.06)
    elif operation == "drag":
        x, y = int(arguments.get("x")), int(arguments.get("y"))
        x2, y2 = int(arguments.get("x2")), int(arguments.get("y2"))
        _move_pointer(x, y)
        _send([_mouse_input(MOUSEEVENTF_LEFTDOWN)])
        steps = max(2, min(30, int(arguments.get("steps", 12))))
        try:
            for index in range(1, steps + 1):
                _move_pointer(round(x + (x2 - x) * index / steps), round(y + (y2 - y) * index / steps))
                time.sleep(0.01)
        finally:
            _send([_mouse_input(MOUSEEVENTF_LEFTUP)])
    elif operation == "scroll":
        delta = max(-10_000, min(10_000, int(arguments.get("delta", 0))))
        if delta == 0:
            raise ValueError("Scroll delta must be non-zero.")
        horizontal = bool(arguments.get("horizontal", False))
        _send([_mouse_input(MOUSEEVENTF_HWHEEL if horizontal else MOUSEEVENTF_WHEEL, data=delta & 0xFFFFFFFF)])
    elif operation == "type_text":
        text = str(arguments.get("text") or "")
        if not text or len(text) > 4000:
            raise ValueError("Text must contain 1-4000 characters.")
        encoded = text.encode("utf-16-le")
        events: List[INPUT] = []
        for index in range(0, len(encoded), 2):
            unit = int.from_bytes(encoded[index:index + 2], "little")
            events.extend((
                _key_input(scan=unit, flags=KEYEVENTF_UNICODE),
                _key_input(scan=unit, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP),
            ))
        for start in range(0, len(events), 128):
            _send(events[start:start + 128])
    elif operation in {"press_key", "shortcut"}:
        keys = arguments.get("keys")
        if isinstance(keys, str):
            values = [part for part in keys.split("+") if part.strip()]
        elif isinstance(keys, list) and all(isinstance(item, str) for item in keys):
            values = list(keys)
        else:
            raise ValueError("keys must be a key name or a bounded key list.")
        if not values or len(values) > 5:
            raise ValueError("Use between one and five keys.")
        resolved = [_resolve_key(value) for value in values]
        if {0x11, 0x12, 0x2E}.issubset(set(resolved)):
            raise ValueError("Ctrl+Alt+Delete is not exposed.")
        for key in resolved:
            _press_virtual_key(key, True)
        for key in reversed(resolved):
            _press_virtual_key(key, False)
    else:
        raise ValueError("Unsupported computer input operation.")
    time.sleep(0.08)
    after = list_windows(100)
    return {
        "operation": operation,
        "input_sent": True,
        "foreground_before": before_foreground,
        "foreground_after": after["foreground_window_id"],
        "foreground_stable": before_foreground == after["foreground_window_id"],
        "cursor_after": after["cursor"],
        # This is intentionally not named success: semantic UI success requires
        # a subsequent observation/vision verification by the computer loop.
        "requires_visual_verification": operation not in {"move"},
    }

