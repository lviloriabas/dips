"""Reglas de auditoría. Cada regla devuelve hallazgos con evidencia verificable."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .referencias import EntradaCatalogo, Limite, Variante
from .texto import extraer_fechas, extraer_psi, extraer_sn, normalizar, posiciones

ORDEN_SEVERIDAD = {"CRITICA": 4, "NO CRITICA": 3, "REVISAR": 2, "OBSERVACION": 1}
ESTADOS = {
    "CRITICA": "DISCREPANCIA CRÍTICA",
    "NO CRITICA": "DISCREPANCIA NO CRÍTICA",
    "REVISAR": "REVISAR",
}


@dataclass
class Hallazgo:
    codigo: str       # clave de configuración (p. ej. intervalo_excedido)
    categoria: str    # tipo de discrepancia (nomenclatura del departamento)
    severidad: str    # CRITICA, NO CRITICA, REVISAR, OBSERVACION
    mensaje: str


@dataclass
class Contexto:
    severidades: dict[str, str]
    fecha_referencia: date
    tol_dias: int = 1
    meses_min: int = 30
    meses_max: int = 31


@dataclass
class ResultadoReglas:
    hallazgos: list[Hallazgo] = field(default_factory=list)
    manuales: list[str] = field(default_factory=list)
    intervalo_ok: bool | None = None
    variante: str = ""

    def agregar(self, ctx: Contexto, codigo: str, categoria: str, mensaje: str,
                severidad: str | None = None) -> None:
        sev = severidad or ctx.severidades.get(codigo, "NO CRITICA")
        self.hallazgos.append(Hallazgo(codigo, categoria, sev, mensaje))


def _fmt(valor: float | None) -> str:
    if valor is None:
        return "?"
    return str(int(valor)) if float(valor).is_integer() else f"{valor:g}"


def _fecha(d: datetime | date | None) -> str:
    return d.strftime("%d-%b-%Y").upper() if d else "?"


def _como_fecha(d: datetime | date | None) -> date | None:
    if d is None:
        return None
    return d.date() if isinstance(d, datetime) else d


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

def regla_intervalo(dip: dict, entrada: EntradaCatalogo, ctx: Contexto, r: ResultadoReglas) -> None:
    valor, unidad = dip["intervalo"], dip["unidad"]
    if valor is None or unidad is None:
        r.agregar(ctx, "datos_incompletos", "Deferral Interval Not Documented",
                  f"Sin intervalo o tipo de intervalo válido en el Excel de entrada "
                  f"('{_fmt(valor)}' '{dip['tipo_intervalo_original']}').", "REVISAR")
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
                      f"T/A aperturado en {_fmt(valor)} {unidad}; la referencia es UNTIL DUE "
                      f"DATE (días calendario).")
            r.intervalo_ok = False
        else:
            r.intervalo_ok = True
        return

    if entrada.no_verificable or not entrada.variantes:
        r.manuales.append(f"Intervalo: verificar manualmente contra la referencia "
                          f"('{'; '.join(x.ta for x in entrada.referencias)}').")
        return

    variantes = entrada.variantes
    flota = dip.get("flota")
    if any(v.flotas for v in variantes):
        if flota:
            aplicables = [v for v in variantes if not v.flotas or flota in v.flotas]
        else:
            aplicables = variantes
            r.manuales.append("No se pudo determinar la flota del avión; se aceptó el "
                              "intervalo de cualquier flota.")
    else:
        aplicables = variantes
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
            if rango[0] <= valor <= rango[1]:
                coincidentes.append((v, lim))
            if maximo is None or rango[1] > maximo[0]:
                maximo = (rango[1], lim)

    texto_ref = "; ".join(
        " o ".join(str(l) for l in v.limites) + (f" [{', '.join(v.flotas)}]" if v.flotas else "")
        for v in aplicables)

    if maximo is None:
        r.agregar(ctx, "tipo_intervalo_incorrecto", "Incorrect DIP Interval",
                  f"T/A aperturado en {unidad} ({_fmt(valor)} {dip['tipo_intervalo_original']}); "
                  f"la referencia indica {texto_ref}.")
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
                      f"'{variante.nombre}'. Verificar que aplique.{extra}", "OBSERVACION")
        if len(variante.limites) > 1:
            r.manuales.append("Verificar límite dual en ICAM: " +
                              " o ".join(str(l) for l in variante.limites) +
                              " (lo que ocurra primero).")
        if variante.rir:
            r.manuales.append(f"Verificar RIR cada {variante.rir}.")
        return

    r.intervalo_ok = False
    if valor > maximo[0]:
        r.agregar(ctx, "intervalo_excedido", "Incorrect DIP Interval",
                  f"T/A aperturado con {_fmt(valor)} {unidad}, mayor que la referencia "
                  f"({texto_ref}).")
    else:
        r.agregar(ctx, "intervalo_menor", "Incorrect DIP Interval",
                  f"T/A aperturado con {_fmt(valor)} {unidad}, distinto de la referencia "
                  f"({texto_ref}).")


def regla_fechas(dip: dict, entrada: EntradaCatalogo | None, ctx: Contexto,
                 r: ResultadoReglas) -> None:
    due, found = _como_fecha(dip["due_date"]), _como_fecha(dip["found_date"])
    valor, unidad, estado = dip["intervalo"], dip["unidad"], dip["estado"]

    if dip.get("correccion_fecha"):
        r.manuales.append(dip["correccion_fecha"] + ".")

    # Due date coherente con fecha de apertura + intervalo (solo días).
    if due and found and valor is not None and unidad == "DAY":
        esperado = found + timedelta(days=valor)
        diferencia = (due - esperado).days
        if diferencia > ctx.tol_dias:
            r.agregar(ctx, "due_date_posterior_a_intervalo", "Incorrect Due Date",
                      f"Due date {_fecha(due)} es {diferencia} días posterior a apertura "
                      f"({_fecha(found)}) + {_fmt(valor)} DAY = {_fecha(esperado)}. "
                      f"Verificar el Start Date del T/A en ICAM.")
        elif diferencia < -ctx.tol_dias:
            r.agregar(ctx, "due_date_anterior_a_intervalo", "Incorrect Due Date",
                      f"Due date {_fecha(due)} es {-diferencia} días anterior a apertura "
                      f"({_fecha(found)}) + {_fmt(valor)} DAY = {_fecha(esperado)}.")

    # Ítems con vencimiento: el due date no puede superar la fecha del ítem.
    if entrada is not None and entrada.hasta_vencimiento and due:
        texto = dip["nombre"] + " " + dip["descripcion"]
        fechas = sorted(f for f in extraer_fechas(texto) if not found or f >= found)
        if fechas:
            vence = fechas[0]
            if due > vence:
                r.agregar(ctx, "due_date_posterior_a_vencimiento_item", "Incorrect Due Date",
                          f"Due date del DIP ({_fecha(due)}) es posterior al vencimiento "
                          f"indicado en la descripción ({_fecha(vence)}).")
            elif (vence - due).days > ctx.tol_dias:
                r.agregar(ctx, "due_date_anterior_a_vencimiento_item", "Incorrect Due Date",
                          f"Due date del DIP ({_fecha(due)}) es anterior al vencimiento "
                          f"indicado en la descripción ({_fecha(vence)}).")
        else:
            r.manuales.append("Verificar en el attachment la fecha de vencimiento del ítem "
                              "y que coincida con el due date del DIP.")

    # Vencido / completado fuera de plazo.
    activo = estado in {"ACTV", "IN WORK", "OPEN"}
    if activo and due and due < ctx.fecha_referencia:
        r.agregar(ctx, "dip_vencido", "Overdue DIP",
                  f"DIP {estado} con due date {_fecha(due)} vencido a la fecha de auditoría "
                  f"({_fecha(ctx.fecha_referencia)}).")
    elif activo and dip["usage_remaining"] is not None and dip["usage_remaining"] < 0:
        r.agregar(ctx, "dip_vencido", "Overdue DIP",
                  f"DIP {estado} con Usage Remaining negativo ({_fmt(dip['usage_remaining'])}).")

    completo = _como_fecha(dip.get("complete_date"))
    if estado == "COMPLETE":
        if completo and due and completo > due:
            r.agregar(ctx, "completado_fuera_de_plazo", "Late Completion",
                      f"Completado el {_fecha(completo)}, después del due date {_fecha(due)}.")
        elif not completo:
            r.manuales.append("DIP COMPLETE: verificar en ICAM que se cerró dentro del plazo.")

    # Usage Remaining mayor que el intervalo: el T/A de scheduling no coincide.
    rem = dip["usage_remaining"]
    if activo and rem is not None and valor is not None:
        tol = ctx.tol_dias if unidad == "DAY" else 0
        if rem > valor + tol:
            r.agregar(ctx, "usage_remaining_mayor_a_intervalo", "Incorrect DIP Interval",
                      f"Usage Remaining ({_fmt(rem)}) es mayor que el intervalo del DIP "
                      f"({_fmt(valor)} {unidad}); revisar el T/A configurado en scheduling.")


def regla_parent_assy(dip: dict, entrada: EntradaCatalogo, ctx: Contexto,
                      r: ResultadoReglas) -> None:
    esperado = entrada.parent_assy
    actual = dip["parent_tipo"]
    if not esperado:
        return
    if not actual:
        r.manuales.append("Parent assy vacío en el Excel de entrada: verificar asignación.")
        return
    if actual not in esperado:
        texto_esp = "/".join(sorted(esperado))
        if entrada.parent_assy_flexible:
            r.agregar(ctx, "parent_assy_incorrecto", "Incorrect Parent Assembly",
                      f"Asignado a {actual}; la referencia indica {texto_esp}* (se abre a "
                      f"AIRCRAFT y se transfiere a ENGINE si se roba el motor). Verificar.",
                      "OBSERVACION")
        else:
            r.agregar(ctx, "parent_assy_incorrecto", "Incorrect Parent Assembly",
                      f"Asignado a {actual} ({dip['parent_assy']}); la referencia indica "
                      f"{texto_esp}.")


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
    sns = extraer_sn(dip["nombre"] + " " + dip["descripcion"])
    if not sns:
        r.agregar(ctx, "sin_sn_en_descripcion", "Missing S/N",
                  "Sin S/N del componente en la descripción.")
    r.manuales.append("Verificar que el S/N del attachment coincida con el componente "
                      "instalado" + (f" (S/N en descripción: {', '.join(sns)})." if sns else "."))


def regla_severidad(dip: dict, ctx: Contexto, r: ResultadoReglas) -> None:
    if dip["severidad"] and dip["severidad"] != "DIP":
        r.agregar(ctx, "fault_severity", "Incorrect Fault Severity",
                  f"Fault Severity es '{dip['severidad']}' (se esperaba DIP).")


def auditar_dip(dip: dict, entrada: EntradaCatalogo | None, ctx: Contexto) -> ResultadoReglas:
    r = ResultadoReglas()
    if entrada is not None:
        regla_intervalo(dip, entrada, ctx, r)
        regla_parent_assy(dip, entrada, ctx, r)
        regla_sn(dip, entrada, ctx, r)
    regla_fechas(dip, entrada, ctx, r)
    regla_ata(dip, entrada, ctx, r)
    regla_severidad(dip, ctx, r)
    r.manuales.append("Verificar attachments: captura de referencia técnica y EC/RA adjunta.")
    return r


# --------------------------------------------------------------------------
# Duplicados (se evalúan sobre el lote completo)
# --------------------------------------------------------------------------

_ACTIVOS = {"ACTV", "IN WORK", "OPEN"}


def _coexisten(da: dict, db: dict) -> bool:
    """True si los dos DIPs estuvieron abiertos al mismo tiempo.

    Sin fecha de cierre en el Excel de entrada solo se puede afirmar si ambos siguen
    activos o si se abrieron el mismo día (DIP creado dos veces).
    """
    if da["estado"] in _ACTIVOS and db["estado"] in _ACTIVOS:
        return True
    fa, fb = _como_fecha(da["found_date"]), _como_fecha(db["found_date"])
    return fa is not None and fa == fb


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
                sa, sb = set(extraer_sn(da["nombre"])), set(extraer_sn(db["nombre"]))
                if sa and sb and not (sa & sb):
                    continue
                if not _coexisten(da, db):
                    continue
                entrada = entradas[a]
                ua, ub = _como_fecha(da["due_date"]), _como_fecha(db["due_date"])
                if entrada is not None and entrada.hasta_vencimiento and ua and ub and abs((ua - ub).days) > tol_dias:
                    continue  # distinto vencimiento = distinto componente
                duplicados[b] = (da["barcode"], da["nombre"])
    return duplicados


def buscar_sn_repetidos(dips: list[dict]) -> dict[int, list[str]]:
    """Índice del DIP -> barcodes de otros DIPs activos del mismo avión con el mismo S/N.

    Detecta el caso de dos tarjetas (p. ej. FAK 1 y FAK 2) con el mismo S/N.
    """
    por_sn: dict[tuple[str, str], list[int]] = {}
    for i, d in enumerate(dips):
        if d["estado"] not in _ACTIVOS or not d["avion"]:
            continue
        for sn in set(extraer_sn(d["nombre"] + " " + d["descripcion"])):
            por_sn.setdefault((d["avion"], sn), []).append(i)
    repetidos: dict[int, list[str]] = {}
    for indices in por_sn.values():
        if len(indices) > 1:
            for i in indices:
                repetidos.setdefault(i, []).extend(
                    dips[j]["barcode"] for j in indices if j != i)
    return repetidos


def estado_final(hallazgos: list[Hallazgo]) -> str:
    peor = max((ORDEN_SEVERIDAD[h.severidad] for h in hallazgos), default=0)
    for sev, orden in ORDEN_SEVERIDAD.items():
        if orden == peor and sev in ESTADOS:
            return ESTADOS[sev]
    return "OK"
