"""Reglas de auditoría. Cada regla devuelve hallazgos con evidencia verificable."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from rapidfuzz.distance import Levenshtein

from .discrepancias import Discrepancias
from .estados import ACTIVOS
from .inventario import cruzar
from .partes import es_squib, verificar_squib
from .referencias import EntradaCatalogo, Limite, Variante
from .rir import solo_rir
from .texto import (clave_sn, clave_sn_completa, extraer_fechas, extraer_psi, extraer_sn,
                    normalizar, posiciones)

POSIBLE_DISCREPANCIA = "POSIBLE DISCREPANCIA"
# El DIP no está en la tabla de referencias: no hay contra qué auditarlo. Una posible
# discrepancia que no depende de la tabla (vencido, cierre tarde...) pesa más.
SIN_FUENTE = "SIN FUENTE EN DIPS REFERENCES"
# La tabla da el TA o el RIR según el daño o el tipo ("DEPENDING ON...", "CONSULT REF."):
# el auditor lo revisa en el manual. Una posible discrepancia pesa más.
REVISAR = "REVISAR"
EXTENSION = "EXTENSIÓN"
SEVERIDAD_SIN_FUENTE = SIN_FUENTE
# Una discrepancia pesa más que la revisión de una extensión, la consulta al manual
# o la falta de fuente. Los detalles OK se anotan sin cambiar el resultado.
ORDEN_SEVERIDAD = {POSIBLE_DISCREPANCIA: 5, EXTENSION: 4, REVISAR: 3, SIN_FUENTE: 2, "OK": 1}
ESTADOS = {
    POSIBLE_DISCREPANCIA: POSIBLE_DISCREPANCIA,
    EXTENSION: EXTENSION,
    REVISAR: REVISAR,
    SIN_FUENTE: SIN_FUENTE,
    "OK": "OK",
}
# Cómo se muestra cada hallazgo según su severidad.
MOSTRAR_SEVERIDAD = ESTADOS.copy()
# Cada DIP se audita dos veces: al abrirse (APERTURA) y al cerrarse (CIERRE). Estos códigos
# son de la auditoría de cierre; todos los demás, de la de apertura.
CODIGOS_CIERRE = {
    "completado_fuera_de_plazo", "cierre_sin_accion_correctiva", "cierre_sin_referencia_tecnica",
    "cierre_referencia_incompleta", "cierre_sn_distinto", "cierre_deadline_extendido",
    "cierre_sin_adjuntos", "cierre_antes_de_ventana",
}


def etapa(codigo: str) -> str:
    return "CIERRE" if codigo in CODIGOS_CIERRE else "APERTURA"


@dataclass
class Hallazgo:
    codigo: str       # regla en config/discrepancias.yaml (p. ej. intervalo_excedido)
    categoria: str    # tipo de discrepancia (nomenclatura del departamento)
    severidad: str    # Valor en config/discrepancias.yaml; OK no cambia el resultado.
    mensaje: str


@dataclass
class Contexto:
    fecha_referencia: datetime | date   # día y hora de la auditoría (fecha sola = inicio del día)
    discrepancias: Discrepancias = field(default_factory=Discrepancias)
    tol_dias: int = 1
    horas_cierre: float = 0      # tolerancia del cierre (Complete Dt en UTC, due en hora local)
    meses_min: int = 30
    meses_max: int = 31
    revision_opcional: frozenset[str] = frozenset()  # manuales cuya cita no pide REV ni fecha
    # Diferencia aceptada entre el Start de un T/A por uso y el uso al encontrar la falla.
    inicio_fh: float = 2
    inicio_fc: float = 0


@dataclass
class ResultadoReglas:
    hallazgos: list[Hallazgo] = field(default_factory=list)
    manuales: list[str] = field(default_factory=list)
    intervalo_ok: bool | None = None
    variante: str = ""

    def agregar(self, ctx: Contexto, codigo: str, categoria: str, mensaje: str,
                severidad: str | None = None) -> None:
        """Agrega el hallazgo si su regla y su tipo están activos. `severidad` fija la
        severidad sin importar la configuración (casos especiales de una regla)."""
        d = ctx.discrepancias
        if d.activa(codigo, categoria):
            self.hallazgos.append(Hallazgo(codigo, d.tipo(codigo, categoria),
                                           severidad or d.severidad(codigo), mensaje))


def _fmt(valor: float | None) -> str:
    if valor is None:
        return "?"
    return str(int(valor)) if float(valor).is_integer() else f"{valor:g}"


def _fecha(d: datetime | date | None) -> str:
    return d.strftime("%d-%b-%Y").upper() if d else "?"


def _fecha_hora(d: datetime | date | None) -> str:
    if isinstance(d, datetime) and d.time() != time():
        return f"{_fecha(d)} {d:%H:%M}"
    return _fecha(d)


def como_fecha_hora(d: datetime | date | None) -> datetime | None:
    """Una fecha sin hora cuenta desde el inicio del día."""
    if d is None or isinstance(d, datetime):
        return d
    return datetime.combine(d, time())


def _fin_del_plazo(due: datetime | date) -> datetime:
    """Un due date sin hora vence al final del día."""
    if isinstance(due, datetime) and due.time() != time():
        return due
    return datetime.combine(due if not isinstance(due, datetime) else due.date(), time.max)


def _como_fecha(d: datetime | date | None) -> date | None:
    if d is None:
        return None
    return d.date() if isinstance(d, datetime) else d


def referencia_y_adjunto_exigibles(dip: dict) -> bool:
    """Solo DIPs diferidos desde el 9-jul-2026 requieren este control."""
    diferido = _como_fecha(dip.get("defer_date"))
    return diferido is not None and diferido >= date(2026, 7, 9)


def _inicio_ta(dip: dict) -> date | None:
    """Start del T/A en días calendario según ICAM ('26-SEP-2026 23:59 UTC'); None sin dato."""
    for i in dip.get("icam_intervalos") or []:
        if (i.get("unit") or "").upper() in ("DAY", "DAYS", "CDY") or \
                (i.get("parameter") or "").upper() == "CDY":
            m = re.search(r"\d{2}-[A-Z]{3}-\d{4}", i.get("start") or "")
            if m:
                return datetime.strptime(m.group(0), "%d-%b-%Y").date()
    return None


# Unidad del DIP -> parámetro del T/A en ICAM, y al revés.
_PARAMETRO = {"FH": "HOURS", "FC": "CYCLES"}
_UNIDAD_PARAMETRO = {"CDY": "DAY", "DAY": "DAY", "HOURS": "FH", "HOUR": "FH", "CYCLES": "FC", "CYCLE": "FC"}


def _inicio_ta_uso(dip: dict, unidad: str) -> list[float]:
    """Start de un T/A por uso (FH, FC) en ICAM: 'Aircraft 14496 / Component 14496' ->
    [14496, 14496]. En un motor viene también el uso del avión: se devuelven todos."""
    for i in dip.get("icam_intervalos") or []:
        if (i.get("parameter") or "").upper() == _PARAMETRO[unidad]:
            return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", i.get("start") or "")]
    return []


def _corrido_uso(dip: dict, unidad: str, cerca_de: float = 0) -> float | None:
    """Cuánto después del uso al encontrar la falla empieza un T/A por uso (FH, FC) en ICAM;
    negativo si empieza antes. En un motor se toma el contador más cercano a `cerca_de`.
    None sin dato, o si el Start es de otro contador (motor contra avión)."""
    uso = (dip.get("uso_encontrado") or {}).get(_PARAMETRO[unidad])
    starts = _inicio_ta_uso(dip, unidad)
    if uso is None or uso <= 0 or not starts:
        return None
    corrido = min((x - uso for x in starts), key=lambda d: abs(d - cerca_de))
    return None if abs(corrido - cerca_de) > 10 * max(dip["intervalo"] or 1, 1) else corrido


def _corrido(dip: dict, unidad: str) -> float | None:
    """Cuánto después de la apertura empieza el T/A en ICAM, en la unidad del DIP (días o
    FH/FC); negativo si empieza antes. None sin dato."""
    if unidad == "DAY":
        inicio, found = _inicio_ta(dip), _como_fecha(dip["found_date"])
        return None if inicio is None or found is None else (inicio - found).days
    return _corrido_uso(dip, unidad) if unidad in _PARAMETRO else None


def _tolerancia(unidad: str, ctx: Contexto) -> float:
    return ctx.tol_dias if unidad == "DAY" else ctx.inicio_fh if unidad == "FH" else ctx.inicio_fc


def _plazo_maximo(dip: dict, entrada: EntradaCatalogo, ctx: Contexto) -> float | None:
    """Plazo más largo que da la referencia contado desde la apertura, en la unidad del DIP
    (con ventana "AFTER A, BEFORE B", B). None si no lo da en esa unidad."""
    rangos = [_rango_limite(lim, dip["unidad"], ctx)
              for v in _variantes_aplicables(dip, entrada) for lim in v.limites]
    return max((x[1] for x in rangos if x), default=None)


def _rango_limite(lim: Limite, unidad_dip: str, ctx: Contexto) -> tuple[float, float] | None:
    """Rango aceptado para el valor del DIP según un límite de la referencia."""
    if lim.unidad == "MONTH":
        if unidad_dip != "DAY":
            return None
        return (lim.valor * ctx.meses_min - ctx.tol_dias, lim.valor * ctx.meses_max + ctx.tol_dias)
    if lim.unidad != unidad_dip:
        return None
    # El intervalo del DIP es un número que se escribe a mano: se compara exacto.
    return (lim.valor, lim.valor)


# --------------------------------------------------------------------------
# Reglas individuales
# --------------------------------------------------------------------------

def _misma_flota(flota: str, flotas: list[str]) -> bool:
    """'NG' (sin modelo conocido) aplica a cualquier variante NG-700/800/900."""
    return flota in flotas or (flota == "NG" and any(f.startswith("NG") for f in flotas))


def _variantes_aplicables(dip: dict, entrada: EntradaCatalogo) -> list[Variante]:
    """Variantes de la referencia que valen para la flota del DIP (todas si no se sabe)."""
    flota = dip.get("flota")
    if flota and any(v.flotas for v in entrada.variantes):
        return [v for v in entrada.variantes if not v.flotas or _misma_flota(flota, v.flotas)]
    return list(entrada.variantes)


def _ventana(dip: dict, entrada: EntradaCatalogo | None) -> tuple[Variante, Limite] | None:
    """Variante con ventana "AFTER A, BEFORE B" en la unidad del DIP, y su límite B.

    Solo si el T/A está armado para esa ventana (intervalo B - A o B). Con otro intervalo es
    otro trabajo sobre el mismo ítem: "NLG STRUT COMPRESSED UNDER 5 INCHES" en 4 FC no es el
    chequeo del amortiguador después del servicio, y empieza en la apertura."""
    if entrada is None or dip["unidad"] is None:
        return None
    for v in _variantes_aplicables(dip, entrada):
        for lim in v.limites:
            desde_inicio = v.intervalo_desde_inicio(lim)
            if lim.unidad == dip["unidad"] and desde_inicio is not None \
                    and dip["intervalo"] in (desde_inicio, lim.valor):
                return v, lim
    return None


def regla_intervalo(dip: dict, entrada: EntradaCatalogo, ctx: Contexto, r: ResultadoReglas) -> None:
    if solo_rir(dip):
        return
    valor, unidad = dip["intervalo"], dip["unidad"]
    if valor is None or unidad is None:
        if dip.get("rirs") and (entrada.no_verificable or not entrada.variantes):
            # Solo sigue un RIR y la tabla no da plazo (EXHAUST PLUG CRACK: TA "-").
            r.manuales.append("DIP sin T/A: solo sigue el RIR. Verificar contra la referencia "
                              f"('{'; '.join(x.ta for x in entrada.referencias)}').")
            return
        r.agregar(ctx, "datos_incompletos", "Deferral Interval Not Documented",
                  f"Sin intervalo válido en el Excel ('{_fmt(valor)}' "
                  f"'{dip['tipo_intervalo_original']}').")
        r.intervalo_ok = False
        return
    if valor <= 0:
        r.agregar(ctx, "intervalo_cero", "Incorrect DIP Interval",
                  f"T/A aperturado con intervalo {_fmt(valor)} {unidad}.")
        r.intervalo_ok = False
        return

    if entrada.hasta_vencimiento:
        if unidad != "DAY":
            r.agregar(ctx, "tipo_intervalo_incorrecto", "Incorrect DIP Interval",
                      f"T/A en {_fmt(valor)} {unidad}; la referencia es UNTIL DUE DATE.")
            r.intervalo_ok = False
        else:
            r.intervalo_ok = True
        return

    if entrada.ta_segun_manual:
        manual = entrada.referencias_tecnicas
        r.agregar(ctx, "intervalo_segun_manual", "Incorrect DIP Interval",
                  f"T/A con {_fmt(valor)} {unidad}; la referencia lo da según el daño o el tipo "
                  f"('{entrada.ta_segun_manual}'). Revisar en el manual"
                  + (f" ({manual})." if manual else "."))
        return

    if entrada.no_verificable or not entrada.variantes:
        r.manuales.append(f"Intervalo: verificar manualmente contra la referencia "
                          f"('{'; '.join(x.ta for x in entrada.referencias)}').")
        return

    flota = dip.get("flota")
    aplicables = _variantes_aplicables(dip, entrada)
    if any(v.flotas for v in entrada.variantes) and not flota:
        r.manuales.append("No se pudo determinar la flota del avión; se aceptó el "
                          "intervalo de cualquier flota.")
    if not aplicables:
        r.manuales.append(f"La referencia no define intervalo para la flota {flota}.")
        return

    coincidentes: list[tuple[Variante, Limite]] = []
    maximo: tuple[float, Limite] | None = None
    for v in aplicables:
        for lim in v.limites:
            rango = _rango_limite(lim, unidad, ctx)
            if rango is None:
                continue
            # Con ventana "AFTER A, BEFORE B" el T/A dura B - A desde su Start. B también se
            # acepta aquí: regla_inicio_ta revisa desde dónde cuenta.
            if rango[0] <= valor <= rango[1] or valor == v.intervalo_desde_inicio(lim):
                coincidentes.append((v, lim))
            if maximo is None or rango[1] > maximo[0]:
                maximo = (rango[1], lim)

    texto_ref = "; ".join(
        " o ".join(str(l) for l in v.limites) + (f" [{', '.join(v.flotas)}]" if v.flotas else "")
        + (f", empezando {v.inicio} después de la apertura" if v.inicio else "")
        for v in aplicables)

    if maximo is None:
        r.agregar(ctx, "tipo_intervalo_incorrecto", "Incorrect DIP Interval",
                  f"T/A en {_fmt(valor)} {unidad}; la referencia indica {texto_ref}.")
        r.intervalo_ok = False
        return

    if coincidentes:
        r.intervalo_ok = True
        variante = coincidentes[0][0]
        r.variante = variante.nombre
        if len(aplicables) > 1 and len({l.valor for v in aplicables for l in v.limites
                                        if l.unidad == unidad}) > 1:
            psi = extraer_psi(dip["nombre"] + " " + dip["descripcion"])
            extra = f" Presión reportada: {', '.join(map(str, psi))} PSI." if psi else ""
            r.agregar(ctx, "variante_condicional", "Incorrect DIP Interval",
                      f"El intervalo {_fmt(valor)} {unidad} corresponde a la condición "
                      f"'{variante.nombre}'. Verificar que aplique.{extra}")
        if len(variante.limites) > 1:
            # Con ICAM se ve el T/A completo; el Excel solo trae el límite que vence primero.
            en_ta = {_UNIDAD_PARAMETRO.get((i.get("parameter") or "").upper())
                     for i in dip.get("icam_intervalos") or []}
            faltan = [l for l in variante.limites
                      if ("DAY" if l.unidad == "MONTH" else l.unidad) not in en_ta]
            limites = " o ".join(str(l) for l in variante.limites)
            if dip.get("icam_intervalos") and faltan:
                r.agregar(ctx, "limite_faltante", "Incorrect DIP Interval",
                          f"T/A sin {' ni '.join(map(str, faltan))}; la referencia pide {limites}.")
            elif not dip.get("icam_intervalos"):
                r.manuales.append(f"Verificar límite dual en ICAM: {limites} (lo que ocurra primero).")
        if variante.rir:
            r.manuales.append(f"Verificar RIR cada {variante.rir}.")
        return

    r.intervalo_ok = False
    if valor > maximo[0]:
        # Solo importa si de verdad vence después: un T/A que empieza antes de la apertura
        # con más intervalo puede vencer dentro del TA (el Start lo revisa regla_inicio_ta).
        # Sin el Start de ICAM se cuenta desde la apertura.
        corrido = _corrido(dip, unidad)
        if corrido is not None and corrido + valor <= maximo[0] + _tolerancia(unidad, ctx):
            return
        r.agregar(ctx, "intervalo_excedido", "Incorrect DIP Interval",
                  f"T/A con {_fmt(valor)} {unidad}; la referencia indica {texto_ref}.")
    else:
        r.agregar(ctx, "intervalo_menor", "Incorrect DIP Interval",
                  f"T/A con {_fmt(valor)} {unidad}; la referencia indica {texto_ref}.")


def regla_inventario(dip: dict, due: date, ctx: Contexto, r: ResultadoReglas) -> bool:
    """Generators de oxígeno: el due date es el Exp. Date (fin de mes) del PDF de inventario
    adjunto. Los generators del DIP son los que tienen su barcode en DIP Barcode y los de los
    S/N de la descripción; manda el que vence primero. False si no hay con qué auditarlo (se
    usa la fecha de la descripción)."""
    inventario = dip.get("inventario")
    if inventario is None:
        r.manuales.append("Verificar el due date contra el Exp. Date del PDF de inventario de "
                          "generators (attachment).")
        return False
    if not inventario["generadores"]:
        if inventario["errores"]:
            r.manuales.append("No se pudo leer el PDF adjunto ("
                              + "; ".join(f"{n}: {e}" for n, e in inventario["errores"].items())
                              + "): verificar el Exp. Date de cada S/N.")
        elif inventario["archivos"]:
            r.manuales.append(f"PDF adjunto sin el inventario en campos de formulario "
                              f"({', '.join(inventario['archivos'])}): verificar el Exp. Date "
                              f"de cada S/N.")
        else:
            if referencia_y_adjunto_exigibles(dip):
                r.agregar(ctx, "sin_inventario_generadores", "Missing Attachment",
                          "Sin el PDF de inventario de generators en los attachments.")
        return False
    cruce = cruzar(inventario["generadores"], dip["barcode"],
                   f"{dip['nombre']}\n{dip['descripcion']}")
    for sn in cruce.sn_fuera:
        r.agregar(ctx, "sn_fuera_de_inventario", "Incorrect S/N",
                  f"S/N {sn} no está en el inventario (PDF).")
    g = cruce.primero
    if g is None:
        r.manuales.append("Ningún generator del inventario (PDF) tiene el S/N del DIP ni su "
                          "barcode en DIP Barcode: verificar el Exp. Date.")
        return False
    fuente = f"inventario: {g.posicion} S/N {g.sn}, Exp. Date {g.vence_texto}"
    if due > g.vence:
        r.agregar(ctx, "due_date_posterior_a_vencimiento_item", "Incorrect Due Date",
                  f"Due date {_fecha(due)}, después del vencimiento del ítem "
                  f"({_fecha(g.vence)}; {fuente}).")
    elif (g.vence - due).days > ctx.tol_dias:
        r.agregar(ctx, "due_date_anterior_a_vencimiento_item", "Incorrect Due Date",
                  f"Due date {_fecha(due)}, antes del vencimiento del ítem "
                  f"({_fecha(g.vence)}; {fuente}).")
    return True


def regla_extension(dip: dict, ctx: Contexto, r: ResultadoReglas) -> None:
    """Una extensión documentada queda para revisión, tanto abierta como cerrada."""
    if solo_rir(dip):
        return
    detalles = []
    original, due = dip.get("orig_due_date"), dip.get("due_date")
    if original and due and _fin_del_plazo(original) < _fin_del_plazo(due):
        detalles.append(f"due date {_fecha_hora(due)}; original {_fecha_hora(original)}")
    for intervalo in dip.get("icam_intervalos") or []:
        extension = str(intervalo.get("extension") or "")
        valor = re.search(r"-?\d+(?:[.,]\d+)?", extension)
        if valor and float(valor.group().replace(",", ".")) > 0:
            unidad = intervalo.get("unit") or intervalo.get("parameter") or ""
            detalle = f"T/A con extensión {extension} {unidad}".strip()
            if intervalo.get("extended_deadline"):
                detalle += f" (deadline extendido {intervalo['extended_deadline']})"
            detalles.append(detalle)
    if detalles and ctx.discrepancias.activa("dip_extendido", "Deadline Extension"):
        r.agregar(ctx, "dip_extendido", "Deadline Extension",
                  "DIP con extensión: " + "; ".join(detalles) + ".")
        r.manuales.append("Revisar la extensión del DIP y su soporte de autorización: "
                          + "; ".join(detalles) + ".")


def regla_fechas(dip: dict, entrada: EntradaCatalogo | None, ctx: Contexto,
                 r: ResultadoReglas) -> None:
    if solo_rir(dip):
        if dip["estado"] == "COMPLETE":
            regla_cierre(dip, ctx, r, entrada)
        return
    due, found = _como_fecha(dip["due_date"]), _como_fecha(dip["found_date"])
    valor, unidad, estado = dip["intervalo"], dip["unidad"], dip["estado"]
    original = dip.get("orig_due_date")
    extendido = (original and dip["due_date"]
                 and _fin_del_plazo(original) < _fin_del_plazo(dip["due_date"]))
    due_ta = _como_fecha(original) if extendido else due
    nombre_due = "Due date original" if extendido else "Due date"

    if dip.get("correccion_fecha"):
        r.manuales.append(dip["correccion_fecha"] + ".")

    # Due date coherente con el inicio del T/A + intervalo (solo días). El T/A cuenta desde
    # su Start en ICAM, que puede ser posterior a la apertura; sin datos de ICAM, desde la
    # apertura. Si hay extensión, la coherencia del T/A se revisa con el due date original.
    # En los ítems con vencimiento el due date es el del ítem.
    hasta_vencimiento = entrada is not None and entrada.hasta_vencimiento
    if due and found and valor is not None and unidad == "DAY" and not hasta_vencimiento:
        inicio = _inicio_ta(dip)
        # Sin ICAM, un T/A armado con la ventana "AFTER A, BEFORE B" en días cuenta desde la apertura + A.
        ventana = _ventana(dip, entrada)
        retraso = (int(ventana[0].inicio.valor) if ventana and not inicio
                   and valor == ventana[0].intervalo_desde_inicio(ventana[1]) else 0)
        base = inicio or found + timedelta(days=retraso)
        desde = (f"Start del T/A {_fecha(base)}" if inicio
                 else f"apertura + {retraso} DAY" if retraso
                 else f"apertura {_fecha(base)}")
        esperado = base + timedelta(days=valor)
        diferencia = (due_ta - esperado).days
        if diferencia > ctx.tol_dias:
            r.agregar(ctx, "due_date_posterior_a_intervalo", "Incorrect Due Date",
                      f"{nombre_due} {_fecha(due_ta)}; corresponde {_fecha(esperado)} ({desde} "
                      f"+ {_fmt(valor)} DAY)."
                      + ("" if inicio else " Verificar el Start del T/A."))
        elif diferencia < -ctx.tol_dias:
            r.agregar(ctx, "due_date_anterior_a_intervalo", "Incorrect Due Date",
                      f"{nombre_due} {_fecha(due_ta)}; corresponde {_fecha(esperado)} ({desde} "
                      f"+ {_fmt(valor)} DAY).")

    # Ítems con vencimiento: el due date no puede superar la fecha del ítem. En los generators
    # de oxígeno la fecha es la del PDF de inventario; sin el PDF, la de la descripción.
    if (entrada is not None and entrada.hasta_vencimiento and due_ta
            and not (entrada.inventario and regla_inventario(dip, due_ta, ctx, r))):
        texto = dip["nombre"] + " " + dip["descripcion"]
        fechas = sorted(f for f in extraer_fechas(texto) if not found or f >= found)
        if fechas:
            vence = fechas[0]
            if due_ta > vence:
                r.agregar(ctx, "due_date_posterior_a_vencimiento_item", "Incorrect Due Date",
                          f"{nombre_due} {_fecha(due_ta)}, después del vencimiento del ítem "
                          f"({_fecha(vence)}).")
            elif (vence - due_ta).days > ctx.tol_dias:
                r.agregar(ctx, "due_date_anterior_a_vencimiento_item", "Incorrect Due Date",
                          f"{nombre_due} {_fecha(due_ta)}, antes del vencimiento del ítem "
                          f"({_fecha(vence)}).")
        else:
            r.manuales.append("Verificar en el attachment la fecha de vencimiento del ítem "
                              "y que coincida con el due date del DIP.")

    # Vencido / completado fuera de plazo.
    activo = estado in ACTIVOS
    auditoria = como_fecha_hora(ctx.fecha_referencia)
    if activo and dip["due_date"] and _fin_del_plazo(dip["due_date"]) < auditoria:
        r.agregar(ctx, "dip_vencido", "Overdue DIP",
                  f"DIP vencido: due date {_fecha_hora(dip['due_date'])}.")
    elif activo and dip["usage_remaining"] is not None and dip["usage_remaining"] < 0:
        r.agregar(ctx, "dip_vencido", "Overdue DIP",
                  f"DIP vencido: Usage Remaining {_fmt(dip['usage_remaining'])}.")

    if estado == "COMPLETE":
        regla_cierre(dip, ctx, r, entrada)

    # Usage Remaining mayor que el intervalo: el T/A de scheduling no coincide.
    rem = dip["usage_remaining"]
    if activo and rem is not None and valor is not None:
        tol = ctx.tol_dias if unidad == "DAY" else 0
        if rem > valor + tol:
            r.agregar(ctx, "usage_remaining_mayor_a_intervalo", "Incorrect DIP Interval",
                      f"Usage Remaining {_fmt(rem)}, mayor que el intervalo "
                      f"({_fmt(valor)} {unidad}).")


# Acción correctiva que remite a otra tarea: "CLOSED IN REFERENCE BARCODE [T40S009H0DK]",
# "ACCOMPLISHED IN THIS BARCODE TRF7N0071057".
_OTRA_TAREA = re.compile(r"\b(?:T40S|TRF7)[0-9A-Z]{6,}\b", re.I)
# Cierre sin trabajo: abierto por error, ya hecho antes o sin acción de mantenimiento.
_SIN_TRABAJO = re.compile(
    r"MISTAKE|BY ERROR|DUPLICAT|PREVIOUS(?:LY)?\s+(?:ACCOMPLISHED|REPLACED|PERFORMED|DONE)"
    r"|NO(?:T)?\s+(?:REQUIRE[DS]?\s+)?(?:FURTHER\s+)?(?:MAINT(?:ENANCE)?\.?\s+)?(?:FURTHER\s+)?ACTION"
    r"|NO\s+ANOMAL", re.I)


# El técnico dice que el DIP se creó por error o está duplicado: en la acción correctiva
# ("ENTERED BY MISTAKE", "DIP OPEN BY MISTAKE IN WRONG WP", "DUPLICATED DIP") o en el nombre,
# la descripción o las notas de la descripción ("DIP DUPLICADO, VER BC T40S009J3HP"). En esos
# textos, "BY MISTAKE" suelto puede ser la falla ("OXYGEN MASK DEPLOYED BY MISTAKE"): tiene que
# referirse al DIP.
_POR_ERROR_ACCION = re.compile(
    r"DUPLICA[DT]|BY\s+(?:MISTAKE|ERROR)|POR\s+(?:ERROR|EQUIVOCACI)|MISTAKENLY|ERRONEOUSLY", re.I)
_POR_ERROR_DIP = re.compile(
    r"\b(?:DIP|ITEM|FAULT|DEFERRAL)\b[^.\n]{0,30}?(?:DUPLICA[DT]|BY\s+(?:MISTAKE|ERROR)"
    r"|POR\s+(?:ERROR|EQUIVOCACI))|\bDUPLICA[DT]\w*\s+(?:DIP|ITEM|FAULT)\b", re.I)


def dip_por_error(dip: dict) -> str | None:
    """Comentario si el técnico marcó el DIP como duplicado o creado por error; None si no."""
    accion = re.sub(r"^\s*\d+\.\s[^\n]*UTC\s*", "", dip.get("accion_correctiva") or "")
    textos = [dip.get("nombre"), dip.get("descripcion"), dip.get("notas_descripcion"),
              *(dip.get("auditoria_manual") or [])]
    candidatos = ([accion] if _POR_ERROR_ACCION.search(accion) else [])
    candidatos += [t for t in textos if t and _POR_ERROR_DIP.search(str(t))]
    if not candidatos:
        return None
    # Una declaración de duplicado no se pierde por una acción genérica "BY MISTAKE".
    texto = next((t for t in candidatos if re.search(r"DUPLICA[DT]", str(t), re.I)), candidatos[0])
    duplicado = re.search(r"DUPLICA[DT]", str(texto), re.I)
    otro = next((b.upper() for b in _OTRA_TAREA.findall(str(texto))
                 if b.upper() != (dip.get("barcode") or "").upper()), None)
    mensaje = ("DIP duplicado" if duplicado else "DIP creado por error") + (
        f" (ver {otro})" if otro else "")
    if dip.get("estado") in ACTIVOS:
        return mensaje + "; sigue abierto."
    return mensaje + "."


def regla_cierre(dip: dict, ctx: Contexto, r: ResultadoReglas,
                 entrada: EntradaCatalogo | None = None) -> None:
    """Auditoría de cierre: fecha de cierre, acción correctiva y S/N removido."""
    completo, due = dip.get("complete_date"), dip["due_date"]
    original = dip.get("orig_due_date")
    accion = dip.get("accion_correctiva")
    # Primera línea: "1. NOMBRE (Technician), 09-SEP-2026 17:27 UTC".
    texto = re.sub(r"^\s*\d+\.\s[^\n]*UTC\s*", "", accion or "")
    otra_tarea = _OTRA_TAREA.search(texto)
    sin_ta = solo_rir(dip)
    if completo and due and not sin_ta:
        # En un DIP cerrado, Usage Remaining es lo que le quedaba al cerrarlo (ICAM): negativo =
        # se cerró tarde. Sin ese dato, se compara la hora de cierre con el due date.
        restante = dip.get("usage_remaining")
        limite = _fin_del_plazo(due) + timedelta(hours=ctx.horas_cierre)
        tarde = restante < 0 if restante is not None else completo > limite
        if tarde and otra_tarea:
            # El trabajo se hizo en otra tarea: la fecha que cuenta es la de esa tarea.
            r.manuales.append(f"Cerrado después del due date en otra tarea ({otra_tarea.group(0)}): "
                              "verificar ahí la fecha en que se hizo el trabajo.")
        elif tarde:
            r.agregar(ctx, "completado_fuera_de_plazo", "Late Completion",
                      f"Cerrado el {_fecha_hora(completo)}, después del due date "
                      f"{_fecha_hora(due)}.")
        elif (original and _fin_del_plazo(original) < _fin_del_plazo(due)
              and _fin_del_plazo(original) + timedelta(hours=ctx.horas_cierre) < completo):
            r.agregar(ctx, "cierre_deadline_extendido", "Deadline Extension",
                      f"Cerrado el {_fecha_hora(completo)} dentro del plazo extendido "
                      f"(due date {_fecha_hora(due)}; original {_fecha_hora(original)}).")
    elif not completo and not sin_ta:
        r.manuales.append("DIP COMPLETE: verificar en ICAM que se cerró dentro del plazo.")
    if not sin_ta:
        _cierre_antes_de_ventana(dip, entrada, ctx, r)
    # "A new ... deadline has been added" es la apertura del T/A, no un cambio.
    cambios = [c for c in dip.get("cambios_deadline") or []
               if not re.search(r"deadline has been added", c, re.I)]
    if cambios and not sin_ta:
        r.manuales.append("Cambios de deadline en History: " + " | ".join(cambios))

    if accion is not None and referencia_y_adjunto_exigibles(dip):  # None = no se leyó ICAM
        from .referencia_tecnica import buscar_referencia, cita_mgm

        encontrada = buscar_referencia(texto)
        if not texto.strip():
            r.agregar(ctx, "cierre_sin_accion_correctiva", "Missing Technical Reference",
                      "DIP cerrado sin acción correctiva.")
        elif not encontrada.manual and otra_tarea:
            # El trabajo se hizo en otra tarea: la referencia técnica está en esa tarea.
            r.manuales.append(f"Cierre en otra tarea ({otra_tarea.group(0)}): verificar ahí la "
                              "referencia técnica.")
        elif not encontrada.manual and _SIN_TRABAJO.search(texto):
            r.manuales.append(f"Cerrado sin trabajo de mantenimiento: '{texto.strip()[:120]}'.")
        elif not encontrada.manual:
            r.agregar(ctx, "cierre_sin_referencia_tecnica", "Missing Technical Reference",
                      "Acción correctiva sin referencia técnica"
                      + (" (el MGM no es referencia técnica)." if cita_mgm(texto) else "."))
        elif encontrada.faltantes_exigidos(ctx.revision_opcional):
            r.agregar(ctx, "cierre_referencia_incompleta", "Missing Technical Reference",
                      f"Acción correctiva con referencia técnica sin "
                      f"{' ni '.join(encontrada.faltantes_exigidos(ctx.revision_opcional))} "
                      f"({encontrada}).")

    # En un cambio (botella, generator) la descripción puede nombrar el que se quitó o el
    # que se puso: vale cualquiera de los dos de Part Requirements.
    # ICAM mezcla Serial No y Batch No en una misma columna. Un lote BN no es un S/N.
    def es_serie(sn: str) -> bool:
        return bool(clave_sn(sn)) and not re.match(r"\s*(?:BN|BATCH\s*(?:NO|NUMBER)?)\b", sn, re.I)

    removidos = [sn for _, sn in dip.get("sn_removidos") or [] if es_serie(sn)]
    cambiados = {clave_sn(sn) for _, sn in (dip.get("sn_removidos") or [])
                 + (dip.get("sn_instalados") or []) if es_serie(sn)}
    cambiados.update(clave_sn(sn) for sn in extraer_sn(texto))
    en_descripcion = extraer_sn(dip["nombre"] + "\n" + dip["descripcion"])
    if (not es_squib(dip, entrada) and removidos and en_descripcion
            and not cambiados & {clave_sn(s) for s in en_descripcion}):
        r.agregar(ctx, "cierre_sn_distinto", "Incorrect S/N",
                  f"S/N removido {', '.join(sorted(set(removidos)))}; la descripción dice "
                  f"{', '.join(sorted(set(en_descripcion)))}.")

    if referencia_y_adjunto_exigibles(dip) and cantidad_adjuntos(dip) == 0:
        r.agregar(ctx, "cierre_sin_adjuntos", "Missing Attachment",
                  f"DIP cerrado sin attachments{_sin_adjuntos(dip)}.")


def _cierre_antes_de_ventana(dip: dict, entrada: EntradaCatalogo | None, ctx: Contexto,
                             r: ResultadoReglas) -> None:
    """Con ventana "AFTER A, BEFORE B" (desgaste de frenos, amortiguador) el trabajo se hace
    después de A: cerrado antes, no se cumplió el mínimo. En FH y FC se cuenta desde el uso al
    encontrar la falla hasta el uso al cerrar (History de ICAM); en días, por fecha."""
    ventana = _ventana(dip, entrada)
    if ventana is None or ventana[0].inicio_opcional:
        return
    unidad, minimo = dip["unidad"], ventana[0].inicio.valor
    if unidad == "DAY":
        found, completo = _como_fecha(dip["found_date"]), _como_fecha(dip.get("complete_date"))
        if found is None or completo is None:
            return
        corrido = (completo - found).days
    elif unidad in _PARAMETRO:
        encontrado = (dip.get("uso_encontrado") or {}).get(_PARAMETRO[unidad])
        cerrado = (dip.get("uso_completado") or {}).get(_PARAMETRO[unidad])
        if not encontrado or cerrado is None or cerrado < encontrado:
            return  # sin dato o de otro contador
        corrido = round(cerrado - encontrado, 2)
    else:
        return
    if corrido < minimo - _tolerancia(unidad, ctx):
        r.agregar(ctx, "cierre_antes_de_ventana", "Early Completion",
                  f"Cerrado a los {_fmt(corrido)} {unidad} de encontrar la falla, antes del mínimo "
                  f"de {_fmt(minimo)} {unidad} de la referencia ('{ventana[0].nombre}').")


def regla_inicio_ta(dip: dict, entrada: EntradaCatalogo | None, ctx: Contexto,
                    r: ResultadoReglas) -> None:
    """Start del T/A en ICAM: debe ser la apertura del DIP ("Incorrect DIP Start Values").

    En días, el Start debe caer entre la fecha en que se encontró la falla y el Defer
    Date (un T/A "within 4 months from the performance date" cuenta desde el
    trabajo). En FH y FC, debe ser el uso al encontrar la falla (History, "Usage When Found").
    Con ventana "AFTER A, BEFORE B" (amortiguador, desgaste de frenos) el T/A empieza
    A después de la apertura y dura B - A. Los auditores marcan el T/A que empieza en la
    apertura con B (vence igual, pero con otro Start) y el que empieza antes de la apertura.
    En un ítem sin ventana, un Start posterior con eso descontado del intervalo se acepta si
    vence dentro del TA, salvo con `start_en_apertura` en el catálogo (FDR). No aplica a los ítems con vencimiento (UNTIL DUE DATE): ahí manda
    la fecha del ítem."""
    if solo_rir(dip):
        return
    unidad, valor = dip["unidad"], dip["intervalo"]
    if unidad is None or (entrada is not None and entrada.hasta_vencimiento):
        return
    ventana = _ventana(dip, entrada)
    retraso = ventana[0].inicio.valor if ventana else 0
    limite = ventana[1].valor if ventana else 0
    esperado = (f"{_fmt(retraso)} {unidad} después de la apertura, con {_fmt(limite - retraso)} "
                f"{unidad} ('{ventana[0].nombre}')" if ventana else "en la apertura")
    if unidad == "DAY":
        inicio, found = _inicio_ta(dip), _como_fecha(dip["found_date"])
        if inicio is None or found is None:
            return
        diferido = max(found, _como_fecha(dip.get("defer_date")) or found)
        desde = found + timedelta(days=retraso - ctx.tol_dias)
        hasta = diferido + timedelta(days=retraso + ctx.tol_dias)
        corrido = (inicio - found).days
        tolerancia = ctx.tol_dias
        fuera = not desde <= inicio <= hasta
        detalle = (f"Start del T/A {_fecha(inicio)}: "
                   + (f"{abs(corrido)} días {'antes' if corrido < 0 else 'después'} de" if corrido
                      else "el día de") + f" la apertura ({_fecha(found)})")
    elif unidad in _PARAMETRO:
        uso = (dip.get("uso_encontrado") or {}).get(_PARAMETRO[unidad])
        corrido = _corrido_uso(dip, unidad, retraso)
        if uso is None or corrido is None:
            return  # sin dato, uso en 0 o de otro contador (motor contra avión)
        tolerancia = _tolerancia(unidad, ctx)
        fuera = abs(corrido - retraso) > tolerancia
        detalle = (f"Start del T/A {_fmt(round(uso + corrido, 2))} {unidad}: "
                   + (f"{_fmt(abs(round(corrido, 2)))} {unidad} "
                      f"{'antes' if corrido < 0 else 'después'} del" if corrido else "igual al")
                   + f" uso al encontrar la falla ({_fmt(uso)})")
    else:
        return
    if fuera and ventana is not None and ventana[0].inicio_opcional and valor == limite:
        # Ventana opcional: también vale empezar en la apertura con el intervalo completo.
        fuera = abs(corrido) > tolerancia
    if fuera and ventana is None and entrada is not None:
        # Empieza donde empieza la ventana del ítem, con otro intervalo (amortiguador MAX con
        # 5 FC + 15 FC): el Start es correcto y la regla del intervalo revisa el resto.
        fuera = not any(abs(corrido - v.inicio.valor) <= tolerancia
                        for v in _variantes_aplicables(dip, entrada)
                        if v.inicio is not None and v.inicio.unidad == unidad)
    if fuera and entrada is not None and corrido > 0 and valor and not entrada.start_en_apertura \
            and not any(v.inicio for v in _variantes_aplicables(dip, entrada)):
        # Ítem sin ventana, con Start después de la apertura y eso descontado del intervalo
        # (más ciclos en el Start, menos en el T/A): si vence dentro del TA, se acepta.
        tope = _plazo_maximo(dip, entrada, ctx)
        fuera = tope is None or corrido + valor > tope + tolerancia
    if fuera:
        # Sin fuente no se sabe si el ítem tiene una ventana: un Start posterior a la
        # apertura queda para verificar. Uno anterior nunca es correcto.
        verificar = entrada is None and corrido > 0
        r.agregar(ctx, "inicio_ta_incorrecto", "Incorrect DIP Start Values",
                  f"{detalle}; debe empezar {esperado}"
                  + (" (salvo que la fuente que cita diga otra cosa: verificar)." if verificar else "."),
                  "OK" if verificar else None)
        return
    # Empieza bien, pero con el intervalo B: vence después de la ventana.
    if ventana and valor is not None and corrido + valor > limite + tolerancia:
        r.agregar(ctx, "intervalo_excedido", "Incorrect DIP Interval",
                  f"T/A empieza {_fmt(corrido)} {unidad} después de la apertura con "
                  f"{_fmt(valor)} {unidad}: vence a los {_fmt(corrido + valor)} {unidad}, "
                  f"después de los {_fmt(limite)} de la referencia ('{ventana[0].nombre}').")


def cantidad_adjuntos(dip: dict) -> int | None:
    """Attachments del DIP: los de ICAM y, sin ICAM, los del Excel (Attach Docs). None = sin dato."""
    if dip.get("adjuntos") is not None:
        return len(dip["adjuntos"])
    return dip.get("adjuntos_excel")


def _sin_adjuntos(dip: dict) -> str:
    return "" if dip.get("adjuntos") is not None else " (Attachment Status PENDING)"


def regla_adjuntos(dip: dict, ctx: Contexto, r: ResultadoReglas) -> None:
    """En DIPs diferidos desde el corte, sin attachments es posible discrepancia,
    aunque la descripción cite el manual. Un attachment
    con la matrícula de otro avión en el nombre puede ser de otro DIP."""
    if referencia_y_adjunto_exigibles(dip) and cantidad_adjuntos(dip) == 0:
        r.agregar(ctx, "sin_adjuntos", "Missing Attachment", f"DIP sin attachments{_sin_adjuntos(dip)}.")
    avion = re.sub(r"\D", "", dip.get("avion") or "")
    for adjunto in dip.get("adjuntos") or []:
        otras = {m for m in re.findall(r"HP\s*-?\s*(\d{4})", adjunto.upper()) if m != avion}
        if avion and otras:
            r.agregar(ctx, "adjunto_otro_avion", "Missing Attachment",
                      f"Attachment '{adjunto}' de otro avión "
                      f"(HP-{', HP-'.join(sorted(otras))}).")


def regla_programado_despues_del_due(dip: dict, ctx: Contexto, r: ResultadoReglas) -> None:
    """Un DIP activo en un paquete de trabajo programado después de su due date va a vencer."""
    if solo_rir(dip):
        return
    programado, due = dip.get("scheduled_date"), dip.get("due_date")
    if dip.get("estado") not in ACTIVOS or not programado or not due:
        return
    if como_fecha_hora(programado) > _fin_del_plazo(due) + timedelta(hours=ctx.horas_cierre):
        paquete = dip.get("work_package") or "El paquete de trabajo"
        r.agregar(ctx, "programado_despues_del_due", "Overdue DIP",
                  f"{paquete} programado el {_fecha_hora(programado)}, después del due date "
                  f"({_fecha_hora(due)}).")


def _sn_parecidos(a: str, b: str) -> bool:
    """El mismo S/N con un error en el número: 1110198 / 11101989, 187 / 178."""
    return a in b or b in a or Levenshtein.distance(a, b) <= 1


def regla_sn_consistente(dip: dict, ctx: Contexto, r: ResultadoReglas,
                         entrada: EntradaCatalogo | None = None) -> None:
    """El S/N del Fault Name y la descripción debe ser el de las notas de la descripción
    (ICAM). Si no coinciden, los auditores marcan "Incorrect Serial Number Referenced".
    Cuenta el número: P11101989 y 11101989 son el mismo S/N. Un S/N de más en uno de los
    textos (otro componente del mismo DIP) no cuenta."""
    if es_squib(dip, entrada):
        return

    def por_clave(texto: str) -> dict[str, str]:
        return {clave_sn(s): s for s in extraer_sn(texto) if clave_sn(s)}

    en_dip = por_clave(dip["nombre"] + "\n" + dip["descripcion"])
    en_notas = por_clave(dip.get("notas_descripcion") or "")
    if not en_dip or not en_notas or en_dip.keys() == en_notas.keys():
        return
    parecidos = [(en_dip[a], en_notas[b]) for a in sorted(en_dip.keys() - en_notas.keys())
                 for b in sorted(en_notas.keys() - en_dip.keys()) if _sn_parecidos(a, b)]
    if not parecidos and en_dip.keys() & en_notas.keys():
        return
    pares = parecidos or [(", ".join(sorted(en_dip.values())), ", ".join(sorted(en_notas.values())))]
    r.agregar(ctx, "sn_inconsistente", "Incorrect S/N",
              "S/N distinto entre el DIP y las notas de la descripción: "
              + "; ".join(f"'{a}' / '{b}'" for a, b in pares) + ".")


def regla_parent_assy(dip: dict, entrada: EntradaCatalogo, ctx: Contexto,
                      r: ResultadoReglas) -> None:
    esperado = entrada.parent_assy
    actual = dip["parent_tipo"]
    # El texto del DIP puede cambiar el Parent Assembly de la tabla: un mensaje LONG TIME
    # va en el motor, salvo el del reversor (REVERSER), que va en el avión.
    por_texto = entrada.parent_por_texto(normalizar(" ".join(
        str(dip.get(c) or "") for c in ("nombre", "descripcion", "notas_descripcion"))))
    if por_texto:
        esperado = {por_texto[0]}
    if not esperado:
        return
    if not actual:
        r.manuales.append("Parent assy vacío en el Excel de entrada: verificar asignación.")
        return
    if por_texto and actual not in esperado:
        asignado = actual if actual == "AIRCRAFT" else f"{actual} ({dip['parent_assy']})"
        r.agregar(ctx, "parent_assy_incorrecto", "Incorrect Parent Assembly",
                  f"Asignado a {asignado}; el DIP dice '{por_texto[1]}' y ese ítem va en "
                  f"{por_texto[0]}.")
    elif actual not in esperado:
        texto_esp = "/".join(sorted(esperado))
        if entrada.parent_assy_flexible:
            r.agregar(ctx, "parent_assy_incorrecto", "Incorrect Parent Assembly",
                      f"Asignado a {actual}; la referencia indica {texto_esp} (a ENGINE si "
                      f"se roba el motor). Verificar.",
                      "OK")
        else:
            # Si es el avión basta con AIRCRAFT; el modelo (737-800...) no aporta.
            asignado = actual if actual == "AIRCRAFT" else f"{actual} ({dip['parent_assy']})"
            r.agregar(ctx, "parent_assy_incorrecto", "Incorrect Parent Assembly",
                      f"Asignado a {asignado}; la referencia indica {texto_esp}.")


def regla_ata(dip: dict, entrada: EntradaCatalogo | None, ctx: Contexto,
              r: ResultadoReglas) -> None:
    m = re.match(r"\s*(\d{1,2})\s*-", dip["deferral_ref"] or "")
    if m and dip["ata"] is not None and int(m.group(1)) != dip["ata"]:
        r.agregar(ctx, "deferral_reference_ata", "Incorrect ATA",
                  f"Deferral Reference '{dip['deferral_ref']}' no coincide con ATA {dip['ata']}.")
    if entrada is not None and dip["ata"] is not None:
        atas = {x.ata for x in entrada.referencias if x.ata is not None}
        if atas and dip["ata"] not in atas:
            r.agregar(ctx, "ata_distinto_a_referencia", "Incorrect ATA",
                      f"ATA {dip['ata']} distinto al de la referencia "
                      f"({', '.join(map(str, sorted(atas)))}).")


def regla_sn(dip: dict, entrada: EntradaCatalogo, ctx: Contexto, r: ResultadoReglas) -> None:
    if not entrada.requiere_sn:
        return
    sns = extraer_sn(dip["nombre"] + "\n" + dip["descripcion"])
    if not sns:
        r.agregar(ctx, "sin_sn_en_descripcion", "Missing S/N",
                  "Sin S/N del componente en la descripción.")
    r.manuales.append("Verificar que el S/N del attachment coincida con el componente "
                      "instalado" + (f" (S/N en descripción: {', '.join(sns)})." if sns else "."))


_POSICION_MOTOR = re.compile(
    r"\b(?:ENGINE|ENG)\s*(?:(?:NO\.?|NUMBER|NBR)\s*)?#?\s*"
    r"(1|2|LH|RH|LEFT|RIGHT)\b", re.I)


def _numero_motor(posicion: str) -> str:
    return {"LH": "1", "LEFT": "1", "RH": "2", "RIGHT": "2"}.get(
        posicion.upper(), posicion)


def regla_sn_motor(dip: dict, ctx: Contexto, r: ResultadoReglas) -> None:
    """ENGINE en el título exige el serial completo del motor en la descripción.

    El Parent Assembly identifica el motor de ese DIP. Nunca se reutiliza el serial
    de otro DIP o de otro motor del avión, que puede haber cambiado con el tiempo.
    """
    if not re.search(r"\bENGINE\b", dip.get("nombre") or "", re.I):
        return
    descripcion = dip.get("descripcion") or ""
    if dip.get("descripcion_disponible") is False and not descripcion:
        r.manuales.append("Verificar el S/N del motor en la descripción: el Excel no trae "
                          "esa columna y no se ha leído la descripción en ICAM.")
        return
    sns = extraer_sn(descripcion)
    if not sns:
        r.agregar(ctx, "sin_sn_motor_en_descripcion", "Missing S/N",
                  "El título del DIP dice ENGINE y la descripción no incluye el S/N del motor.")
        return

    # El Excel sigue siendo la fuente principal; ICAM completa el dato cuando el
    # DIP está asignado al avión en el Excel o no trae un serial de motor.
    parent = next((p for p in (dip.get("parent_assy"), dip.get("parent_icam"))
                   if p and re.search(r"\bENGINE\b", p, re.I) and extraer_sn(p)), "")
    if not parent:
        r.manuales.append("Verificar que el S/N de la descripción corresponda al motor "
                          "indicado en el título: sin S/N de motor en Parent Assembly.")
        return
    esperados = extraer_sn(parent)
    titulo = {_numero_motor(m.group(1)) for m in _POSICION_MOTOR.finditer(dip["nombre"])}
    lado = re.search(r"\((LH|RH)\)", parent, re.I)
    if lado and titulo and _numero_motor(lado.group(1)) not in titulo:
        r.agregar(ctx, "sn_motor_incorrecto", "Incorrect S/N",
                  f"El título indica ENGINE {'/'.join(sorted(titulo))}, pero el Parent Assembly "
                  f"corresponde al motor {_numero_motor(lado.group(1))}: {parent}.")
        return

    # Si la descripción enumera ambos motores, el serial debe estar en el apartado
    # del motor del título; encontrarlo en el del otro motor no lo valida.
    marcas = list(_POSICION_MOTOR.finditer(descripcion))
    if len(titulo) == 1 and marcas:
        segmentos = [descripcion[m.end():marcas[i + 1].start() if i + 1 < len(marcas) else None]
                     for i, m in enumerate(marcas) if _numero_motor(m.group(1)) in titulo]
        sns = [s for segmento in segmentos for s in extraer_sn(segmento)]
    if not {clave_sn_completa(s) for s in esperados} & {clave_sn_completa(s) for s in sns}:
        r.agregar(ctx, "sn_motor_incorrecto", "Incorrect S/N",
                  f"La descripción no cita el S/N del motor correspondiente "
                  f"({', '.join(esperados)} según Parent Assembly). "
                  f"S/N citados para ese motor: {', '.join(sns) or 'ninguno'}.")


def regla_severidad(dip: dict, ctx: Contexto, r: ResultadoReglas) -> None:
    if dip["severidad"] and dip["severidad"] != "DIP":
        r.agregar(ctx, "fault_severity", "Incorrect Fault Severity",
                  f"Fault Severity es '{dip['severidad']}' (se esperaba DIP).")


# Recordatorio que llevan todos los DIPs: no cuenta como verificación pendiente en el resumen.
VERIFICACION_GENERAL = "Verificar attachments: captura de referencia técnica y EC/RA adjunta."


def auditar_dip(dip: dict, entrada: EntradaCatalogo | None, ctx: Contexto) -> ResultadoReglas:
    r = ResultadoReglas()
    regla_extension(dip, ctx, r)
    if entrada is not None:
        regla_intervalo(dip, entrada, ctx, r)
        regla_parent_assy(dip, entrada, ctx, r)
        regla_sn(dip, entrada, ctx, r)
    regla_fechas(dip, entrada, ctx, r)
    regla_inicio_ta(dip, entrada, ctx, r)
    regla_adjuntos(dip, ctx, r)
    regla_programado_despues_del_due(dip, ctx, r)
    regla_sn_motor(dip, ctx, r)
    regla_sn_consistente(dip, ctx, r, entrada)
    regla_ata(dip, entrada, ctx, r)
    regla_severidad(dip, ctx, r)
    if referencia_y_adjunto_exigibles(dip):
        r.manuales.append(VERIFICACION_GENERAL)
    if es_squib(dip, entrada):
        r.manuales.append(verificar_squib(dip))
    return r


# --------------------------------------------------------------------------
# Duplicados (se evalúan sobre el lote completo)
# --------------------------------------------------------------------------

def _coexisten(da: dict, db: dict) -> bool:
    """True si los dos DIPs estuvieron abiertos al mismo tiempo.

    Con la fecha de cierre de los cerrados, se solapan si cada uno se abrió antes de que el
    otro se cerrara (un DIP cerrado "OPEN BY MISTAKE" a las 05:29 y abierto de nuevo a las
    05:32 no es un duplicado). Sin ella solo se puede afirmar si ambos siguen activos o si se
    abrieron el mismo día (DIP creado dos veces).
    """
    if da["estado"] in ACTIVOS and db["estado"] in ACTIVOS:
        return True
    fin = {id(d): d.get("complete_date") if d["estado"] not in ACTIVOS else datetime.max
           for d in (da, db)}
    if da["found_date"] and db["found_date"] and all(fin.values()):
        return (como_fecha_hora(db["found_date"]) < como_fecha_hora(fin[id(da)])
                and como_fecha_hora(da["found_date"]) < como_fecha_hora(fin[id(db)]))
    fa, fb = _como_fecha(da["found_date"]), _como_fecha(db["found_date"])
    return fa is not None and fa == fb


def _lado(texto: str) -> frozenset[str]:
    """Posiciones escritas con palabras (FWD/AFT, LH/RH...) en la descripción. Los números
    sueltos no cuentan: ahí son pasos, días o task cards."""
    return frozenset(p for p in posiciones(normalizar(texto)) if not p.isdigit())


# Número de mensaje de mantenimiento del motor o del AHM: 75-10452, 73-30311, 79-21101.
_MENSAJE = re.compile(r"(?<![\d-])\d{2}-\d{5}(?![\d-])")


def buscar_duplicados(dips: list[dict], entradas: list[EntradaCatalogo | None],
                      tol_dias: int = 1) -> dict[int, tuple[str, str]]:
    """Índice del DIP -> (barcode, nombre) del DIP que parece duplicar.

    Dos DIPs son posibles duplicados si son del mismo avión, misma entrada del
    catálogo, mismas posiciones (FWD/AFT, LH/RH, #n), S/N compatibles, abiertos
    al mismo tiempo y, en ítems con vencimiento, con el mismo due date. Se marca
    el que se abrió después.
    """
    grupos: dict[tuple[str, str], list[int]] = {}
    for i, (dip, e) in enumerate(zip(dips, entradas)):
        if e is not None and dip["avion"]:
            grupos.setdefault((dip["avion"], e.id), []).append(i)

    duplicados: dict[int, tuple[str, str]] = {}
    for indices in grupos.values():
        if len(indices) < 2:
            continue
        indices.sort(key=lambda i: (_como_fecha(dips[i]["found_date"]) or date.max,
                                    dips[i]["barcode"]))
        for a_pos, a in enumerate(indices):
            for b in indices[a_pos + 1:]:
                if b in duplicados:
                    continue
                da, db = dips[a], dips[b]
                if da["barcode"] == db["barcode"]:
                    continue
                na, nb = normalizar(da["nombre"]), normalizar(db["nombre"])
                if posiciones(na) != posiciones(nb):
                    continue
                # Mismo nombre, otro componente según la descripción: "(LEFT SQUIB) OF LEFT
                # Engine Fire Extinguisher Bottle" y "(RIGHT SQUIB) OF LEFT ...".
                if da["descripcion"] and db["descripcion"] and \
                        _lado(da["descripcion"]) != _lado(db["descripcion"]):
                    continue
                sa = {clave_sn_completa(s) for s in extraer_sn(da["nombre"] + "\n" + da["descripcion"])}
                sb = {clave_sn_completa(s) for s in extraer_sn(db["nombre"] + "\n" + db["descripcion"])}
                if sa and sb and not (sa & sb):
                    continue
                # Mensajes de mantenimiento distintos del mismo motor: SHORT TIME 75-20451 y
                # 75-10451 son dos fallas.
                ma = set(_MENSAJE.findall(da["nombre"] + " " + da["descripcion"]))
                mb = set(_MENSAJE.findall(db["nombre"] + " " + db["descripcion"]))
                if ma and mb and not (ma & mb):
                    continue
                if not _coexisten(da, db):
                    continue
                entrada = entradas[a]
                # Referencia con varias etapas (1er re-torque a los 60 días, 2do a los 12
                # meses): con otro intervalo es la otra etapa, no un duplicado.
                if entrada is not None and len(entrada.variantes) > 1 and \
                        None not in (da["intervalo"], db["intervalo"]) and \
                        (da["intervalo"], da["unidad"]) != (db["intervalo"], db["unidad"]):
                    continue
                ua, ub = _como_fecha(da["due_date"]), _como_fecha(db["due_date"])
                if entrada is not None and entrada.hasta_vencimiento and ua and ub and abs((ua - ub).days) > tol_dias:
                    continue  # distinto vencimiento = distinto componente
                duplicados[b] = (da["barcode"], da["nombre"])
    return duplicados


def buscar_sn_repetidos(dips: list[dict]) -> dict[int, list[str]]:
    """Índice del DIP -> otros DIPs del avión con el mismo S/N que coexistieron.

    Detecta el caso de dos tarjetas (p. ej. FAK 1 y FAK 2) con el mismo S/N.
    """
    por_sn: dict[tuple[str, str], list[int]] = {}
    for i, d in enumerate(dips):
        if not d["avion"] or es_squib(d):
            continue
        for sn in {clave_sn_completa(s) for s in extraer_sn(d["nombre"] + "\n" + d["descripcion"])}:
            por_sn.setdefault((d["avion"], sn), []).append(i)
    repetidos: dict[int, list[str]] = {}
    for indices in por_sn.values():
        for pos, i in enumerate(indices):
            for j in indices[pos + 1:]:
                if dips[i]["barcode"] == dips[j]["barcode"] or not _coexisten(dips[i], dips[j]):
                    continue
                for a, b in ((i, j), (j, i)):
                    otros = repetidos.setdefault(a, [])
                    if dips[b]["barcode"] not in otros:
                        otros.append(dips[b]["barcode"])
    return repetidos


def estado_final(hallazgos: list[Hallazgo]) -> str:
    peor = max((ORDEN_SEVERIDAD[h.severidad] for h in hallazgos), default=0)
    for sev, orden in ORDEN_SEVERIDAD.items():
        if orden == peor and sev in ESTADOS:
            return ESTADOS[sev]
    return "OK"
