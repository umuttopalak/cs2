import ctypes
import ctypes.wintypes

kernel32 = ctypes.windll.kernel32

TH32CS_SNAPMODULE = 0x00000008

class MODULEENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_uint32),
        ("th32ModuleID", ctypes.c_uint32),
        ("th32ProcessID", ctypes.c_uint32),
        ("GlblcntUsage", ctypes.c_uint32),
        ("ProccntUsage", ctypes.c_uint32),
        ("modBaseAddr", ctypes.c_uint64),
        ("modBaseSize", ctypes.c_uint32),
        ("hModule", ctypes.c_void_p),
        ("szModule", ctypes.c_char * 256),
        ("szExePath", ctypes.c_char * 260),
    ]

pid = 20116  # senin PID'in

snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE, pid)
if snapshot == ctypes.c_void_p(-1).value:
    print(f"Snapshot alınamadı! Hata: {ctypes.GetLastError()}")
else:
    me = MODULEENTRY32()
    me.dwSize = ctypes.sizeof(MODULEENTRY32)
    
    count = 0
    if kernel32.Module32First(snapshot, ctypes.byref(me)):
        while True:
            mod_name = me.szModule.decode("utf-8", errors="ignore")
            mod_path = me.szExePath.decode("utf-8", errors="ignore")
            base = me.modBaseAddr
            print(f"[{count}] {mod_name:30s} -> 0x{base:016X}")
            
            if "client" in mod_name.lower():
                print(f"    *** BULUNDU! ***")
            
            count += 1
            if not kernel32.Module32Next(snapshot, ctypes.byref(me)):
                break
    
    kernel32.CloseHandle(snapshot)
    print(f"\nToplam modül: {count}")
    
    if count == 0:
        print("Modül listesi boş! Yönetici olarak çalıştırdığına emin misin?")