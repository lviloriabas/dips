r"""¿Hay que esperar una tecla al terminar un .bat?

Sí solo si el .bat se abrió desde el Explorador (arrastrar el Excel o doble clic): la ventana
se cierra al terminar y no se alcanza a leer el resultado. Desde una consola ya abierta, no.
Uso en el .bat: python "%RAIZ%dips_audit\pausa.py" && pause   (sale con 0 si hay que pausar)
"""

import ctypes
import os
import sys
from ctypes import wintypes


class _Proceso(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]


def _procesos() -> dict[int, tuple[int, str]]:
    """{pid: (pid del padre, nombre del ejecutable)} de todos los procesos."""
    k = ctypes.windll.kernel32
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    foto = k.CreateToolhelp32Snapshot(2, 0)   # TH32CS_SNAPPROCESS
    p, salida = _Proceso(), {}
    p.dwSize = ctypes.sizeof(p)
    try:
        ok = k.Process32FirstW(foto, ctypes.byref(p))
        while ok:
            salida[p.th32ProcessID] = (p.th32ParentProcessID, p.szExeFile.lower())
            ok = k.Process32NextW(foto, ctypes.byref(p))
    finally:
        k.CloseHandle(foto)
    return salida


def abierto_desde_explorador() -> bool:
    """Sube desde este proceso (python, el lanzador del venv, cmd) hasta el primero que no es
    python ni cmd: si es el Explorador, la ventana es del .bat."""
    procesos, pid = _procesos(), os.getpid()
    for _ in range(10):
        padre, nombre = procesos.get(pid, (0, ""))
        if nombre not in ("python.exe", "pythonw.exe", "cmd.exe", "conhost.exe"):
            return nombre == "explorer.exe"
        pid = padre
    return False


if __name__ == "__main__":
    try:
        sys.exit(0 if abierto_desde_explorador() else 1)
    except Exception:
        sys.exit(0)   # ante la duda, pausar: que no se cierre la ventana sin ver el resultado
