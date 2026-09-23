"""Carga de "DIPs References.xlsx", interpretación del TA y catálogo de Others."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl
import yaml

from .texto import contiene_frase, normalizar

# Unidades normalizadas: DAY (días calendario), FH (horas de vuelo),
# FC (ciclos), MONTH (se convierte a un rango de días al comparar).
_UNIDADES = {
    "DAY": "DAY", "DAYS": "DAY", "CDY": "DAY", "D": "DAY", "DIA": "DAY", "DIAS": "DAY",
    "HOUR": "FH", "HOURS": "FH", "FH": "FH", "HRS": "FH", "HR": "FH",
    "CYCLE": "FC", "CYCLES": "FC", "FC": "FC", "LANDINGS": "FC", "CYC": "FC",
    "MONTH": "MONTH", "MONTHS": "MONTH",
}


def normalizar_unidad(valor: object) -> str | None:
    if valor is None:
        return None
    return _UNIDADES.get(str(valor).strip().upper())


@dataclass(frozen=True)
class Limite:
    valor: float
    unidad: str  # DAY, FH, FC, MONTH

    def __str__(self) -> str:
        v = int(self.valor) if float(self.valor).is_integer() else self.valor
        return f"{v} {self.unidad}"


@dataclass
class FilaReferencia:
    fila: int
    tipo: str
    area: str
    ata: int | None
    flota: str
    descripcion: str
    parent_assy: str
    referencias: str
    ta: str
    rir: str
    notas: str = ""


@dataclass
class Variante:
    nombre: str
    limites: list[Limite]           # más de uno = límite dual (lo que ocurra primero)
    flotas: list[str] | None = None  # None = todas
    rir: str = ""
    referencia: FilaReferencia | None = None


@dataclass
class InterpretacionTA:
    limites: list[Limite] = field(default_factory=list)
    hasta_vencimiento: bool = False
    no_verificable: bool = False


@dataclass
class EntradaCatalogo:
    id: str
    nombre: str
    referencias: list[FilaReferencia]
    requiere: list[list[str]]
    excluir: list[str]
    variantes: list[Variante]
    hasta_vencimiento: bool = False
    no_verificable: bool = False
    requiere_sn: bool = False

    @property
    def parent_assy(self) -> set[str]:
        return {r.parent_assy.rstrip("*").strip() for r in self.referencias if r.parent_assy}

    @property
    def parent_assy_flexible(self) -> bool:
        return any(r.parent_assy.endswith("*") for r in self.referencias)

    @property
    def referencias_tecnicas(self) -> str:
        vistas: list[str] = []
        for r in self.referencias:
            if r.referencias and r.referencias not in vistas:
                vistas.append(r.referencias)
        return " | ".join(vistas)

    @property
    def especificidad(self) -> int:
        return len(self.requiere)

    def coincide(self, nombre_normalizado: str) -> tuple[bool, int]:
        """(coincide, puntaje). El puntaje favorece entradas más específicas."""
        if any(contiene_frase(nombre_normalizado, x) for x in self.excluir):
            return False, 0
        puntaje = 0
        for grupo in self.requiere:
            encontradas = [f for f in grupo if contiene_frase(nombre_normalizado, f)]
            if not encontradas:
                return False, 0
            puntaje += 100 + max(len(normalizar(f)) for f in encontradas)
        return True, puntaje

    def texto_busqueda(self) -> str:
        partes = [self.nombre] + [r.descripcion for r in self.referencias]
        partes += [f for g in self.requiere for f in g]
        return normalizar(" ".join(partes))


# --------------------------------------------------------------------------
# Lectura del Excel de referencias
# --------------------------------------------------------------------------

def _texto(v: object) -> str:
    if v is None:
        return ""
    return re.sub(r"\s+", " ", str(v)).strip()


def cargar_referencias(ruta: Path, hoja: str = "References") -> list[FilaReferencia]:
    wb = openpyxl.load_workbook(ruta, data_only=True, read_only=True)
    ws = wb[hoja]
    filas = list(ws.iter_rows(values_only=True))
    wb.close()
    encabezado = [_texto(c).upper() for c in filas[0]]
    idx = {nombre: encabezado.index(nombre) for nombre in
           ["TYPE", "AREA", "ATA", "FLEET", "DESCRIPTION", "PARENT ASSY", "REFERENCES", "TA", "RIR"]}
    resultado = []
    for n, fila in enumerate(filas[1:], start=2):
        def col(nombre: str) -> object:
            i = idx[nombre]
            return fila[i] if i < len(fila) else None

        descripcion = _texto(col("DESCRIPTION"))
        if not descripcion:
            continue
        # Columnas sin encabezado (p. ej. notas al margen de la tabla).
        extra = [_texto(v) for i, v in enumerate(fila)
                 if i not in idx.values() and _texto(v)]
        ata = col("ATA")
        resultado.append(FilaReferencia(
            fila=n,
            tipo=_texto(col("TYPE")).upper(),
            area=_texto(col("AREA")),
            ata=int(ata) if isinstance(ata, (int, float)) else None,
            flota=_texto(col("FLEET")),
            descripcion=descripcion,
            parent_assy=_texto(col("PARENT ASSY")).upper(),
            referencias=_texto(col("REFERENCES")),
            ta=_texto(col("TA")),
            rir=_texto(col("RIR")),
            notas=" ".join(extra),
        ))
    return resultado


def interpretar_ta(texto: str) -> InterpretacionTA:
    """Convierte el texto libre del TA en límites comparables.

    '3 DAYS' -> [3 DAY]; '60 DAYS OR 500 FH' -> límite dual; 'UNTIL DUE DATE' ->
    hasta_vencimiento. Textos condicionales (por flota, por presión...) se marcan
    no_verificable y deben definirse en el catálogo con 'intervalos'.
    """
    t = texto.upper()
    if "UNTIL DUE DATE" in t:
        return InterpretacionTA(hasta_vencimiento=True)
    limites = [
        Limite(float(v), normalizar_unidad(u))
        for v, u in re.findall(r"(\d+(?:\.\d+)?)\s*(DAYS?|MONTHS?|FH|FC|HOURS?|CYCLES?)\b", t)
    ]
    condicional = bool(re.search(r"[:;]|\bIF\b|\bAFTER\b|DEPENDING|CONSULT", t))
    if not limites or condicional:
        return InterpretacionTA(limites=limites, no_verificable=True)
    return InterpretacionTA(limites=limites)


def interpretar_rir(texto: str) -> str:
    """Devuelve el RIR solo si es un intervalo reconocible ('1 DAY', '100 FH')."""
    if re.search(r"\d+\s*(DAYS?|FH|FC|HOURS?|CYCLES?)", texto.upper()):
        return texto.upper()
    return ""


# --------------------------------------------------------------------------
# Catálogo
# --------------------------------------------------------------------------

class ErrorCatalogo(Exception):
    pass


@dataclass
class Catalogo:
    entradas: list[EntradaCatalogo]
    referencias: list[FilaReferencia]
    advertencias: list[str]

    def por_id(self, id_: str) -> EntradaCatalogo | None:
        return next((e for e in self.entradas if e.id == id_), None)


def cargar_catalogo(ruta_catalogo: Path, referencias: list[FilaReferencia],
                    tipo: str = "OTHERS") -> Catalogo:
    datos = yaml.safe_load(Path(ruta_catalogo).read_text(encoding="utf-8")) or []
    por_descripcion = {normalizar(r.descripcion): r for r in referencias}
    entradas: list[EntradaCatalogo] = []
    advertencias: list[str] = []
    ids = set()

    for d in datos:
        if d["id"] in ids:
            raise ErrorCatalogo(f"ID repetido en el catálogo: {d['id']}")
        ids.add(d["id"])
        filas = []
        for desc in d["referencias"]:
            fila = por_descripcion.get(normalizar(desc))
            if fila is None:
                raise ErrorCatalogo(
                    f"[{d['id']}] La referencia '{desc}' no existe en DIPs References.xlsx")
            filas.append(fila)

        variantes: list[Variante] = []
        hasta_vencimiento = no_verificable = False
        if d.get("intervalos"):
            for v in d["intervalos"]:
                variantes.append(Variante(
                    nombre=v["variante"],
                    limites=[Limite(float(l["valor"]), l["unidad"]) for l in v["limites"]],
                    flotas=v.get("flotas"),
                    rir=v.get("rir", ""),
                    referencia=filas[0],
                ))
        else:
            for fila in filas:
                interp = interpretar_ta(fila.ta)
                if interp.hasta_vencimiento:
                    hasta_vencimiento = True
                elif interp.no_verificable:
                    no_verificable = True
                    advertencias.append(
                        f"[{d['id']}] TA no interpretable automáticamente: '{fila.ta}' "
                        f"(fila {fila.fila}). Defínalo con 'intervalos' en el catálogo.")
                else:
                    variantes.append(Variante(
                        nombre=fila.descripcion, limites=interp.limites,
                        rir=interpretar_rir(fila.rir), referencia=fila))

        entradas.append(EntradaCatalogo(
            id=d["id"], nombre=d.get("nombre", d["id"]), referencias=filas,
            requiere=d["requiere"], excluir=d.get("excluir", []), variantes=variantes,
            hasta_vencimiento=hasta_vencimiento,
            no_verificable=no_verificable and not variantes,
            requiere_sn=bool(d.get("requiere_sn", False)),
        ))

    usadas = {id(f) for e in entradas for f in e.referencias}
    for r in referencias:
        if r.tipo == tipo and id(r) not in usadas:
            advertencias.append(
                f"Referencia {tipo} sin entrada en el catálogo (fila {r.fila}): {r.descripcion}")
        if r.tipo == tipo and r.ata is None:
            advertencias.append(f"Referencia sin ATA (fila {r.fila}): {r.descripcion}")
    return Catalogo(entradas=entradas, referencias=referencias, advertencias=advertencias)
