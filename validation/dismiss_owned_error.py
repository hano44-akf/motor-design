import ctypes
from ctypes import wintypes
u=ctypes.windll.user32
u.SendMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
cb=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
def child(h,p):
 b=ctypes.create_unicode_buffer(100);u.GetWindowTextW(h,b,100)
 if b.value=='OK':u.SendMessageW(h,0xF5,0,0)
 return True
def top(h,p):
 pid=wintypes.DWORD();u.GetWindowThreadProcessId(h,ctypes.byref(pid));b=ctypes.create_unicode_buffer(100);u.GetWindowTextW(h,b,100)
 if pid.value==22412 and b.value=='Error' and u.IsWindowVisible(h):u.EnumChildWindows(h,cb(child),0)
 return True
u.EnumWindows(cb(top),0)
