"""Referencia técnica cargada en el DIP frente a la de la tabla de referencias.

Los números de tarea (AMM, ECRA/EA, task card JIC, SRM) se extraen de los dos textos y
se comparan de forma exacta. Así se detecta si el DIP no tiene referencia técnica, si
tiene la de otra referencia (se equivocaron) o una tarea que la tabla no tiene. Si el
nombre no alcanza para asociar el DIP, un número que corresponde a una sola referencia
del catálogo también sirve para asociarlo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .referencias import Catalogo, EntradaCatalogo, FilaReferencia

# Tarea AMM o subtarea: 32-44-00-790-801 (se ignora el sufijo de efectividad -F00/-G00).
_AMM = re.compile(r"(?<![\d-])(\d{2})-(\d{2})-(\d{2})-(\d{3})-(\d{3})")
# ECRA / EC / EA: 3244-0178C REV 4 -> 3244-0178 (misma numeración de ingeniería).
_EC = re.compile(r"\b(?:ECRA|EC|EA)\s*#?\s*(\d{4})-(\d{4})", re.I)
# Task card: B737-31-1-0003-U-JIC o MAX-31-1-0003-U-JIC (misma tarjeta en las dos flotas).
_JIC = re.compile(r"\b(?:B737|MAX\d?)-(\d{2})-(\d)-(\d{4})-U-JIC", re.I)
# SRM 51-10-05-0G-0 -> capítulo-sección-tema.
_SRM = re.compile(r"\bSRM\s*(\d{2})-(\d{2})-(\d{2})", re.I)
# MGM 7.7 (manual general de mantenimiento, por sección).
_MGM = re.compile(r"\bMGM\s*(\d+(?:\.\d+)+)", re.I)


def extraer_codigos(texto: object) -> list[str]:
    """Números de referencia técnica normalizados, en el orden en que aparecen."""
    if texto is None:
        return []
    t = re.sub(r"\s+", " ", str(texto))
    codigos = [f"AMM {'-'.join(m.groups())}" for m in _AMM.finditer(t)]
    codigos += [f"EC {m.group(1)}-{m.group(2)}" for m in _EC.finditer(t)]
    codigos += [f"JIC {'-'.join(m.groups())}" for m in _JIC.finditer(t)]
    codigos += [f"SRM {'-'.join(m.groups())}" for m in _SRM.finditer(t)]
    codigos += [f"MGM {m.group(1)}" for m in _MGM.finditer(t)]
    return list(dict.fromkeys(codigos))


# Referencia del manual: cualquier manual seguido de un identificador con números
# (AMM TASK 12-15-21-200-801, MGM 7.7, FIM TASK ..., SRM 51-10-05, IPC 32-11-01, EC 1215-0032C).
_MANUAL = re.compile(
    r"\b(AMM|MGM|FIM|SRM|IPC|CMM|TSM|WDM|SSM|MPD|DDG|SB|AD|ECRA|EC|EA|JIC|TASK\s*CARD)\b"
    r"\s*(?:SUB)?(?:TASK)?\s*[#:.]?\s*([A-Z0-9]*\d[A-Z0-9]*(?:[-.][A-Z0-9]+)*)", re.I)
# Revisión del manual y su fecha, en cualquier orden y cerca una de otra:
# "REV 28, 15-MAY-2026", "Rev.90 / 15 Jun 2026", "REVISION 12 DATED 01/08/2026",
# "15-MAY-2026 REV 28".
_MES = r"(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*"
_FECHA = (rf"(?:\d{{1,2}}\s*[-/ ]\s*{_MES}\s*[-/ ,]?\s*\d{{2,4}}"
          rf"|{_MES}\s+\d{{1,2}}\s*,?\s*\d{{4}}"
          r"|\d{1,2}[/.-]\d{1,2}[/.-]\d{4}|\d{4}-\d{2}-\d{2})")
_REV = r"\b(?:REV(?:ISION)?|VER(?:SION)?)\s*\.?\s*(?:NO\.?\s*)?[#:]?\s*(\d+)\b"
_REVISION = re.compile(_REV, re.I)
_REV_Y_FECHA = re.compile(rf"{_REV}[^A-Z0-9]{{0,6}}(?:DATED?|OF|DE|DEL)?\W{{0,3}}({_FECHA})", re.I)
_FECHA_Y_REV = re.compile(rf"({_FECHA})[^A-Z0-9]{{0,6}}{_REV}", re.I)


@dataclass
class ReferenciaEncontrada:
    """Lo que el DIP dice de su referencia técnica."""
    manual: str | None = None     # primera referencia del manual encontrada
    revision: str | None = None
    fecha: str | None = None      # fecha de la REV

    @property
    def faltantes(self) -> list[str]:
        salida = []
        if not self.manual:
            salida.append("referencia del manual")
        if not self.revision:
            salida.append("REV")
        if not self.fecha:
            salida.append("fecha de la REV")
        return salida

    def __str__(self) -> str:
        partes = [self.manual, f"REV {self.revision}" if self.revision else None, self.fecha]
        return " · ".join(p for p in partes if p)


def buscar_referencia(*textos: object) -> ReferenciaEncontrada:
    """Busca en todos los textos del DIP (descripción primero) la referencia del manual,
    su revisión y la fecha de la revisión. La fecha solo cuenta si va junto a la revisión:
    así no se toman fechas de vencimiento del ítem ("Battery Due: 31-JAN-2027")."""
    r = ReferenciaEncontrada()
    for texto in textos:
        if not texto:
            continue
        t = re.sub(r"\s+", " ", str(texto))
        if r.manual is None:
            codigos = extraer_codigos(t)
            m = _MANUAL.search(t)
            r.manual = codigos[0] if codigos else (
                f"{re.sub(r'\s+', ' ', m.group(1)).upper()} {m.group(2).upper()}" if m else None)
        if r.fecha is None:
            m = _REV_Y_FECHA.search(t)
            if m:
                r.revision, r.fecha = m.group(1), m.group(2).upper()
            else:
                m = _FECHA_Y_REV.search(t)
                if m:
                    r.fecha, r.revision = m.group(1).upper(), m.group(2)
        if r.revision is None:
            m = _REVISION.search(t)
            if m:
                r.revision = m.group(1)
    return r


def _tema(codigo: str) -> str | None:
    """Capítulo-sección-tema de una tarea AMM (12-15-21), para reconocer tareas hermanas."""
    return codigo[4:12] if codigo.startswith("AMM ") else None


@dataclass
class IndiceReferencias:
    """Qué entradas del catálogo y qué filas de la tabla tienen cada número."""
    por_entrada: dict[str, set[str]] = field(default_factory=dict)       # id -> códigos
    entradas: dict[str, set[str]] = field(default_factory=dict)          # código -> ids
    filas: dict[str, list[FilaReferencia]] = field(default_factory=dict)  # código -> filas

    @classmethod
    def desde_catalogo(cls, catalogo: Catalogo) -> IndiceReferencias:
        indice = cls()
        for e in catalogo.entradas:
            codigos = {c for r in e.referencias for c in extraer_codigos(r.referencias)}
            indice.por_entrada[e.id] = codigos
            for c in codigos:
                indice.entradas.setdefault(c, set()).add(e.id)
        for fila in catalogo.referencias:  # todas las filas, también Structures y Powerplant
            for c in extraer_codigos(fila.referencias):
                indice.filas.setdefault(c, []).append(fila)
        return indice

    def entrada_unica(self, codigos: list[str]) -> str | None:
        """ID de la única entrada del catálogo que tiene alguno de estos números."""
        ids = set().union(*(self.entradas.get(c, set()) for c in codigos)) if codigos else set()
        return next(iter(ids)) if len(ids) == 1 else None


@dataclass
class Revision:
    codigo: str | None      # clave del hallazgo en config.yaml; None = coincide
    mensaje: str = ""


def _lista(codigos: set[str] | list[str]) -> str:
    return ", ".join(sorted(codigos))


def revisar(texto: str | None, entrada: EntradaCatalogo, catalogo: Catalogo,
            indice: IndiceReferencias) -> Revision | None:
    """Compara la referencia técnica del DIP con la de su referencia en la tabla.

    `texto` None = no se tiene el dato (no se revisa); "" = el DIP no tiene referencia
    técnica cargada. Devuelve None si la tabla no define referencia técnica para la entrada.
    """
    if texto is None:
        return None
    esperados = indice.por_entrada.get(entrada.id, set())
    if not esperados:
        return None
    cargados = extraer_codigos(texto)
    if not cargados:
        return Revision("sin_referencia_tecnica",
                        f"Sin referencia técnica. Corresponde {_lista(esperados)}.")
    if esperados & set(cargados):
        return Revision(None)
    otras = sorted({i for c in cargados for i in indice.entradas.get(c, set())} - {entrada.id})
    otras_tablas = sorted({f"{f.descripcion} ({f.tipo.title()})" for c in cargados
                           for f in indice.filas.get(c, []) if f.tipo.upper() != "OTHERS"})
    if otras or otras_tablas:
        nombres = [catalogo.por_id(i).nombre for i in otras] + otras_tablas
        return Revision("referencia_tecnica_equivocada",
                        f"Referencia técnica {_lista(cargados)} es de '{'; '.join(nombres)}'. "
                        f"Corresponde {_lista(esperados)}.")
    temas = {_tema(c) for c in esperados} - {None}
    mismo_tema = [c for c in cargados if _tema(c) in temas]
    if mismo_tema:
        return Revision("referencia_tecnica_distinta",
                        f"Referencia técnica {_lista(mismo_tema)}: mismo tema que la tabla "
                        f"({_lista(esperados)}), otra tarea. Verificar que aplique.")
    return Revision("referencia_tecnica_distinta",
                    f"Referencia técnica {_lista(cargados)} no está en la tabla. "
                    f"Corresponde {_lista(esperados)}.")
