"""Orquesta la auditoría: carga, asociación, reglas, duplicados y resultado."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import yaml

from .asociacion import Asociacion, asociar, asociar_por_codigos, similares_en_tabla
from .cargador import Lote, cargar_export, completar_con_icam
from .discrepancias import Discrepancias, cargar_discrepancias, validar_cobertura
from .referencia_tecnica import (IndiceReferencias, buscar_referencia, cita_barcode, cita_mgm,
                                 es_captura_de_barcode, extraer_codigos, referencias_cargadas, revisar,
                                 sin_task_cards)
from .rir import requerido as rir_requerido, solo_rir
from .rir import revisar as revisar_rir
from .referencias import Catalogo, EntradaCatalogo, cargar_catalogo, cargar_referencias
from .reglas_descripcion import buscar_parent_distinto_de_pares, revisar_descripcion
from .reglas import (ACTIVOS, EXTENSION, MOSTRAR_SEVERIDAD, ORDEN_SEVERIDAD, POSIBLE_DISCREPANCIA,
                     REVISAR, SEVERIDAD_SIN_FUENTE, SIN_FUENTE, Contexto, Hallazgo, auditar_dip, buscar_duplicados,
                     buscar_sn_repetidos, dip_por_error, estado_final, etapa,
                     referencia_y_adjunto_exigibles)

RAIZ = Path(__file__).resolve().parent.parent
FUERA_DE_ALCANCE = "FUERA DE ALCANCE"
CORREGIDO_EN_CIERRE = "CORREGIDO EN CIERRE"
CODIGOS_DUPLICADO = {"duplicado", "duplicado_declarado", "sn_repetido"}
# CORREGIDO EN CIERRE identifica discrepancias de apertura con cierre OK.
RESULTADOS = {POSIBLE_DISCREPANCIA: POSIBLE_DISCREPANCIA, EXTENSION: EXTENSION,
              REVISAR: REVISAR, SIN_FUENTE: SIN_FUENTE,
              "OK": "OK", CORREGIDO_EN_CIERRE: CORREGIDO_EN_CIERRE, FUERA_DE_ALCANCE: FUERA_DE_ALCANCE}


def cierre_auditado_ok(dip: dict) -> bool:
    """El auditor marcó el cierre en Technical References ("DIP CLOSED - RT AUDIT
    COMPLETED") sin discrepancia."""
    return any(m.startswith("Cierre: sin discrepancia") for m in dip.get("auditoria_manual") or [])


def cargar_configuracion(ruta: Path | None = None) -> dict:
    ruta = Path(ruta) if ruta else RAIZ / "config" / "config.yaml"
    config = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    config.setdefault("carpeta_pruebas", "pruebas")
    for clave in ("referencias", "catalogo", "carpeta_salida", "discrepancias", "carpeta_pruebas"):
        if clave == "referencias" and str(config[clave]).lower().startswith("https://"):
            continue
        p = Path(config[clave])
        config[clave] = p if p.is_absolute() else RAIZ / p
    icam = config.get("icam")
    if icam:
        for clave in ("perfil", "archivo"):
            p = Path(icam[clave])
            icam[clave] = p if p.is_absolute() else RAIZ / p
    return config


@dataclass
class ResultadoAuditoria:
    lote: Lote
    filas: pd.DataFrame        # una fila por DIP (resultado + datos clave)
    hallazgos: pd.DataFrame    # una fila por hallazgo
    advertencias: list[str] = field(default_factory=list)
    segundos: float = 0.0
    asociaciones: list[Asociacion | None] = field(default_factory=list)  # una por DIP

    def conteo_estados(self) -> dict[str, int]:
        return self.filas["ESTADO IA"].value_counts().to_dict()

    def hallazgos_auditoria_actual(self) -> pd.DataFrame:
        """Hallazgos de apertura para DIPs abiertos y de cierre para los COMPLETE."""
        h = self.hallazgos
        auditorias = self.filas.set_index("Fila Excel")["AUDITORÍA"]
        return h[(h["Auditoría"] == h["Fila Excel"].map(auditorias))
                 | (h["Severidad"] == SEVERIDAD_SIN_FUENTE) | (h["Código"] == "dip_extendido")]



class Auditor:
    def __init__(self, config: dict, fecha_auditoria: datetime | date | None = None):
        self.config = config
        # Día y hora en que se audita (por defecto, ahora).
        self.fecha_auditoria = fecha_auditoria or datetime.now().replace(second=0, microsecond=0)
        referencias = cargar_referencias(config["referencias"], config.get("hoja_referencias",
                                                                             "References"))
        self.catalogo: Catalogo = cargar_catalogo(config["catalogo"], referencias)
        self.indice_referencias = IndiceReferencias.desde_catalogo(self.catalogo)
        # Tipos de DIP que se auditan; None = todos.
        tipos = config.get("tipos_auditados")
        self.tipos = {str(t).upper() for t in tipos} if tipos else None
        tol = config.get("tolerancias", {})
        self.discrepancias: Discrepancias = cargar_discrepancias(config["discrepancias"])
        validar_cobertura(self.discrepancias)
        self._ctx_base = dict(
            discrepancias=self.discrepancias,
            tol_dias=tol.get("dias", 1), meses_min=tol.get("meses_min", 30),
            meses_max=tol.get("meses_max", 31), horas_cierre=tol.get("horas_cierre", 0),
            inicio_fh=tol.get("inicio_fh", 2), inicio_fc=tol.get("inicio_fc", 0),
            revision_opcional=frozenset(
                str(m).upper() for m in (config.get("referencia_tecnica") or {}).get(
                    "revision_opcional", [])))

    def contexto(self, fecha: datetime | date | None = None) -> Contexto:
        return Contexto(fecha_referencia=fecha or self.fecha_auditoria, **self._ctx_base)

    def auditar_archivo(self, ruta: Path, hoja: str | None = None,
                        icam: Path | None = None) -> ResultadoAuditoria:
        """`icam`: archivo con datos extraídos de ICAM (referencia técnica), por barcode."""
        lote = cargar_export(ruta, hoja)
        lote.prueba = bool(self.config.get("modo_prueba"))
        if icam:
            completar_con_icam(lote, icam)
        return self.auditar_lote(lote)

    def auditar_lote(self, lote: Lote, fechas_referencia: list | None = None) -> ResultadoAuditoria:
        """`fechas_referencia`: día y hora de auditoría de cada DIP (None = la del auditor)."""
        inicio = time.perf_counter()
        dips = lote.datos.to_dict("records")
        en_alcance = [self.tipos is None or not d["tipo"] or d["tipo"].upper() in self.tipos
                      for d in dips]

        asociaciones: list[Asociacion | None] = [
            self._asociar(dip) if alcance else None for dip, alcance in zip(dips, en_alcance)]
        entradas = [a.entrada if a else None for a in asociaciones]
        # Duplicados y S/N repetidos se buscan sobre el subconjunto en alcance;
        # luego se remapean los índices al lote completo.
        indices_alcance = [i for i, a in enumerate(en_alcance) if a]
        dips_alcance = [dips[i] for i in indices_alcance]
        duplicados = buscar_duplicados(dips_alcance, [entradas[i] for i in indices_alcance],
                                       self._ctx_base["tol_dias"])
        duplicados = {indices_alcance[k]: v for k, v in duplicados.items()}
        sn_repetidos = {indices_alcance[k]: v
                        for k, v in buscar_sn_repetidos(dips_alcance).items()}
        # DIPs SIN FUENTE en otro Parent Assembly que los demás con la misma EC/AMM/SRM.
        parent_pares = {indices_alcance[k]: v for k, v in buscar_parent_distinto_de_pares(
            dips_alcance, [entradas[i] for i in indices_alcance]).items()}

        filas, hallazgos = [], []
        for i, (dip, alcance, asoc) in enumerate(zip(dips, en_alcance, asociaciones)):
            if not alcance:
                filas.append(self._fila(dip, None, None, None))
                continue
            fecha = fechas_referencia[i] if fechas_referencia else None
            fecha = None if fecha is None or pd.isna(fecha) else fecha
            ctx = self.contexto(fecha)
            r = auditar_dip(dip, asoc.entrada, ctx)
            self._referencia_tecnica(dip, asoc, ctx, r)
            self._rir(dip, asoc, ctx, r)
            revisar_descripcion(dip, asoc.entrada, ctx, r)
            if i in parent_pares:
                tipo, n, codigo = parent_pares[i]
                r.agregar(ctx, "parent_assy_distinto_a_pares", "Incorrect Parent Assembly",
                          f"Asignado a {dip['parent_tipo']}; los otros {n} DIPs con la {codigo} "
                          f"están en {tipo}.")
            if dip.get("intervalo_de_icam") and not solo_rir(dip):
                r.agregar(ctx, "intervalo_de_icam", "Missing Data",
                          f"Sin intervalo en el Excel; se usó el de ICAM "
                          f"({dip['intervalo']:g} {dip['tipo_intervalo_original']}).")
            if asoc.metodo == "REGLAS" and asoc.detalle:
                r.agregar(ctx, "asociacion_aproximada", "Reference Match",
                          f"Fault Name con error de escritura: {asoc.detalle}")
            elif asoc.metodo == "REF_TECNICA":
                r.agregar(ctx, "asociacion_por_referencia_tecnica", "Reference Match",
                          f"Referencia '{asoc.entrada.nombre}' identificada por la referencia "
                          f"técnica {asoc.detalle}.")
            elif asoc.metodo == "DESCRIPCION":
                r.agregar(ctx, "asociacion_por_descripcion", "Reference Match",
                          f"Referencia '{asoc.entrada.nombre}' identificada por la descripción. "
                          f"Verificar.")
            if asoc.entrada is not None and asoc.entrada.automatica:
                r.agregar(ctx, "asociacion_por_tabla", "Reference Match",
                          f"Fila {asoc.entrada.referencias[0].fila} de la tabla sin entrada en "
                          f"el catálogo: identificada por sus palabras o su referencia técnica. "
                          f"Verificar.")
            if asoc.entrada is None:
                if asoc.metodo == "AMBIGUA":
                    motivo = f"varias referencias posibles ({', '.join(asoc.candidatos[:3])})"
                else:
                    motivo = "no está en la tabla de referencias"
                similares = similares_en_tabla(dip["nombre"], self.catalogo)
                pista = "; ".join(f"'{f.descripcion}' ({f.tipo}, fila {f.fila})"
                                  for f, _ in similares)
                r.agregar(ctx, "sin_referencia", "Missing Reference in Table",
                          f"{SIN_FUENTE}: {motivo}.")
                if pista:
                    r.manuales.append(f"Parecido en la tabla: {pista}.")
                otros_tipos = {f.tipo for f, p in similares
                               if p >= 90 and f.tipo.upper() != (dip["tipo"] or "").upper()}
                if otros_tipos and dip["tipo"]:
                    r.agregar(ctx, "tipo_dip_distinto_a_referencia", "Incorrect DIP Type",
                              f"Abierto como {dip['tipo']}; parece {'/'.join(sorted(otros_tipos))}.")
            if i in duplicados:
                otro_barcode, _ = duplicados[i]
                r.agregar(ctx, "duplicado", "Duplicated DIP",
                          f"Posible duplicado de {otro_barcode}.")
            elif i in sn_repetidos:
                r.agregar(ctx, "sn_repetido", "Incorrect S/N",
                          f"S/N repetido en otro DIP que estuvo abierto al mismo tiempo: "
                          f"{', '.join(sn_repetidos[i])}.")
            self._por_error(dip, ctx, r)
            marcas = dip.get("auditoria_manual") or dip.get("marcas_auditdip")
            if marcas:
                r.manuales.insert(0, "Ya se había auditado manualmente (Technical References "
                                  f"en ICAM): {'; '.join(marcas)}.")
            filas.append(self._fila(dip, asoc, r, ctx.fecha_referencia))
            for h in r.hallazgos:
                hallazgos.append({
                    "Fila Excel": dip["fila"], "Fault Barcode": dip["barcode"],
                    "Aircraft": dip["avion"], "Fault Name": dip["nombre"],
                    "Auditoría": etapa(h.codigo), "Severidad": h.severidad, "Tipo de discrepancia": h.categoria,
                    "Código": h.codigo, "Detalle": h.mensaje,
                })

        resultado = ResultadoAuditoria(
            lote=lote, filas=pd.DataFrame(filas),
            hallazgos=pd.DataFrame(hallazgos, columns=[
                "Fila Excel", "Fault Barcode", "Aircraft", "Fault Name", "Auditoría", "Severidad",
                "Tipo de discrepancia", "Código", "Detalle"]),
            advertencias=list(lote.notas) + self._nota_categorias(),
            segundos=time.perf_counter() - inicio,
            asociaciones=asociaciones,
        )
        return resultado

    def _nota_categorias(self) -> list[str]:
        d = self.discrepancias
        if d.solo is None or d.solo >= set(d.tipos):
            return []
        revisados = [t for t, activo in d.tipos.items() if activo and t in d.solo]
        return ["Solo se revisaron estos tipos de discrepancia (--categorias): "
                + (", ".join(revisados) or "ninguno") + "."]

    def _referencia_tecnica(self, dip: dict, asoc: Asociacion, ctx, r) -> None:
        """Apertura: el DIP debe tener su referencia técnica, y debe ser la de la tabla.

        Como la acepta el auditor, sirve cualquiera de estas: cargada en ICAM (Technical
        References), una captura adjunta o citada en la descripción. Si falta la revisión o
        su fecha, se anota con estado OK (salvo en los manuales de revision_opcional de
        config.yaml). El MGM no es referencia técnica. Las task cards (JIC) sí son
        referencia técnica, en ICAM, en la descripción o en un attachment; para comparar
        con la tabla, las de la descripción se toman como la tarea donde se encontró la
        falla. Un barcode de trabajo citado como fuente ("IAW BARCODE: TRF7N00900V4,
        STEP 63") sin referencia del manual es una referencia no específica."""
        if not dip.get("datos_referencia"):
            return  # no hay descripción ni referencias: no se puede revisar
        cargadas = referencias_cargadas(dip.get("referencia_tecnica"))
        adjuntos = dip.get("adjuntos")
        descripcion = sin_task_cards(dip.get("descripcion"))
        accion = dip.get("accion_correctiva") if dip.get("estado") == "COMPLETE" else None
        encontrada = buscar_referencia("; ".join(cargadas), dip.get("descripcion"),
                                       dip.get("notas_descripcion"), accion, dip.get("nombre"))
        evidencia = [*(cargadas or [str(encontrada)]), *(f"Adjunto: {a}" for a in adjuntos or [])]
        dip["referencia_encontrada"] = "; ".join(x for x in dict.fromkeys(evidencia) if x)
        if not referencia_y_adjunto_exigibles(dip):
            return
        esperada = (self.indice_referencias.por_entrada.get(asoc.entrada.id)
                    if asoc.entrada else None)
        corresponde = f" Corresponde {', '.join(sorted(esperada))}." if esperada else ""
        if not (cargadas or adjuntos or encontrada.manual):
            if adjuntos is None:  # sin datos de ICAM no se sabe si hay captura adjunta
                r.manuales.append("Verificar la referencia técnica." + corresponde)
            else:
                mgm = cita_mgm(dip.get("referencia_tecnica"), descripcion,
                               dip.get("notas_descripcion"), dip.get("nombre"))
                r.agregar(ctx, "sin_referencia_tecnica", "Missing Technical Reference",
                          "Sin referencia técnica"
                          + (" (el MGM no es referencia técnica)." if mgm else ".")
                          + corresponde)
        elif (encontrada.manual and not adjuntos
              and encontrada.faltantes_exigidos(ctx.revision_opcional)):
            r.agregar(ctx, "referencia_tecnica_incompleta", "Missing Technical Reference",
                      f"Referencia técnica sin {' ni '.join(encontrada.faltantes)} "
                      f"({encontrada}).")
        elif (adjuntos and not cargadas and not encontrada.manual
              and all(es_captura_de_barcode(a) for a in adjuntos)):
            # T40S009H9BB: sin cita y como único attachment la captura de un barcode de trabajo.
            r.agregar(ctx, "sin_referencia_tecnica", "Missing Technical Reference",
                      "Sin referencia técnica: el attachment es de un barcode de trabajo."
                      + corresponde)
        barcode = cita_barcode(dip.get("descripcion"), dip.get("notas_descripcion"))
        if barcode and (not encontrada.manual or encontrada.tipo == "TASK CARD"):
            r.agregar(ctx, "referencia_tecnica_no_especifica", "Non-Specific Technical Reference",
                      f"Cita el barcode {barcode}, no el manual." + corresponde)
        if asoc.entrada:
            # Una task card JIC adjunta, como en la descripción, suele ser la tarea donde se
            # encontró la falla (el Service Visit): no se compara, salvo que sea la de la tabla.
            citadas = extraer_codigos("; ".join([dip.get("descripcion") or "", *(adjuntos or [])]))
            if esperada and {c for c in citadas if c.startswith("JIC")} & esperada:
                return
            texto = "; ".join(x for x in (*cargadas, *map(sin_task_cards, adjuntos or []),
                                          descripcion, accion or "") if x.strip())
            if not extraer_codigos(texto):
                return  # sin número de tarea que comparar con la tabla
            revision = revisar(texto, asoc.entrada, self.catalogo, self.indice_referencias)
            if revision and revision.codigo and revision.codigo != "sin_referencia_tecnica":
                severidad = None
                if revision.codigo == "referencia_tecnica_distinta":
                    citados = extraer_codigos(texto)
                    grave = ((any(c.startswith("EC ") for c in esperada or ()) and
                              not set(citados) & set(esperada or ()))
                             or (citados and all(c.startswith("JIC") for c in citados)))
                    severidad = None if grave else "OK"
                r.agregar(ctx, revision.codigo, "Incorrect Technical Reference",
                          revision.mensaje, severidad)

    def _rir(self, dip: dict, asoc: Asociacion, ctx, r) -> None:
        """RIR del DIP (columnas Rir del Excel o Follow-on Tasks de ICAM) contra la referencia y el T/A."""
        from .rir import remanentes_inverosimiles

        rirs = list(dip.get("rirs_excel") or [])
        if dip.get("rirs") is not dip.get("rirs_excel"):
            rirs += dip.get("rirs") or []
        for mensaje in remanentes_inverosimiles(rirs):
            r.agregar(ctx, "rir_restante_inverosimil", "RIR", mensaje)
        entrada = asoc.entrada
        sin_ta = solo_rir(dip)
        if entrada and entrada.rir_segun_manual:
            # El RIR cambia según el daño o la medición: no se compara, se revisa en el manual.
            rirs = dip.get("rirs")
            en_icam = ("" if rirs is None else " En ICAM: " + ("; ".join(map(str, rirs))
                                                              if rirs else "sin RIR") + ".")
            manual = entrada.referencias_tecnicas
            r.agregar(ctx, "rir_segun_manual", "RIR",
                      f"La referencia da el RIR según el daño o el tipo "
                      f"('{entrada.rir_segun_manual}'). Revisar en el manual"
                      + (f" ({manual})." if manual else ".") + en_icam)
            r.manuales = [m for m in r.manuales if not m.startswith("Verificar RIR")]
            if sin_ta and rirs is not None:
                for codigo, mensaje in revisar_rir(rirs, None, dip):
                    r.agregar(ctx, codigo, "RIR", mensaje)
            return
        if dip.get("rirs") is None:
            if sin_ta:
                r.manuales.append("Verificar RIR en Follow-on Tasks: DIP de boroscope sin T/A.")
            return  # sin datos de RIR: queda la verificación manual
        texto = ""
        if entrada:
            variante = next((v for v in entrada.variantes if v.nombre == r.variante and v.rir), None)
            variante = variante or next((v for v in entrada.variantes if v.rir), None)
            texto = variante.rir if variante else ""
        for codigo, mensaje in revisar_rir(dip["rirs"], rir_requerido(texto), dip):
            r.agregar(ctx, codigo, "RIR", mensaje)
        exigido = rir_requerido(texto)
        if (exigido or sin_ta) and not dip["rirs"] and not dip.get("historico_rir") and \
                dip.get("estado") not in {"ACTV", "OPEN", "IN WORK"}:
            r.manuales = [m for m in r.manuales if not m.startswith("Verificar RIR")]
            r.manuales.append((f"Verificar RIR cada {exigido}" if exigido else "Verificar RIR")
                              + " en Follow-on Tasks "
                              "(Show Historical Tasks): el DIP está cerrado.")
        elif dip["rirs"] or exigido or sin_ta:
            r.manuales = [m for m in r.manuales if not m.startswith("Verificar RIR")]

    def _asociar(self, dip: dict) -> Asociacion:
        """Por el Fault Name. Si no alcanza, en este orden:

        1. La referencia técnica cargada en ICAM, si corresponde a una sola referencia.
        2. El Fault Name junto con la descripción, con las mismas palabras clave ("AFT
           PASSENGER CABIN LESS THAN 130 DAYS" -> la descripción dice FIRST AID KIT; "BIRD
           STRIKE" en el nombre y "BOROSCOPE INSPECTION ENG 2" en la descripción), salvo que
           la descripción cite una tarea que no es la de esa referencia: entonces el DIP
           sigue otra fuente (una muestra de combustible por la SUBTASK 28-10-00-280-056 no
           es FUEL MICROBIAL GROWTH, 4 DAYS).
        3. La tarea citada en la descripción ("IAW EC/RA 2500-0538C" -> LIFEVEST DOOR LATCH).

        Las task cards JIC de la descripción no cuentan: son la tarea donde se encontró la
        falla, no la fuente del DIP."""
        a = asociar(dip["nombre"], self.catalogo)
        if a.entrada is not None:
            return a
        # Una SRM (53-00-01) es un capítulo de daños admisibles, no un ítem: no asocia.
        codigos = [c for c in extraer_codigos(dip.get("referencia_tecnica")) if not c.startswith("SRM")]
        entrada = asociar_por_codigos(codigos, self.catalogo, self.indice_referencias)
        descripcion = sin_task_cards(dip.get("descripcion"))
        citados = [c for c in extraer_codigos(descripcion) if not c.startswith("SRM")]
        d = asociar(f"{dip['nombre'] or ''} {descripcion}", self.catalogo, aproximada=False)
        por_descripcion = None
        if d.entrada:
            esperados = self.indice_referencias.por_entrada.get(d.entrada.id, set())
            if not citados or not esperados or esperados & set(citados):
                por_descripcion = d.entrada
        # Si la referencia cargada es de un ítem y la descripción dice otro, manda la
        # descripción (un mensaje LONG TIME con la AMM del EGT cargada): la revisión de la
        # referencia técnica marca después que la cargada es de otra referencia.
        if entrada and not (por_descripcion and por_descripcion.id != entrada.id):
            return Asociacion(entrada, "REF_TECNICA", detalle=", ".join(codigos),
                              candidatos=a.candidatos)
        if por_descripcion:
            return Asociacion(por_descripcion, "DESCRIPCION", candidatos=a.candidatos)
        entrada = asociar_por_codigos(citados, self.catalogo, self.indice_referencias)
        if entrada:
            return Asociacion(entrada, "REF_TECNICA",
                              detalle=", ".join(citados) + " (en la descripción)",
                              candidatos=a.candidatos)
        return a

    @staticmethod
    def _por_error(dip: dict, ctx, r) -> None:
        """Conserva solo la declaración: un duplicado sigue siendo discrepancia al cerrar;
        un DIP creado por error, sin declaración de duplicado, queda OK si ya cerró."""
        mensaje = dip_por_error(dip)
        if not mensaje or not ctx.discrepancias.activa("duplicado_declarado", "Duplicated DIP"):
            return
        duplicados = [h for h in r.hallazgos
                      if h.codigo in CODIGOS_DUPLICADO and h.severidad == POSIBLE_DISCREPANCIA]
        r.hallazgos, r.manuales, r.intervalo_ok = [], [], False
        if duplicados and mensaje.startswith("DIP creado por error"):
            r.hallazgos = duplicados
            return
        cerrado_por_error = dip["estado"] not in ACTIVOS and mensaje.startswith("DIP creado por error")
        r.agregar(ctx, "duplicado_declarado", "Duplicated DIP", mensaje,
                  "OK" if cerrado_por_error else None)

    @staticmethod
    def _comentario(r, hallazgos: list[Hallazgo] | None = None) -> str:
        """Texto para ICAM: datos y correcciones del DIP, sin mencionar el Excel."""
        if any(h.codigo == "duplicado_declarado" for h in r.hallazgos):
            return r.hallazgos[0].mensaje
        partes = []
        if hallazgos is None and r.intervalo_ok:
            partes.append("T/A aperturado correctamente")
        # Las consultas al manual y extensiones son revisiones para el auditor.
        hallazgos = [h for h in (r.hallazgos if hallazgos is None else hallazgos)
                     if h.severidad not in {"OK", REVISAR, EXTENSION}]
        codigos = {h.codigo for h in hallazgos}
        for h in hallazgos:
            # Cerrado sin attachments también es "sin attachments" de la apertura: el
            # comentario lo dice una vez (HALLAZGOS conserva los dos, uno por auditoría).
            if h.codigo == "cierre_sin_adjuntos" and "sin_adjuntos" in codigos:
                continue
            mensaje = h.mensaje
            if h.codigo == "datos_incompletos" and "excel" in mensaje.lower():
                mensaje = "Verificar el intervalo y el tipo de intervalo del T/A en ICAM."
            # La procedencia del remanente sirve a la auditoría; el comentario conserva
            # el barcode, el valor, la unidad y el intervalo que se debe revisar en ICAM.
            mensaje = re.sub(r"\s*\(\s*Excel\s*\)", "", mensaje, flags=re.IGNORECASE)
            partes.append(mensaje)
        return " // ".join(partes)

    @classmethod
    def _fila(cls, dip: dict, asoc: Asociacion | None, r, fecha) -> dict:
        entrada: EntradaCatalogo | None = asoc.entrada if asoc else None
        hallazgos = sorted(r.hallazgos if r else [], key=lambda h: -ORDEN_SEVERIDAD[h.severidad])
        manuales = r.manuales if r else []
        en_alcance = r is not None
        # Apertura: DIP abierto. Cierre: DIP COMPLETE (se informan también los de apertura).
        cierre = en_alcance and dip["estado"] == "COMPLETE"
        de_cierre = [h for h in hallazgos if etapa(h.codigo) == "CIERRE"]
        de_apertura = [h for h in hallazgos if etapa(h.codigo) == "APERTURA"]
        # Sin fuente vale para las dos auditorías: el DIP no está en la tabla.
        sin_fuente = [h for h in de_apertura if h.severidad == SEVERIDAD_SIN_FUENTE]
        # La duplicación se conserva en el cierre aunque cualquiera de los DIPs ya cerró.
        duplicados = [h for h in de_apertura
                      if h.codigo in CODIGOS_DUPLICADO and h.severidad == POSIBLE_DISCREPANCIA]
        extensiones = [h for h in de_apertura if h.codigo == "dip_extendido"]
        aplican_al_cierre = de_cierre + sin_fuente + duplicados + extensiones
        estado_apertura = estado_final(de_apertura) if en_alcance else ""
        estado_cierre = estado_final(aplican_al_cierre) if cierre else ""
        estado = (estado_cierre if cierre else estado_apertura) if en_alcance else FUERA_DE_ALCANCE
        if cierre and estado_apertura == POSIBLE_DISCREPANCIA and estado_cierre == "OK":
            estado = CORREGIDO_EN_CIERRE
        if cierre and estado not in {"OK", EXTENSION} and not duplicados and cierre_auditado_ok(dip):
            # El OK manual resuelve las discrepancias de cierre; una extensión sigue
            # pendiente de revisión. Los estados y hallazgos conservan la evidencia.
            revisado = estado_final(extensiones)
            manuales = [*manuales, f"Resultado {revisado} por la auditoría manual de cierre en ICAM; "
                        f"el programa dio {estado}: revisar los hallazgos."]
            estado = revisado
        comentario = cls._comentario(r, aplican_al_cierre if cierre else None) if r else ""
        return {
            "Fila Excel": dip["fila"],
            "Fault Barcode": dip["barcode"],
            "Aircraft": dip["avion"],
            "Flota": dip.get("flota") or "",
            "Fault Name": dip["nombre"],
            "DIP Interval": dip["intervalo"],
            "Interval Type": dip["tipo_intervalo_original"],
            "Fault Status": dip["estado"],
            "RESULTADO": RESULTADOS.get(estado, estado),
            "ESTADO IA": estado,
            "AUDITORÍA": ("CIERRE" if cierre else "APERTURA") if en_alcance else "",
            "FECHA AUDITORÍA": fecha,
            "ESTADO APERTURA": estado_apertura,
            "ESTADO CIERRE": estado_cierre,
            "HALLAZGOS": "\n".join(
                f"[{MOSTRAR_SEVERIDAD[h.severidad]}]"
                f"{' [CIERRE]' if h in de_cierre else ' [APERTURA]' if cierre else ''} {h.mensaje}"
                for h in hallazgos),
            "COMENTARIO SUGERIDO": comentario,
            "VERIFICACIÓN MANUAL": "\n".join(f"- {m}" for m in manuales),
            "REFERENCIA ASOCIADA": entrada.nombre if entrada else "",
            "ASOCIACIÓN": (f"{asoc.metodo} ({asoc.confianza})" if asoc else ""),
            "TA SEGÚN REFERENCIA": "No aplica: solo RIR (boroscope)." if en_alcance and solo_rir(dip)
            else "\n".join(
                f"{x.descripcion}: {x.ta}" + (f" / RIR {x.rir}" if x.rir else "")
                for x in entrada.referencias) if entrada else "",
            "REFERENCIA TÉCNICA ESPERADA": entrada.referencias_tecnicas if entrada else "",
            "REFERENCIA TÉCNICA DEL DIP": dip.get("referencia_encontrada") or "",
            "RIR EN ICAM": ("" if dip.get("rirs") is None
                            else "; ".join(map(str, dip["rirs"])) or "Sin RIR"),
            "AUDITORÍA MANUAL EN ICAM": "\n".join(dip.get("auditoria_manual") or []),
            "ADJUNTOS EN ICAM": ("" if dip.get("adjuntos") is None
                                 else f"{len(dip['adjuntos'])}: " + ", ".join(dip["adjuntos"])
                                 if dip["adjuntos"] else "0"),
        }
