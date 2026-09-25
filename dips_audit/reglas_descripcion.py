"""Reglas contra la fuente que cita el propio DIP, para los DIPs que la tabla no tiene.

Un DIP SIN FUENTE no se puede comparar con la tabla de referencias, pero su descripción
suele decir el plazo ("open DIP for 45 days or 225 FC", "within 60 days"), las inspecciones
repetitivas ("every 30 days") y el vencimiento del ítem ("DUE DATE NOVEMBER/2027"). Estas
reglas revisan el T/A, el RIR y el due date contra ese texto, como hace el auditor con
"verificar contra la fuente que cita". En los DIPs de la tabla manda la tabla.
"""

from __future__ import annotations

from collections import Counter
from datetime import timedelta

from .cargador import tipo_parent
from .limites_declarados import LimiteDeclarado, extraer_limites, fechas_de_vencimiento
from .referencia_tecnica import extraer_codigos, sin_task_cards
from .referencias import EntradaCatalogo
from .reglas import ACTIVOS, Contexto, ResultadoReglas, _como_fecha, _fecha, _fmt
from .rir import Limite as LimiteRIR
from .rir import _mismo

# Parámetro del T/A en ICAM -> unidad.
_UNIDAD_TA = {"CDY": "DAY", "DAY": "DAY", "HOURS": "FH", "HOUR": "FH", "CYCLES": "FC", "CYCLE": "FC"}


def _texto(dip: dict) -> str:
    return " ".join(str(x) for x in (dip.get("nombre"), dip.get("descripcion"),
                                     dip.get("notas_diferimiento")) if x)


def _limites_ta(dip: dict) -> tuple[dict[str, float], bool]:
    """Límites del T/A {unidad: valor} y si vienen de ICAM (todos) o del Excel (solo el
    que vence primero)."""
    ta = {_UNIDAD_TA.get((i.get("parameter") or "").upper()): i.get("value")
          for i in dip.get("icam_intervalos") or []}
    ta = {u: v for u, v in ta.items() if u and v is not None}
    if ta:
        return ta, True
    if dip.get("intervalo") is not None and dip.get("unidad") in ("DAY", "FH", "FC"):
        return {dip["unidad"]: dip["intervalo"]}, False
    return {}, False


def _en_dias(lim: LimiteDeclarado) -> tuple[str, float]:
    """Meses a días (n meses = hasta 31 n días), para comparar con un T/A en días."""
    return ("DAY", lim.valor * 31) if lim.unidad == "MONTH" else (lim.unidad, lim.valor)


def _texto_limites(lims: list[LimiteDeclarado]) -> str:
    return " o ".join(map(str, lims))


def regla_plazo_declarado(dip: dict, ctx: Contexto, r: ResultadoReglas) -> None:
    """T/A contra el plazo que declara la descripción: mayor, en otra unidad o sin alguno
    de los límites ("45 days or 225 FC": el T/A debe tener los dos)."""
    declarado = extraer_limites(_texto(dip))
    ta, de_icam = _limites_ta(dip)
    if not declarado.plazos or not ta:
        return
    # Por unidad, el límite declarado más amplio (una misma descripción puede dar varios).
    maximo: dict[str, float] = {}
    for _, lims in declarado.plazos:
        for lim in lims:
            u, v = _en_dias(lim)
            maximo[u] = max(maximo.get(u, 0), v)
    frase, grupo = declarado.plazo
    comunes = set(ta) & set(maximo)
    if not comunes:
        r.agregar(ctx, "tipo_intervalo_distinto_a_descripcion", "Incorrect DIP Interval",
                  f"T/A en {', '.join(f'{_fmt(v)} {u}' for u, v in ta.items())}; la descripción "
                  f"dice '{frase.strip()}'.")
        return
    excedidos = [u for u in comunes if ta[u] > maximo[u] + (ctx.tol_dias if u == "DAY" else 0)]
    for u in excedidos:
        r.agregar(ctx, "intervalo_mayor_a_descripcion", "Incorrect DIP Interval",
                  f"T/A con {_fmt(ta[u])} {u}, mayor que lo que dice la descripción "
                  f"('{frase.strip()}').")
    faltan = [lim for lim in grupo if _en_dias(lim)[0] not in ta]
    if len(grupo) > 1 and faltan:
        texto = (f"La descripción pide {_texto_limites(grupo)} (lo que ocurra primero) "
                 f"('{frase.strip()}')")
        if de_icam:
            r.agregar(ctx, "limite_declarado_faltante", "Incorrect DIP Interval",
                      f"{texto}; el T/A no tiene {_texto_limites(faltan)}.")
        else:
            r.manuales.append(f"{texto}: verificar en ICAM que el T/A tenga todos los límites "
                              f"(el Excel solo muestra {', '.join(f'{_fmt(v)} {u}' for u, v in ta.items())}).")
    elif not excedidos:
        r.manuales.append(f"El T/A coincide con el plazo de la descripción ('{frase.strip()}').")


