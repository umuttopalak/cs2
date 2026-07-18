import ctypes
import ctypes.wintypes

# Gerekli yapılar
kernel32 = ctypes.windll.kernel32
psapi = ctypes.windll.psapi

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400

pid = 20116  # Senin PID'in

# Process'i aç
handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
if not handle:
    print(f"OpenProcess hatası: {ctypes.GetLastError()}")
else:
    print(f"Process açıldı: {handle}")
    
    # Modülleri listele
    cb_needed = ctypes.wintypes.DWORD()
    h_mods = (ctypes.c_void_p * 1024)()  # 1024 modül kapasite
    
    if psapi.EnumProcessModules(handle, ctypes.byref(h_mods), ctypes.sizeof(h_mods), ctypes.byref(cb_needed)):
        mod_count = cb_needed.value // ctypes.sizeof(ctypes.c_void_p)
        print(f"Toplam modül: {mod_count}")
        
        for i in range(mod_count):
            mod_name = ctypes.create_unicode_buffer(256)
            mod_path = ctypes.create_unicode_buffer(260)
            
            if psapi.GetModuleBaseNameW(handle, h_mods[i], mod_name, 256):
                psapi.GetModuleFileNameExW(handle, h_mods[i], mod_path, 260)
                
                print(f"[{i}] {mod_name.value:30s} 0x{h_mods[i]:016X}")
                
                if "client" in mod_name.value.lower():
                    print(f"    * client BULUNDU! Base: 0x{h_mods[i]:016X} *")
    else:
        print(f"EnumProcessModules hatası: {ctypes.GetLastError()}")
    
    kernel32.CloseHandle(handle)