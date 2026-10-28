import os
import subprocess
import sys
from pathlib import Path


def test_pruebas_en_copia_nueva_crean_temporales_y_respetan_otras_corridas(tmp_path):
    raiz = Path(__file__).resolve().parent.parent
    (tmp_path / "conftest.py").write_text(
        "from pathlib import Path\n"
        "from tests import conftest as proyecto\n"
        "proyecto.TEMPORALES = Path(__file__).parent / '.pytest_tmp'\n"
        "pytest_configure = proyecto.pytest_configure\n"
        "pytest_unconfigure = proyecto.pytest_unconfigure\n",
        encoding="utf-8",
    )
    prueba = tmp_path / "test_escritura.py"
    prueba.write_text(
        "def test_escritura(tmp_path):\n"
        "    archivo = tmp_path / 'resultado.txt'\n"
        "    archivo.write_text('sin administrador', encoding='utf-8')\n"
        "    assert archivo.read_text(encoding='utf-8') == 'sin administrador'\n",
        encoding="utf-8",
    )
    entorno = os.environ.copy()
    entorno["PYTHONPATH"] = str(raiz) + os.pathsep + entorno.get("PYTHONPATH", "")
    comando = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
               "--confcutdir", str(tmp_path), str(prueba)]
    temporales = tmp_path / ".pytest_tmp"
    assert not temporales.exists()

    resultado = subprocess.run(comando, cwd=tmp_path, env=entorno, capture_output=True,
                               text=True, timeout=60)

    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    assert temporales.is_dir()
    assert list(temporales.iterdir()) == []

    otra_corrida = temporales / "otra-corrida"
    otra_corrida.mkdir()
    conservar = otra_corrida / "conservar.txt"
    conservar.write_text("no borrar", encoding="utf-8")

    repetida = subprocess.run(comando, cwd=tmp_path, env=entorno, capture_output=True,
                              text=True, timeout=60)

    assert repetida.returncode == 0, repetida.stdout + repetida.stderr
    assert conservar.read_text(encoding="utf-8") == "no borrar"
    assert list(temporales.iterdir()) == [otra_corrida]
