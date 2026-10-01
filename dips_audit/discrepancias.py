"""Tipos de discrepancia y reglas: cuáles se aplican y con qué severidad.

Se configuran en `config/discrepancias.yaml`. Un hallazgo se informa solo si su regla y
el tipo de discrepancia de la regla están activos.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

import yaml

SEVERIDADES = ("CRITICA", "NO CRITICA", "REVISAR", "CONSULTAR MANUAL", "SIN FUENTE", "OBSERVACION")


class _SinDuplicados(yaml.SafeLoader):
    pass


def _mapa_sin_duplicados(loader: _SinDuplicados, nodo: yaml.MappingNode) -> dict:
    resultado = {}
    for clave_nodo, valor_nodo in nodo.value:
        clave = loader.construct_object(clave_nodo, deep=True)
        if clave in resultado:
            raise ValueError(f"Clave repetida '{clave}' en la línea {clave_nodo.start_mark.line + 1}.")
        resultado[clave] = loader.construct_object(valor_nodo, deep=True)
    return resultado


_SinDuplicados.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
                               _mapa_sin_duplicados)


@dataclass(frozen=True)
class Regla:
    codigo: str
    tipo: str          # tipo de discrepancia (nomenclatura del departamento)
    activa: bool
    severidad: str


@dataclass
class Discrepancias:
    """Configuración de tipos y reglas. En auditorías reales se comprueba la cobertura
    completa; el valor por defecto permite construir contextos parciales en pruebas."""
    tipos: dict[str, bool] = field(default_factory=dict)     # tipo -> activo
    reglas: dict[str, Regla] = field(default_factory=dict)   # código -> regla
    solo: set[str] | None = None   # tipos elegidos al ejecutar (--categorias); None = todos

    def activa(self, codigo: str, tipo: str | None = None) -> bool:
        """`tipo`: el de la regla si no está en el documento."""
        r = self.reglas.get(codigo)
        if self.solo is not None and (r.tipo if r else tipo) not in self.solo:
            return False
        return r is None or (r.activa and self.tipos.get(r.tipo, True))

    def buscar_tipos(self, nombres: list[str]) -> set[str]:
        """Tipos que corresponden a los nombres escritos: el nombre completo o una parte
        ("technical reference" = Missing e Incorrect Technical Reference), sin distinguir
        mayúsculas. Error si alguno no corresponde a ningún tipo."""
        encontrados: set[str] = set()
        for nombre in nombres:
            n = nombre.strip().lower()
            iguales = {t for t in self.tipos if t.lower() == n}
            parecidos = iguales or {t for t in self.tipos if n in t.lower()}
            if not parecidos:
                raise ValueError(f"'{nombre}' no es un tipo de discrepancia. Tipos: "
                                 + ", ".join(self.tipos) + ".")
            encontrados |= parecidos
        return encontrados

    def filtrar(self, incluir: list[str] | None = None,
                excluir: list[str] | None = None) -> list[str]:
        """Revisa solo los tipos de `incluir` (todos si no se indica) menos los de `excluir`.
        Devuelve los tipos que quedan activos."""
        solo = self.buscar_tipos(incluir) if incluir else set(self.tipos)
        if excluir:
            solo -= self.buscar_tipos(excluir)
        self.solo = solo
        return [t for t, activo in self.tipos.items() if activo and t in solo]

    def severidad(self, codigo: str) -> str:
        r = self.reglas.get(codigo)
        return r.severidad if r else "NO CRITICA"

    def tipo(self, codigo: str, defecto: str) -> str:
        r = self.reglas.get(codigo)
        return r.tipo if r else defecto

    def como_dict(self) -> dict:
        """Tal como se escribe en el documento (para el benchmark)."""
        return {t: {"activo": activo,
                    "reglas": {r.codigo: {"activa": r.activa, "severidad": r.severidad}
                               for r in self.reglas.values() if r.tipo == t}}
                for t, activo in self.tipos.items()}

    @classmethod
    def desde_dict(cls, datos: dict, origen: str = "discrepancias") -> Discrepancias:
        if not isinstance(datos, dict):
            raise ValueError(f"{origen}: 'tipos' debe contener los tipos y sus reglas.")
        d = cls()
        for tipo, conf in datos.items():
            if not isinstance(tipo, str) or not tipo.strip() or not isinstance(conf, dict):
                raise ValueError(f"{origen}: cada tipo debe tener un nombre y un bloque de reglas.")
            desconocidas = set(conf) - {"activo", "reglas"}
            if desconocidas:
                raise ValueError(f"{origen}: campos desconocidos en '{tipo}': {', '.join(sorted(desconocidas))}.")
            d.tipos[tipo] = _booleano(conf.get("activo", True), f"{origen}: '{tipo}.activo'")
            reglas = conf.get("reglas")
            if not isinstance(reglas, dict) or not reglas:
                raise ValueError(f"{origen}: '{tipo}.reglas' debe contener al menos una regla.")
            for codigo, regla in reglas.items():
                if not isinstance(codigo, str) or not codigo.strip():
                    raise ValueError(f"{origen}: cada regla de '{tipo}' necesita un código.")
                if codigo in d.reglas:
                    raise ValueError(f"{origen}: la regla '{codigo}' está en "
                                     f"'{d.reglas[codigo].tipo}' y en '{tipo}'.")
                if isinstance(regla, str):  # forma corta: codigo: CRITICA
                    regla = {"severidad": regla}
                if not isinstance(regla, dict):
                    raise ValueError(f"{origen}: '{codigo}' debe indicar una severidad.")
                desconocidas = set(regla) - {"activa", "severidad"}
                if desconocidas:
                    raise ValueError(f"{origen}: campos desconocidos en '{codigo}': {', '.join(sorted(desconocidas))}.")
                activa = _booleano(regla.get("activa", True),
                                   f"{origen}: '{codigo}.activa'")
                if "severidad" not in regla:
                    raise ValueError(f"{origen}: '{codigo}' debe indicar una severidad.")
                severidad = str(regla["severidad"]).upper()
                if severidad not in SEVERIDADES:
                    raise ValueError(f"{origen}: severidad '{severidad}' de '{codigo}' no válida "
                                     f"(use {', '.join(SEVERIDADES)}).")
                d.reglas[codigo] = Regla(
                    codigo, tipo, activa, severidad)
        return d


def _booleano(valor: object, donde: str) -> bool:
    if not isinstance(valor, bool):
        raise ValueError(f"{donde} debe ser true o false (es '{valor}').")
    return valor


def cargar_discrepancias(ruta: Path) -> Discrepancias:
    datos = yaml.load(Path(ruta).read_text(encoding="utf-8"), Loader=_SinDuplicados)
    if not isinstance(datos, dict) or set(datos) != {"tipos"}:
        raise ValueError(f"{Path(ruta).name}: se espera un bloque 'tipos' con las reglas.")
    return Discrepancias.desde_dict(datos["tipos"], Path(ruta).name)


def codigos_implementados() -> set[str]:
    """Códigos literales usados al crear hallazgos en los módulos de auditoría."""
    codigos = set()
    for ruta in Path(__file__).parent.glob("*.py"):
        arbol = ast.parse(ruta.read_text(encoding="utf-8"), filename=str(ruta))
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.Call) or not nodo.args:
                continue
            funcion = nodo.func
            if isinstance(funcion, ast.Attribute) and funcion.attr == "agregar" and len(nodo.args) > 1:
                candidato = nodo.args[1]
            elif (isinstance(funcion, ast.Attribute) and funcion.attr == "append"
                  and isinstance(funcion.value, ast.Name) and funcion.value.id == "hallazgos"
                  and isinstance(nodo.args[0], ast.Tuple)):
                candidato = nodo.args[0].elts[0]
            elif isinstance(funcion, ast.Name) and funcion.id == "Revision":
                candidato = nodo.args[0]
            else:
                continue
            codigos.update(n.value for n in ast.walk(candidato)
                           if isinstance(n, ast.Constant) and isinstance(n.value, str))
    return codigos


def validar_cobertura(discrepancias: Discrepancias) -> None:
    """Detecta reglas omitidas o nombres mal escritos antes de usar la configuración."""
    implementados = codigos_implementados()
    configurados = set(discrepancias.reglas)
    faltan = implementados - configurados
    sobran = configurados - implementados
    if faltan or sobran:
        partes = []
        if faltan:
            partes.append("faltan en discrepancias.yaml: " + ", ".join(sorted(faltan)))
        if sobran:
            partes.append("no existen en el programa: " + ", ".join(sorted(sobran)))
        raise ValueError("Reglas: " + "; ".join(partes) + ".")
