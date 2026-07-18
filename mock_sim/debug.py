import ctypes
import ctypes.wintypes

# Debug için
print("[*] CS2 Process aranıyor...")

# Daha basit bir process bulma yöntemi
from ctypes import wintypes

# EnumWindows ile dene
EnumWindows = ctypes.windll.user32.EnumWindows
GetWindowThreadProcessId = ctypes.windll.user32.GetWindowThreadProcessId

cs2_pids = []
def enum_proc(hwnd, lParam):
    pid = wintypes.DWORD()
    GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    # Pencere başlığını kontrol et
    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
    if length:
        title = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, title, length + 1)
        if "Counter-Strike" in title.value or "CS2" in title.value:
            print(f"CS2 Pencere bulundu: PID={pid.value}, Title={title.value}")
            cs2_pids.append(pid.value)
    return True

WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
EnumWindows(WNDENUMPROC(enum_proc), 0)

if cs2_pids:
    print(f"CS2 PID(ler)i: {cs2_pids}")
else:
    print("[!] CS2 penceresi bulunamadı!")