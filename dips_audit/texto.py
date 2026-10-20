"""Normalización de texto y extracción de datos (PSI, S/N, fechas) del Fault Name."""

from __future__ import annotations

import calendar
import re
import unicodedata
from datetime import date

# Errores de escritura y sinónimos frecuentes en el histórico. Se aplican sobre
# texto ya normalizado (mayúsculas, sin acentos, puntuación convertida a espacios).
_SINONIMOS: list[tuple[str, str]] = [
    (r"\bFIRT\b", "FIRST"),
    (r"\bFIRTS\b", "FIRST"),
    (r"\bOXIGEN\b", "OXYGEN"),
    (r"\bOXIGENO\b", "OXYGEN"),
    (r"\bOXY\b", "OXYGEN"),
    (r"\bO2\b", "OXYGEN"),
    (r"\bPREESURE\b", "PRESSURE"),
    (r"\bBELLOW\b", "BELOW"),
    (r"\bCERTICATE\b", "CERTIFICATE"),
    (r"\bCERTIFICTE\b", "CERTIFICATE"),
    (r"\bCERTIFICADO\b", "CERTIFICATE"),
    (r"\bFUMIGACION\b", "FUMIGATION"),
    (r"\bMEDICAL KID\b", "MEDICAL KIT"),
    (r"\bAID KID\b", "AID KIT"),
    (r"\bTRANSMITER\b", "TRANSMITTER"),
    (r"\bLIGHTING STRIKE\b", "LIGHTNING STRIKE"),
    (r"\bBREAK\b", "BRAKE"),
    (r"\bEXTINTOR\b", "EXTINGUISHER"),
    (r"\bEXTINGUIHSER\b", "EXTINGUISHER"),
    (r"\bEXTINGUISHERS\b", "EXTINGUISHER"),
    (r"\bFIRE EXT\b", "FIRE EXTINGUISHER"),
    (r"\bSQUIBS\b", "SQUIB"),
    (r"\bRE TENSION\b", "RETENSION"),
    (r"\bLIFE VEST\b|\bLIVEVEST\b|\bLIFE JACKET\b|\bLIFEJACKET\b", "LIFEVEST"),
    (r"\bTIRES\b|\bTYRES?\b", "TIRE"),
    (r"\bBRAKES\b", "BRAKE"),
    (r"\bSTRUTS\b", "STRUT"),
    (r"\bUNIVERSIAL\b|\bUNIVERVAL\b|\bUNIVERSAL\b", "UNIVERSAL"),
    (r"\bCOMMPRESED\b|\bCOMPRESED\b", "COMPRESSED"),
    (r"\bWIGHT\b", "WEIGHT"),
    # Siglas pegadas a su número: ELT2 -> ELT 2, FAK1 -> FAK 1, MLG3 -> MLG 3.
    (r"\b(ELT|FAK|EMK|UPK|MLG|NLG|ENG|POB)(\d)\b", r"\1 \2"),
]
_SINONIMOS_RE = [(re.compile(p), r) for p, r in _SINONIMOS]
_SIGLA_CON_PUNTOS = re.compile(r"\b(?:[A-Z]\.){2,}[A-Z]?\b\.?")

MESES = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
    # español
    "ENE": 1, "ABR": 4, "AGO": 8, "DIC": 12,
}
_MES = r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC|ENE|ABR|AGO|DIC)[A-Z]*"


