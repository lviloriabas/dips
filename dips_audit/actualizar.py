r"""¿Hay una versión más nueva del programa en GitHub? Si la hay, pregunta si se actualiza.

Lo llaman los .bat al inicio, antes de correr el programa. Solo con la biblioteca estándar (no
importa el paquete) para que el código nuevo recién bajado sea el que corra después.

No hace nada (sale con 0, en silencio) si la PC no tiene git, si la carpeta no es un repositorio,
si no hay conexión, si la rama actual no es main o si hay commits locales que no están en GitHub.
Con la variable de entorno DIPS_SIN_ACTUALIZAR no busca actualizaciones.

Sale con 3 si actualizó: el .bat se vuelve a lanzar para correr con la versión nueva (el .bat
mismo pudo haber cambiado).
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
RAMA = "main"
ACTUALIZADO = 3
ESPERA_FETCH = 20   # segundos: sin conexión o con la red lenta, se sigue sin actualizar
MAX_CAMBIOS = 10    # commits nuevos que se listan


def _git(*args: str, timeout: float = 10) -> str | None:
    """Salida de un comando git, o None si falla."""
    entorno = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    try:
        r = subprocess.run(["git", "-C", str(RAIZ), *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout, env=entorno,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _pendientes() -> tuple[str, list[str]] | None:
    """(commit de origin/main, títulos de los commits que faltan), o None si no hay que ofrecer
    nada."""
    if not shutil.which("git") or not (RAIZ / ".git").exists():
        return None
    if _git("rev-parse", "--abbrev-ref", "HEAD") != RAMA:
        return None
    if _git("fetch", "--quiet", "origin", RAMA, timeout=ESPERA_FETCH) is None:
        return None
    remoto = _git("rev-parse", f"origin/{RAMA}")
    cuentas = _git("rev-list", "--left-right", "--count", f"HEAD...origin/{RAMA}")
    if not remoto or not cuentas:
        return None
    adelante, atras = (int(n) for n in cuentas.split())
    if atras == 0 or adelante > 0:   # al día, o con commits locales: no se toca
        return None
    titulos = _git("log", "--format=%s", f"-{MAX_CAMBIOS}", f"HEAD..{remoto}") or ""
    return remoto, [t for t in titulos.splitlines() if t]


def _preguntar(texto: str) -> bool:
    try:
        respuesta = input(texto).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return respuesta in ("", "s", "si", "sí", "y", "yes")


def _actualizar(remoto: str) -> bool:
    antes = _git("rev-parse", "HEAD")
    if _git("merge", "--ff-only", "--quiet", remoto, timeout=60) is None:
        print("No se pudo actualizar (¿hay archivos del programa modificados en esta PC?). "
              "Se sigue con la versión actual.\n")
        return False
    # git diff --quiet falla (None) si el archivo cambió
    if antes and _git("diff", "--quiet", antes, remoto, "--", "requirements.txt") is None:
        print("Cambiaron las librerías: instalándolas...")
        r = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet",
                            "--disable-pip-version-check", "-r", str(RAIZ / "requirements.txt")])
        if r.returncode:
            print("No se pudieron instalar las librerías: ejecute setup.bat.")
    print("Programa actualizado.\n")
    return True


def main() -> int:
    if os.environ.get("DIPS_SIN_ACTUALIZAR") or not sys.stdin.isatty():
        return 0
    pendientes = _pendientes()
    if not pendientes:
        return 0
    remoto, titulos = pendientes
    atras = int(_git("rev-list", "--count", f"HEAD..{remoto}") or len(titulos))
    print(f"Hay una versión más nueva del programa ({atras} "
          f"{'cambio' if atras == 1 else 'cambios'}):")
    for t in titulos:
        print(f"  - {t}")
    if atras > len(titulos):
        print(f"  ... y {atras - len(titulos)} más")
    if not _preguntar("¿Actualizar ahora? [S/n] "):
        print("Se sigue con la versión actual.\n")
        return 0
    return ACTUALIZADO if _actualizar(remoto) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)   # un problema al buscar actualizaciones nunca impide usar el programa
