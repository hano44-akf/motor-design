import ctypes
from ctypes import wintypes
u=ctypes.windll.user32
callback=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
def text(h):
 b=ctypes.create_unicode_buffer(4096);u.GetWindowTextW(h,b,4096);return b.value
def child(h,p):
 t=text(h)
 if t: print('  '+t)
 return True
def top(h,p):
 pid=wintypes.DWORD();u.GetWindowThreadProcessId(h,ctypes.byref(pid))
 if pid.value==22412:
  print('WINDOW',text(h),'visible',bool(u.IsWindowVisible(h)))
  u.EnumChildWindows(h,callback(child),0)
 return True
u.EnumWindows(callback(top),0)