def sin_acentos(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()


def normalizar(texto: object) -> str:
    """Mayúsculas, sin acentos, puntuación -> espacio, sinónimos aplicados."""
    if texto is None:
        return ""
    t = sin_acentos(str(texto)).upper()
    # Siglas escritas con puntos: P.O.B -> POB, E.L.T. -> ELT.
    t = _SIGLA_CON_PUNTOS.sub(lambda m: m.group(0).replace(".", ""), t)
    t = re.sub(r"[^A-Z0-9]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    for patron, reemplazo in _SINONIMOS_RE:
        t = patron.sub(reemplazo, t)
    return t


def contiene_frase(texto_normalizado: str, frase: str) -> bool:
    """True si la frase (normalizada) aparece como palabras completas."""
    f = normalizar(frase)
    if not f:
        return False
    return f" {f} " in f" {texto_normalizado} "


# --------------------------------------------------------------------------
# Extracción de datos del Fault Name
# --------------------------------------------------------------------------

def extraer_psi(texto: object) -> list[int]:
    """Valores de presión mencionados (p. ej. '950 PSI', '1.100 PSI', '1000PSI')."""
    t = sin_acentos(str(texto or "")).upper()
    valores = []
    for m in re.finditer(r"(\d{1,2}[.,]\d{3}|\d{2,4})[\s_]*PSI", t):
        valores.append(int(re.sub(r"[.,]", "", m.group(1))))
    return valores


_SN_NO_VALIDOS = {"DUE", "DATE", "INCORRECTO", "CORRECTO", "THE", "AND"}
_SN_FIN = "(?:" + "|".join(sorted(_SN_NO_VALIDOS)) + r"|[PS] */ *N\d?|[PS]N\d?)\b"
# Un número seguido de unidad o mes pertenece a la presión, al plazo o a la fecha,
# no al serial anterior. Las continuaciones numéricas sí pueden tener espacios.
_SN_MEDIDA_O_FECHA = (
    r"(?:\d{1,4}[-/]\d{1,2}[-/]\d{2,4}\b|\d{1,2}:\d{2}\b|\d+(?:[.,]\d+)?[ -]*"
    r"(?:PSI|FH|FC|HOURS?|HRS?|DAYS?|CDY|MONTHS?|CMON|CYCLES?|LANDINGS?|E/A|EA|"
    + "|".join(MESES) + r")[A-Z]*\b)"
)
_SN_RE = re.compile(
    r"\b(?:(?:S\s*/\s*N|SN)(?:\d(?=[\s:#.=]))?|SERIAL\s*(?:NO\.?|NUMBER)?)"
    r"\s*[:#.=\-]?\s*"
    r"([A-Z0-9]+(?: *- *(?!" + _SN_FIN + r")[A-Z0-9]+"
    r"|(?<=\d) +(?=\d)(?!" + _SN_MEDIDA_O_FECHA + r")[A-Z0-9]+)*)\b"
)
_PN_RE = re.compile(
    r"\b(?:(?:P\s*/\s*N|PN)(?:\d(?=[\s:#.=]))?|PART\s*(?:NO\.?|NUMBER))"
    r"\s*[:#.=]?\s*([A-Z0-9][A-Z0-9\-]{2,})\b"
)


def extraer_sn(texto: object) -> list[str]:
    """Seriales completos con prefijo S/N o SN, incluso con espacios entre dígitos o guiones."""
    t = sin_acentos(str(texto or "")).upper()
    encontrados = []
    for m in _SN_RE.finditer(t):
        sn = re.sub(r"\s+", "", m.group(1)).strip("-")
        if len(sn) >= 3 and sn not in _SN_NO_VALIDOS and any(c.isdigit() for c in sn):
            encontrados.append(sn)
    return encontrados


def clave_sn(sn: str) -> str:
    """Lo que identifica un S/N: sus dígitos. El mismo S/N se escribe con o sin letras y
    guiones (P11101989 / 11101989, 1234-AB / 1234)."""
    return re.sub(r"\D", "", str(sn or ""))


def clave_sn_completa(sn: str) -> str:
    """Identidad completa para duplicados: conserva letras y dígitos, omite espacios y guiones."""
    return re.sub(r"[^A-Z0-9]", "", sin_acentos(str(sn or "")).upper())


def extraer_pn(texto: object) -> list[str]:
    """P/N y P/N2 identifican partes, independientemente del S/N del componente."""
    t = sin_acentos(str(texto or "")).upper()
    return list(dict.fromkeys(m.group(1).strip("-") for m in _PN_RE.finditer(t)
                             if any(c.isdigit() for c in m.group(1))))


def _anio(valor: str) -> int:
    n = int(valor)
    return 2000 + n if n < 100 else n


def extraer_fechas(texto: object) -> list[date]:
    """Fechas de vencimiento mencionadas en el texto.

    Soporta '30-SEP-2026', '30 SEP 2026', '07/AUG/2026', '05AUG26', '16-JUL-26',
    'JULY 24 2026', '(19 Jul 2026)' y mes-año ('Sep-2026' -> último día del mes).
    """
    t = sin_acentos(str(texto or "")).upper()
    fechas: list[date] = []
    usados: list[tuple[int, int]] = []

    def agregar(m: re.Match, d: int, mes: str, a: str) -> None:
        try:
            fechas.append(date(_anio(a), MESES[mes[:3]], d))
            usados.append(m.span())
        except (ValueError, KeyError):
            pass

    # día-mes-año. El día puede venir con la letra O en vez de cero ('O3-FEB-2027') o pegado
    # a la palabra anterior ('DATED09-OCT-2026'): es una fecha exacta, no un mes-año.
    for m in re.finditer(rf"(?<!\d)([\dO]{{1,2}})\s*[-/ ]?\s*{_MES}\s*[-/ ,]?\s*(\d{{4}}|\d{{2}})\b", t):
        dia = m.group(1).replace("O", "0")
        if dia.strip("0"):
            agregar(m, int(dia), m.group(2), m.group(3))
    # mes día año (JULY 24 2026)
    for m in re.finditer(rf"\b{_MES}\s+(\d{{1,2}})\s*,?\s+(\d{{4}})\b", t):
        if not _solapa(m.span(), usados):
            agregar(m, int(m.group(2)), m.group(1), m.group(3))
    # mes-año (SEP-2026) -> último día del mes
    for m in re.finditer(rf"\b{_MES}\s*[-/ ]\s*(\d{{4}})\b", t):
        if not _solapa(m.span(), usados):
            try:
                anio, mes = int(m.group(2)), MESES[m.group(1)[:3]]
                fechas.append(date(anio, mes, calendar.monthrange(anio, mes)[1]))
            except (ValueError, KeyError):
                pass
    return fechas


def _solapa(span: tuple[int, int], usados: list[tuple[int, int]]) -> bool:
    return any(span[0] < fin and ini < span[1] for ini, fin in usados)


_POSICIONES = {
    "FWD", "AFT", "LH", "RH", "LEFT", "RIGHT", "UPPER", "LOWER", "L", "R",
    "COCKPIT", "GALLEY", "BIN", "OVH", "NOSE", "MAIN", "INITIAL", "TERMINAL",
}


def posiciones(texto_normalizado: str) -> frozenset[str]:
    """Tokens que distinguen componentes gemelos (FWD/AFT, LH/RH, #1/#2...).

    Se usan para no marcar como duplicados dos DIPs de componentes distintos.
    """
    tokens = set()
    for tok in texto_normalizado.split():
        if tok in _POSICIONES:
            tokens.add({"LEFT": "LH", "RIGHT": "RH", "L": "LH", "R": "RH"}.get(tok, tok))
        elif tok.isdigit() and len(tok) == 1:
            tokens.add(tok)
    return frozenset(tokens)


_REF_TECNICA_RE = re.compile(
    r"\b(AMM|SRM|FIM|IPC|ECRA|EC|EA|RA|TASK CARD)\b[\s:]*(TASK|SUBTASK)?\s*[A-Z0-9]*\d{2}-\d{2}",
)


def menciona_referencia_tecnica(texto: object) -> bool:
    t = sin_acentos(str(texto or "")).upper()
    return bool(_REF_TECNICA_RE.search(t)) or bool(re.search(r"\b(B737|MAX)-\d{2}-\d-\d{4}", t))
