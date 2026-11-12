"""
Win32 命名互斥量单例运行守护与已有窗口唤醒置顶
遵循 python-exe-build 规范，包含 64 位指针与句柄严格类型声明
"""
import sys
import ctypes

if sys.platform == "win32":
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32

    # 声明 kernel32 API 类型，防范 64 位 HANDLE / DWORD 截断
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE

    kernel32.GetLastError.argtypes = []
    kernel32.GetLastError.restype = wintypes.DWORD

    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD

    # 声明 user32 API 类型，防范 64 位 HWND 截断
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND

    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL

    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND

    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD

    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user32.AttachThreadInput.restype = wintypes.BOOL

    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.restype = wintypes.BOOL

    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL


class SingleInstanceGuard:
    def __init__(self, mutex_name: str):
        self.mutex_name = mutex_name
        self.mutex_handle = None
        self.is_running = False

        if sys.platform == "win32":
            ERROR_ALREADY_EXISTS = 183
            self.mutex_handle = kernel32.CreateMutexW(None, False, self.mutex_name)
            last_err = kernel32.GetLastError()
            if last_err == ERROR_ALREADY_EXISTS:
                self.is_running = True

    def is_already_running(self) -> bool:
        return self.is_running

    def restore_and_activate_existing_window(self, window_title: str):
        """寻找已有主窗口并穿透前台锁恢复置顶"""
        if sys.platform != "win32":
            return
        try:
            hwnd = user32.FindWindowW(None, window_title)
            if not hwnd:
                return

            SW_RESTORE = 9
            user32.ShowWindow(hwnd, SW_RESTORE)

            # 穿透 Windows 前台窗口激活锁机制
            foreground_hwnd = user32.GetForegroundWindow()
            foreground_thread = user32.GetWindowThreadProcessId(foreground_hwnd, None)
            app_thread = kernel32.GetCurrentThreadId()

            if foreground_thread and foreground_thread != app_thread:
                user32.AttachThreadInput(foreground_thread, app_thread, True)
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
                user32.AttachThreadInput(foreground_thread, app_thread, False)
            else:
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
        except Exception:
            pass
