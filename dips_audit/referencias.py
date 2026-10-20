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
    # Ventana "AFTER A, BEFORE B": el T/A empieza A después de la apertura y dura B - A
    # (vence igual a los B de la tabla). None = empieza en la apertura.
    inicio: Limite | None = None
    # True: también vale empezar en la apertura con B (sellante: 7 días, o +3 y 4 días).
    inicio_opcional: bool = False

    def intervalo_desde_inicio(self, lim: Limite) -> float | None:
        """Intervalo que debe tener el T/A si empieza en `inicio` (B - A); None sin ventana."""
        if self.inicio is None or self.inicio.unidad != lim.unidad:
            return None
        return lim.valor - self.inicio.valor


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
    # TA o RIR que cambian según el daño, la medición o el tipo ("DEPENDING ON DAMAGE ZONE",
    # "CONSULT SRM 53-00-01"): el texto de la tabla. Se revisan en el manual: REVISAR.
    ta_segun_manual: str = ""
    rir_segun_manual: str = ""
    # Fila de la tabla sin entrada en el catálogo: se reconoce por las palabras de su
    # DESCRIPTION y por su referencia técnica, solo si ninguna entrada del catálogo coincide.
    automatica: bool = False
    # Como el asterisco en PARENT ASSY de la tabla: otro Parent Assembly queda en OK.
    parent_flexible: bool = False
    # El vencimiento del ítem es el del PDF de inventario adjunto (generators de oxígeno).
    inventario: bool = False
    # El T/A empieza en la apertura con el intervalo completo: un Start posterior con eso
    # descontado del intervalo no se acepta (FDR: 30 días, no 7 + 23).
    start_en_apertura: bool = False
    # (frases, Parent Assembly): si el DIP tiene alguna de las frases, ese es el Parent
    # Assembly correcto y no el de la tabla (mensaje LONG TIME del reversor: AIRCRAFT).
    parent_segun_texto: list[tuple[list[str], str]] = field(default_factory=list)

    @property
    def parent_assy(self) -> set[str]:
        return {r.parent_assy.rstrip("*").strip() for r in self.referencias if r.parent_assy}

    @property
    def parent_assy_flexible(self) -> bool:
        return self.parent_flexible or any(r.parent_assy.endswith("*") for r in self.referencias)

    def parent_por_texto(self, texto_normalizado: str) -> tuple[str, str] | None:
        """(Parent Assembly, frase que lo decide) si el texto del DIP tiene alguna de las
        frases de `parent_assy_segun_texto`; None si manda la tabla."""
        for frases, parent in self.parent_segun_texto:
            for frase in frases:
                if contiene_frase(texto_normalizado, frase):
                    return parent, frase
        return None

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


_COLUMNAS = ["TYPE", "AREA", "ATA", "FLEET", "DESCRIPTION", "PARENT ASSY",
             "REFERENCES", "TA", "RIR"]


