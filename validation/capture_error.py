import ctypes
from ctypes import wintypes
from pathlib import Path
from PIL import Image
u=ctypes.windll.user32
u.SetProcessDPIAware()
cb=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
def f(h,p):
 pid=wintypes.DWORD();u.GetWindowThreadProcessId(h,ctypes.byref(pid))
 b=ctypes.create_unicode_buffer(300);u.GetWindowTextW(h,b,300)
 if pid.value==22412 and b.value=='Error' and u.IsWindowVisible(h):
  r=wintypes.RECT();u.GetWindowRect(h,ctypes.byref(r))
  w,ht=r.right-r.left,r.bottom-r.top
  g=ctypes.windll.gdi32
  u.GetWindowDC.restype=wintypes.HDC
  g.CreateCompatibleDC.restype=wintypes.HDC
  g.CreateCompatibleBitmap.restype=wintypes.HBITMAP
  g.SelectObject.restype=wintypes.HANDLE
  g.SelectObject.argtypes=[wintypes.HDC,wintypes.HANDLE]
  g.CreateCompatibleDC.argtypes=[wintypes.HDC]
  g.CreateCompatibleBitmap.argtypes=[wintypes.HDC,ctypes.c_int,ctypes.c_int]
  u.GetWindowDC.argtypes=[wintypes.HWND]
  u.PrintWindow.argtypes=[wintypes.HWND,wintypes.HDC,wintypes.UINT]
  g.GetDIBits.argtypes=[wintypes.HDC,wintypes.HBITMAP,wintypes.UINT,wintypes.UINT,ctypes.c_void_p,ctypes.c_void_p,wintypes.UINT]
  g.DeleteObject.argtypes=[wintypes.HANDLE]
  g.DeleteDC.argtypes=[wintypes.HDC]
  u.ReleaseDC.argtypes=[wintypes.HWND,wintypes.HDC]
  dc=u.GetWindowDC(h);mdc=g.CreateCompatibleDC(dc);bmp=g.CreateCompatibleBitmap(dc,w,ht);old=g.SelectObject(mdc,bmp)
  u.PrintWindow(h,mdc,2)
  class BI(ctypes.Structure):
   _fields_=[('size',wintypes.DWORD),('width',wintypes.LONG),('height',wintypes.LONG),('planes',wintypes.WORD),('bits',wintypes.WORD),('compression',wintypes.DWORD),('imagesize',wintypes.DWORD),('x',wintypes.LONG),('y',wintypes.LONG),('used',wintypes.DWORD),('important',wintypes.DWORD)]
  info=BI(40,w,-ht,1,32,0,0,0,0,0,0);buf=ctypes.create_string_buffer(w*ht*4)
  g.GetDIBits(mdc,bmp,0,ht,buf,ctypes.byref(info),0)
  Image.frombuffer('RGB',(w,ht),buf.raw,'raw','BGRX',0,1).save(Path(__file__).with_name('startup_error.png'))
  g.SelectObject(mdc,old);g.DeleteObject(bmp);g.DeleteDC(mdc);u.ReleaseDC(h,dc)
 return True
u.EnumWindows(cb(f),0)