def regla_rir_declarado(dip: dict, ctx: Contexto, r: ResultadoReglas) -> None:
    """Inspección repetitiva que pide la descripción ("every 30 days", "inspect within
    50 FH and correct within 100 FH"): el DIP debe tener ese RIR."""
    declarado = extraer_limites(_texto(dip))
    if not declarado.repetitivos:
        return
    pedidos = [lims for _, lims in declarado.repetitivos if lims]
    texto = "; ".join(f"'{f.strip()}'" for f, _ in declarado.repetitivos)
    rirs = dip.get("rirs")
    if rirs is None:
        r.manuales.append(f"La descripción pide una inspección repetitiva ({texto}): verificar el "
                          "RIR en Follow-on Tasks.")
        return
    if not rirs:
        if dip.get("historico_rir") or dip.get("estado") in ACTIVOS:
            r.agregar(ctx, "rir_descripcion_faltante", "RIR",
                      f"Sin RIR; la descripción pide {texto}.")
        else:
            r.manuales.append(f"La descripción pide una inspección repetitiva ({texto}): el DIP "
                              "está cerrado, verificar el RIR en Show Historical Tasks.")
        return
    con_intervalo = [rir for rir in rirs if rir.limites]
    if not con_intervalo:
        return
    coincide = [rir for rir in con_intervalo
                if any(_mismo(LimiteRIR(lim.valor, lim.unidad), l) for lims in pedidos
                       for lim in lims for l in rir.limites)]
    if not coincide:
        r.agregar(ctx, "rir_descripcion_distinto", "RIR",
                  "RIR cada " + "; ".join(" / ".join(map(str, rir.limites)) for rir in con_intervalo)
                  + f"; la descripción pide {texto}.")
        return
    for lims in pedidos:
        if len(lims) < 2:
            continue
        for rir in coincide:
            unidades = {l.unidad for l in rir.limites}
            faltan = [lim for lim in lims if lim.unidad not in unidades
                      and not (lim.unidad == "MONTH" and "DAY" in unidades)]
            if faltan and rir.fuente == "página del RIR":
                r.agregar(ctx, "rir_descripcion_distinto", "RIR",
                          f"RIR {rir.ids[0]} sin el límite de {_texto_limites(faltan)}; la "
                          f"descripción pide {_texto_limites(lims)} (lo que ocurra primero).")
            elif faltan:
                r.manuales.append(f"La descripción pide el RIR cada {_texto_limites(lims)} (lo que "
                                  f"ocurra primero): verificar en ICAM que tenga todos los límites "
                                  f"(el Excel muestra {' / '.join(map(str, rir.limites))}).")


def regla_vencimiento_declarado(dip: dict, ctx: Contexto, r: ResultadoReglas) -> None:
    """El due date no puede pasar el vencimiento que da la descripción. En un grupo de
    componentes con distintas fechas ("(4 E/A) DUE DATE NOVEMBER/2027 ... (1 E/A) DUE DATE
    OCTOBER/2027") manda el primero que vence."""
    due, found = _como_fecha(dip.get("due_date")), _como_fecha(dip.get("found_date"))
    if due is None:
        return
    fechas = [f for f in fechas_de_vencimiento(_texto(dip)) if not found or f >= found]
    if fechas and due > min(fechas):
        r.agregar(ctx, "due_date_posterior_a_vencimiento_item", "Incorrect Due Date",
                  f"Due date {_fecha(due)}, después del vencimiento del ítem "
                  f"({_fecha(min(fechas))}).")


def regla_sin_ta(dip: dict, ctx: Contexto, r: ResultadoReglas) -> None:
    """Un DIP sin intervalo no tiene plazo. No se marca si solo sigue un RIR (inspección
    repetitiva sin fecha de cierre) o si se abrió y se cerró en el mismo día."""
    if dip.get("intervalo") is not None and dip.get("unidad") is not None:
        return
    if dip.get("icam_intervalos") or dip.get("rirs"):
        return
    completo, found = dip.get("complete_date"), dip.get("found_date")
    if completo and found and completo - found <= timedelta(days=1):
        return
    r.agregar(ctx, "datos_incompletos", "Deferral Interval Not Documented",
              "DIP sin intervalo ni tipo de intervalo (sin T/A ni RIR).")


def revisar_descripcion(dip: dict, entrada: EntradaCatalogo | None, ctx: Contexto,
                        r: ResultadoReglas) -> None:
    """Reglas contra la descripción. Solo en los DIPs que la tabla no tiene."""
    if entrada is not None:
        return
    regla_sin_ta(dip, ctx, r)
    regla_plazo_declarado(dip, ctx, r)
    regla_rir_declarado(dip, ctx, r)
    regla_vencimiento_declarado(dip, ctx, r)


def _codigo_citado(dip: dict) -> str | None:
    """Primera EC/ECRA que cita la descripción. Solo las EC: son de un ítem (7300-0132C,
    toberas de combustible); una AMM puede ser genérica (05-00-00-750-801 revisa los
    mensajes AHM de sistemas distintos: bleed, packs, EEC)."""
    codigos = [c for c in extraer_codigos(sin_task_cards(dip.get("descripcion")))
               if c.startswith("EC ")]
    return codigos[0] if codigos else None


def buscar_parent_distinto_de_pares(dips: list[dict], entradas: list[EntradaCatalogo | None]
                                    ) -> dict[int, tuple[str, int, str]]:
    """Índice del DIP -> (Parent Assembly de los pares, cuántos son, referencia citada).

    Para un DIP que la tabla no tiene, los otros DIPs del lote que citan la misma EC/ECRA
    hacen de referencia: si al menos dos, y todos, están en otro Parent Assembly
    (5 cambios de toberas por la ECRA 7300-0132C en el motor y uno en el avión), se marca."""
    codigos = [_codigo_citado(d) for d in dips]
    tipos = [tipo_parent(d.get("parent_assy") or "") for d in dips]
    salida: dict[int, tuple[str, int, str]] = {}
    for i, (dip, entrada, codigo) in enumerate(zip(dips, entradas, codigos)):
        if entrada is not None or not codigo or not tipos[i]:
            continue
        pares = Counter(tipos[j] for j, c in enumerate(codigos) if j != i and c == codigo and tipos[j])
        if sum(pares.values()) >= 2 and len(pares) == 1 and tipos[i] not in pares:
            tipo, n = next(iter(pares.items()))
            salida[i] = (tipo, n, codigo)
    return salida

