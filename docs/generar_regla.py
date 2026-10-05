"""Prepara ejemplos de reglas, sin modificar la auditoría ni su configuración."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import sys

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from dips_audit.discrepancias import SEVERIDADES, codigos_implementados

CAMPOS = {
    "descripcion": "Descripción del DIP",
    "nombre": "Fault Name",
    "deferral_ref": "Deferral Reference",
    "parent_assy": "Parent Assembly",
    "severidad": "Fault Severity",
}


def generar(codigo: str, tipo: str, campo: str, condicion: str, texto: str,
            etapa: str, severidad: str, mensaje: str) -> dict[str, str]:
    """Devuelve ejemplos de función, configuración, prueba e integración."""
    if not re.fullmatch(r"[a-z][a-z0-9_]*", codigo):
        raise ValueError("El código debe empezar con una letra y usar minúsculas, números y _.")
    if codigo in codigos_implementados():
        raise ValueError(f"El código '{codigo}' ya existe. Use otro para una regla nueva.")
    for etiqueta, valor in (("tipo", tipo), ("mensaje", mensaje)):
        if not valor.strip() or any(c in valor for c in "\r\n"):
            raise ValueError(f"El {etiqueta} debe tener texto en una sola línea.")
    if campo not in CAMPOS or condicion not in {"vacio", "no_contiene"}:
        raise ValueError("Elija un campo y una condición del generador.")
    if etapa not in {"APERTURA", "CIERRE"} or severidad not in SEVERIDADES:
        raise ValueError("La etapa o la severidad no son válidas.")
    if condicion == "no_contiene" and not texto.strip():
        raise ValueError("La condición no_contiene necesita el texto esperado.")
    if any(chr(0x2014) in v for v in (tipo, mensaje, texto)):
        raise ValueError("Use un guion normal en los textos.")

    funcion = f"regla_{codigo}"
    estados = '{"COMPLETE"}' if etapa == "CIERRE" else 'ACTIVOS'
    condicion_py = "not valor" if condicion == "vacio" else f"{texto.strip()!r}.casefold() not in valor.casefold()"
    valor_falla = ""
    valor_cumple = texto.strip() if condicion == "no_contiene" else "Dato presente"
    importacion = "from dips_audit.reglas import ACTIVOS\n\n" if etapa == "APERTURA" else ""
    python = f'''# EJEMPLO: revisar el criterio con el auditor antes de integrarlo.
{importacion}def {funcion}(dip, ctx, r):
    if dip.get("estado") not in {estados}:
        return
    if {campo!r} not in dip:
        r.manuales.append("Verificar {CAMPOS[campo]}: dato no disponible para esta regla.")
        return
    valor = str(dip.get({campo!r}) or "").strip()
    if {condicion_py}:
        r.agregar(ctx, {codigo!r}, {tipo!r}, {mensaje!r})
'''
    yaml = f'''# EJEMPLO: integrar debajo de tipos: en config/discrepancias.yaml.
# Si el tipo ya existe, agregar solo el código debajo de sus reglas:.
  {json.dumps(tipo, ensure_ascii=False)}:
    reglas:
      {json.dumps(codigo)}: {severidad}
'''
    prueba = f'''# EJEMPLO: guardar como tests/test_{codigo}.py después de integrar la función.
from datetime import date

from dips_audit.discrepancias import Discrepancias
from dips_audit.reglas import Contexto, auditar_dip, etapa
from tests.conftest import hacer_dip


def contexto(activa=True):
    configuracion = Discrepancias.desde_dict({{
        {tipo!r}: {{"reglas": {{
            {codigo!r}: {{"activa": activa, "severidad": {severidad!r}}}
        }}}}
    }})
    return Contexto(fecha_referencia=date(2026, 10, 5), discrepancias=configuracion)


def codigos(dip, activa=True):
    return {{h.codigo for h in auditar_dip(dip, None, contexto(activa)).hallazgos}}


def test_{codigo}():
    falla = hacer_dip(estado={('COMPLETE' if etapa == 'CIERRE' else 'ACTV')!r}, {campo}={valor_falla!r})
    cumple = {{**falla, {campo!r}: {valor_cumple!r}}}
    assert {codigo!r} in codigos(falla)
    assert {codigo!r} not in codigos(cumple)
    assert {codigo!r} not in codigos(falla, activa=False)
    otra_etapa = {{**falla, "estado": {('ACTV' if etapa == 'CIERRE' else 'COMPLETE')!r}}}
    assert {codigo!r} not in codigos(otra_etapa)
    assert etapa({codigo!r}) == {etapa!r}
'''
    instruccion_cierre = (f"4. Agregar `{codigo}` a `CODIGOS_CIERRE` en `dips_audit/reglas.py`.\n"
                         if etapa == "CIERRE" else
                         "4. Es de apertura: no agregar el código a `CODIGOS_CIERRE`.\n")
    instrucciones = f'''# Integración de {codigo}

Estos archivos son ejemplos. Generarlos no activa un chequeo.
El criterio y sus excepciones requieren revisión antes de usarlos en auditoría.

1. Copiar la función de `regla.py.txt` a `dips_audit/reglas.py`.
   Si necesita datos de ICAM, una referencia asociada o varios DIPs,
   adaptar la función y su lugar de ejecución con quien mantiene el sistema.
2. Dentro de `auditar_dip`, antes de `return r`, agregar:

   ```python
   {funcion}(dip, ctx, r)
   ```

3. Integrar `discrepancias.yaml.txt` en `config/discrepancias.yaml`.
   Conservar el bloque `tipos:` existente. Si `{tipo}` ya existe,
   incorporar solo `{codigo}: {severidad}` debajo de sus `reglas:`.
{instruccion_cierre}5. Copiar `prueba.py.txt` a `tests/test_{codigo}.py`.
6. Desde la raíz de DIPS, ejecutar:

   ```bat
   .venv\\Scripts\\python -m dips_audit validar-reglas
   .venv\\Scripts\\python -m pytest
   .venv\\Scripts\\python -m dips_audit benchmark
   ```

La prueba llama al flujo real `auditar_dip`: fallará si falta la conexión.
Agregar casos para dato no disponible y para las excepciones del criterio.
Revisar también un DIP de muestra con y sin el dato antes de publicar el cambio.
El generador cubre campo vacío y texto ausente. Comparaciones de fechas,
límites, referencias o varios DIPs necesitan una implementación específica.
'''
    ast.parse(python)
    ast.parse(prueba)
    return {"regla.py.txt": python, "discrepancias.yaml.txt": yaml,
            "prueba.py.txt": prueba, "LEEME.md": instrucciones}


def guardar(archivos: dict[str, str], destino: Path) -> Path:
    """Crea una carpeta nueva y nunca sobrescribe un ejemplo anterior."""
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=False)
    for nombre, contenido in archivos.items():
        (destino / nombre).write_text(contenido, encoding="utf-8")
    return destino


def elegir(pregunta: str, opciones: list[str]) -> str:
    print(f"\n{pregunta}")
    for numero, opcion in enumerate(opciones, 1):
        print(f"  {numero}. {opcion}")
    while True:
        respuesta = input("Número: ").strip()
        if respuesta.isdigit() and 1 <= int(respuesta) <= len(opciones):
            return opciones[int(respuesta) - 1]
        print("Elija uno de los números mostrados.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codigo")
    parser.add_argument("--tipo")
    parser.add_argument("--campo", choices=list(CAMPOS))
    parser.add_argument("--condicion", choices=["vacio", "no_contiene"])
    parser.add_argument("--texto", default="")
    parser.add_argument("--etapa", choices=["APERTURA", "CIERRE"])
    parser.add_argument("--severidad", choices=SEVERIDADES)
    parser.add_argument("--mensaje")
    parser.add_argument("--salida", type=Path)
    args = parser.parse_args(argv)
    try:
        if not args.codigo:
            print("GENERADOR DE EJEMPLOS DE REGLAS\nNo modifica el programa ni activa reglas.")
            args.codigo = input("Código nuevo (ejemplo: descripcion_obligatoria): ").strip()
            args.tipo = input("Tipo de discrepancia (nuevo o existente): ").strip()
            campo = elegir("Dato a revisar", list(CAMPOS.values()))
            args.campo = next(c for c, nombre in CAMPOS.items() if nombre == campo)
            args.condicion = elegir("Cuándo informa el hallazgo", ["vacio", "no_contiene"])
            if args.condicion == "no_contiene":
                args.texto = input("Texto que debe contener: ").strip()
            args.etapa = elegir("Etapa", ["APERTURA", "CIERRE"])
            print("CRITICA / NO CRITICA / REVISAR: POSIBLE DISCREPANCIA.\n"
                  "CONSULTAR MANUAL: REVISAR. SIN FUENTE: SIN FUENTE.\n"
                  "OBSERVACION: informa sin cambiar el resultado.")
            args.severidad = elegir("Severidad", list(SEVERIDADES))
            args.mensaje = input("Mensaje concreto que verá el auditor: ").strip()
        obligatorios = (args.tipo, args.campo, args.condicion, args.etapa,
                        args.severidad, args.mensaje)
        if not all(obligatorios):
            raise ValueError("Complete --tipo, --campo, --condicion, --etapa, --severidad y --mensaje.")
        archivos = generar(args.codigo, args.tipo, args.campo, args.condicion,
                           args.texto, args.etapa, args.severidad, args.mensaje)
        destino = args.salida or RAIZ / "docs" / "ejemplos" / "generados" / args.codigo
        guardar(archivos, destino)
        print(f"\nEjemplos guardados en {destino.resolve()}\n"
              "Abra LEEME.md para integrarlos. Todavía no se ejecutan en la auditoría.")
        return 0
    except (ValueError, OSError, EOFError) as error:
        print(f"No se generaron los ejemplos: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
