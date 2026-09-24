"""Tipos de discrepancia y reglas: cuáles se aplican y con qué severidad.

Se configuran en `config/discrepancias.yaml`. Un hallazgo se informa solo si su regla y
el tipo de discrepancia de la regla están activos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

SEVERIDADES = ("CRITICA", "NO CRITICA", "REVISAR", "OBSERVACION")


@dataclass(frozen=True)
class Regla:
    codigo: str
    tipo: str          # tipo de discrepancia (nomenclatura del departamento)
    activa: bool
    severidad: str


@dataclass
class Discrepancias:
    """Configuración de tipos y reglas. Una regla que no está en el documento se aplica
    con severidad NO CRITICA y el tipo que indica el programa."""
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
        d = cls()
        for tipo, conf in (datos or {}).items():
            conf = conf or {}
            d.tipos[tipo] = _booleano(conf.get("activo", True), f"{origen}: '{tipo}.activo'")
            for codigo, regla in (conf.get("reglas") or {}).items():
                if codigo in d.reglas:
                    raise ValueError(f"{origen}: la regla '{codigo}' está en "
                                     f"'{d.reglas[codigo].tipo}' y en '{tipo}'.")
                if isinstance(regla, str):  # forma corta: codigo: CRITICA
                    regla = {"severidad": regla}
                severidad = str(regla.get("severidad", "NO CRITICA")).upper()
                if severidad not in SEVERIDADES:
                    raise ValueError(f"{origen}: severidad '{severidad}' de '{codigo}' no válida "
                                     f"(use {', '.join(SEVERIDADES)}).")
                d.reglas[codigo] = Regla(
                    codigo, tipo, _booleano(regla.get("activa", True),
                                            f"{origen}: '{codigo}.activa'"), severidad)
        return d


def _booleano(valor: object, donde: str) -> bool:
    if not isinstance(valor, bool):
        raise ValueError(f"{donde} debe ser true o false (es '{valor}').")
    return valor


def cargar_discrepancias(ruta: Path) -> Discrepancias:
    datos = yaml.safe_load(Path(ruta).read_text(encoding="utf-8")) or {}
    return Discrepancias.desde_dict(datos.get("tipos", {}), Path(ruta).name)