def _filas_pdf(ruta: Path) -> list[tuple]:
    """Lee un PDF de texto exportado con las nueve columnas de References visibles."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    filas: list[tuple] = [tuple(_COLUMNAS)]
    try:
        paginas = PdfReader(str(ruta)).pages
    except PdfReadError as e:
        raise ErrorCatalogo(f"No se pudo leer el PDF de referencias {ruta.name}: {e}") from e
    for pagina in paginas:
        lineas = (pagina.extract_text(extraction_mode="layout") or "").splitlines()
        posiciones = None
        actual: list[str] | None = None
        for linea in lineas:
            mayus = linea.upper()
            if all(nombre in mayus for nombre in _COLUMNAS):
                nuevas = []
                desde = 0
                for nombre in _COLUMNAS:
                    pos = mayus.find(nombre, desde)
                    if pos < 0:
                        break
                    nuevas.append(pos)
                    desde = pos + len(nombre)
                if len(nuevas) == len(_COLUMNAS):
                    posiciones = nuevas
                continue
            if posiciones is None or not linea.strip() or re.search(r"\bPAGE\s+\d+\b", mayus):
                continue
            celdas = [linea[posiciones[i]:posiciones[i + 1]].strip()
                      for i in range(len(posiciones) - 1)]
            celdas.append(linea[posiciones[-1]:].strip())
            tipo = celdas[0].upper()
            if tipo in {"OTHERS", "POWERPLANT", "STRUCTURES"} and celdas[4]:
                actual = celdas
                filas.append(tuple(actual))
            elif actual is not None and not celdas[0] and any(celdas[1:]):
                for i, valor in enumerate(celdas[1:], 1):
                    if valor:
                        actual[i] = (actual[i] + " " + valor).strip()
                filas[-1] = tuple(actual)
    if len(filas) == 1:
        raise ErrorCatalogo("El PDF no contiene la tabla References con texto seleccionable "
                            "y las nueve columnas. Exporte la hoja completa a PDF o use el XLSX.")
    return filas


def cargar_referencias(ruta: Path, hoja: str = "References") -> list[FilaReferencia]:
    ruta = Path(ruta)
    if ruta.suffix.lower() == ".pdf":
        filas = _filas_pdf(ruta)
    elif ruta.suffix.lower() in {".xlsx", ".xlsm"}:
        wb = openpyxl.load_workbook(ruta, data_only=True, read_only=True)
        if hoja not in wb:
            wb.close()
            raise ErrorCatalogo(f"La hoja '{hoja}' no existe en {ruta.name}.")
        filas = list(wb[hoja].iter_rows(values_only=True))
        wb.close()
    else:
        raise ErrorCatalogo("La fuente de referencias debe ser un XLSX o PDF.")
    if not filas:
        raise ErrorCatalogo(f"La tabla de referencias de {ruta.name} está vacía.")
    encabezado = [_texto(c).upper() for c in filas[0]]
    try:
        idx = {nombre: encabezado.index(nombre) for nombre in _COLUMNAS}
    except ValueError as e:
        raise ErrorCatalogo(f"Falta una columna obligatoria en {ruta.name}: {e}") from e
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
            ata=int(ata) if isinstance(ata, (int, float)) else (
                int(ata) if str(ata).strip().isdigit() else None),
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


def remite_al_manual(texto: str) -> bool:
    """El TA o el RIR de la tabla cambia según el daño, la medición o el tipo, y hay que
    ir al manual: '25 FC DEPENDING ON MEASUREMENTS', '7 DAYS OR 1 DAY, DEPENDING ON DAMAGE
    ZONE AND SIZE (CONSULT REF.)', '10 FC, 350 FC OR BEFORE NEXT REVENUE FLIGHT. CONSULT SRM',
    'MMEL 32-51-02' (el plazo del ítem del MMEL)."""
    return bool(re.search(r"DEPEND|CONSULT|SEG[UÚ]N|\bMMEL\b", (texto or "").upper()))


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
                advertencias.append(
                    f"[{d['id']}] Referencia retirada o renombrada en la tabla vigente: "
                    f"'{desc}'. Se omite esa referencia del catálogo local.")
                continue
            filas.append(fila)
        if not filas:
            continue  # no conservar reglas ni intervalos de ítems que ya no están en la tabla

        variantes: list[Variante] = []
        hasta_vencimiento = no_verificable = False
        # Las variantes locales solo interpretan la versión de TA para la que se definieron.
        # Si cambia online, manda la tabla; una condición nueva queda para revisión manual.
        usar_intervalos = bool(d.get("intervalos"))
        if usar_intervalos and d.get("ta_base") is not None and any(
                _texto(f.ta).casefold() != _texto(d["ta_base"]).casefold() for f in filas):
            usar_intervalos = False
            advertencias.append(
                f"[{d['id']}] El TA cambió en la tabla vigente. Se usa el nuevo TA "
                "y se omiten las variantes locales anteriores.")
        ta_manual = "" if usar_intervalos else "; ".join(
            f.ta for f in filas if remite_al_manual(f.ta))
        rir_manual = "; ".join(f.rir for f in filas if remite_al_manual(f.rir))
        if usar_intervalos:
            for v in d["intervalos"]:
                variantes.append(Variante(
                    nombre=v["variante"],
                    limites=[Limite(float(l["valor"]), l["unidad"]) for l in v["limites"]],
                    flotas=v.get("flotas"),
                    rir=interpretar_rir(filas[0].rir),
                    referencia=filas[0],
                    inicio=(Limite(float(v["inicio"]["valor"]), v["inicio"]["unidad"])
                            if v.get("inicio") else None),
                    inicio_opcional=bool(v.get("inicio_opcional", False)),
                ))
        else:
            variantes, hasta_vencimiento, no_verificable = _variantes_de_la_tabla(
                d["id"], filas, advertencias)

        entradas.append(EntradaCatalogo(
            id=d["id"], nombre=d.get("nombre", d["id"]), referencias=filas,
            requiere=d["requiere"], excluir=d.get("excluir", []), variantes=variantes,
            hasta_vencimiento=hasta_vencimiento,
            no_verificable=no_verificable and not variantes,
            requiere_sn=bool(d.get("requiere_sn", False)),
            ta_segun_manual=ta_manual, rir_segun_manual=rir_manual,
            parent_flexible=bool(d.get("parent_assy_flexible", False)),
            inventario=bool(d.get("inventario", False)),
            start_en_apertura=bool(d.get("start_en_apertura", False)),
            parent_segun_texto=[(list(p["contiene"]), str(p["parent_assy"]).upper())
                                for p in d.get("parent_assy_segun_texto", [])],
        ))

    # Filas de la tabla (de cualquier tipo) que el catálogo no tiene: entrada automática.
    usadas = {id(f) for e in entradas for f in e.referencias}
    for r in referencias:
        if id(r) not in usadas:
            entrada = _entrada_automatica(r, advertencias)
            entradas.append(entrada)
            advertencias.append(
                f"Fila {r.fila} sin entrada en el catálogo ({r.tipo}): {r.descripcion}. Se "
                f"reconoce por su referencia técnica o si el DIP tiene estas palabras: "
                f"{', '.join(g[0] for g in entrada.requiere) or '-'}.")
        if r.tipo == tipo and r.ata is None:
            advertencias.append(f"Referencia sin ATA (fila {r.fila}): {r.descripcion}")
    return Catalogo(entradas=entradas, referencias=referencias, advertencias=advertencias)


def _variantes_de_la_tabla(id_: str, filas: list[FilaReferencia], advertencias: list[str]
                           ) -> tuple[list[Variante], bool, bool]:
    """(variantes, hasta_vencimiento, no_verificable) según el TA de las filas."""
    variantes: list[Variante] = []
    hasta_vencimiento = no_verificable = False
    for fila in filas:
        interp = interpretar_ta(fila.ta)
        if interp.hasta_vencimiento:
            hasta_vencimiento = True
        elif interp.no_verificable:
            no_verificable = True
            if remite_al_manual(fila.ta):
                continue  # queda en REVISAR: el TA sale del manual
            advertencias.append(
                f"[{id_}] TA no interpretable automáticamente: '{fila.ta}' "
                f"(fila {fila.fila}). Defínalo con 'intervalos' en el catálogo.")
        else:
            variantes.append(Variante(
                nombre=fila.descripcion, limites=interp.limites,
                rir=interpretar_rir(fila.rir), referencia=fila))
    return variantes, hasta_vencimiento, no_verificable


# Palabras de la DESCRIPTION que no identifican el ítem.
_PALABRAS_GENERICAS = {
    "A", "THE", "OF", "WITH", "TO", "IN", "ON", "AND", "FOR", "OR", "AT", "BY", "PER", "IS",
    "LESS", "THAN", "DAY", "DAYS", "DUE", "DATE", "NEW", "CHECK", "CLOSE",
}


def palabras_de_la_descripcion(descripcion: str) -> list[str]:
    """Palabras que identifican el ítem en la DESCRIPTION de la tabla: las anteriores a la
    aclaración (" - " o paréntesis), sin números ni palabras genéricas.
    'TIRE PRESSURE RECHECK IN 24 HOURS (LOW PRESSURE)' -> TIRE, PRESSURE, RECHECK, HOURS."""
    cabeza = re.split(r"\s-\s|\(|\[", descripcion)[0]
    palabras = [p for p in normalizar(cabeza).split()
                if len(p) > 1 and not p.isdigit() and p not in _PALABRAS_GENERICAS]
    return list(dict.fromkeys(palabras))


def _entrada_automatica(fila: FilaReferencia, advertencias: list[str]) -> EntradaCatalogo:
    """Entrada para una fila que el catálogo no tiene. Así, agregar la fila a DIPs
    References.xlsx ya sirve: el DIP se reconoce si tiene todas las palabras de la
    DESCRIPTION o la referencia técnica de la fila, hasta que se escriba su entrada en el
    catálogo (con sinónimos y exclusiones)."""
    id_ = f"FILA_{fila.fila}"
    variantes, hasta_vencimiento, no_verificable = _variantes_de_la_tabla(
        id_, [fila], advertencias)
    return EntradaCatalogo(
        id=id_, nombre=fila.descripcion, referencias=[fila],
        requiere=[[p] for p in palabras_de_la_descripcion(fila.descripcion)], excluir=[],
        variantes=variantes, hasta_vencimiento=hasta_vencimiento,
        no_verificable=no_verificable and not variantes,
        ta_segun_manual=fila.ta if remite_al_manual(fila.ta) else "",
        rir_segun_manual=fila.rir if remite_al_manual(fila.rir) else "",
        automatica=True,
    )
