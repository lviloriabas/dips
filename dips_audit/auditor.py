"""Orquesta la auditoría: carga, asociación, reglas, duplicados y resultado."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import yaml

from .asociacion import Asociacion, asociar, similares_en_tabla
from .cargador import Lote, cargar_export, completar_con_icam
from .discrepancias import Discrepancias, cargar_discrepancias
from .referencia_tecnica import (IndiceReferencias, buscar_referencia, cita_mgm,
                                 extraer_codigos, referencias_cargadas, revisar, sin_task_cards)
from .rir import requerido as rir_requerido
from .rir import revisar as revisar_rir
from .referencias import Catalogo, EntradaCatalogo, cargar_catalogo, cargar_referencias
from .reglas import (MOSTRAR_SEVERIDAD, POSIBLE_DISCREPANCIA, Contexto, Hallazgo, auditar_dip,
                     buscar_duplicados, buscar_sn_repetidos, estado_final, etapa)

RAIZ = Path(__file__).resolve().parent.parent
FUERA_DE_ALCANCE = "FUERA DE ALCANCE"
# Resultado para el auditor. Por ahora solo OK o POSIBLE DISCREPANCIA (ver reglas.ESTADOS).
RESULTADOS = {POSIBLE_DISCREPANCIA: POSIBLE_DISCREPANCIA, "OK": "OK",
              FUERA_DE_ALCANCE: FUERA_DE_ALCANCE}


def cargar_configuracion(ruta: Path | None = None) -> dict:
    ruta = Path(ruta) if ruta else RAIZ / "config" / "config.yaml"
    config = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    config.setdefault("carpeta_pruebas", "pruebas")
    for clave in ("referencias", "catalogo", "carpeta_salida", "discrepancias", "carpeta_pruebas"):
        p = Path(config[clave])
        config[clave] = p if p.is_absolute() else RAIZ / p
    icam = config.get("icam")
    if icam:
        for clave in ("perfil", "carpeta"):
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


class Auditor:
    def __init__(self, config: dict, fecha_auditoria: datetime | date | None = None):
        self.config = config
        # Día y hora en que se audita (por defecto, ahora).
        self.fecha_auditoria = fecha_auditoria or datetime.now().replace(second=0, microsecond=0)
        referencias = cargar_referencias(config["referencias"], config.get("hoja_referencias",
                                                                             "References"))
        self.catalogo: Catalogo = cargar_catalogo(config["catalogo"], referencias)
        self.indice_referencias = IndiceReferencias.desde_catalogo(self.catalogo)
        self.tipos = {t.upper() for t in config.get("tipos_auditados", ["Others"])}
        tol = config.get("tolerancias", {})
        self.discrepancias: Discrepancias = cargar_discrepancias(config["discrepancias"])
        self._ctx_base = dict(
            discrepancias=self.discrepancias,
            tol_dias=tol.get("dias", 1), meses_min=tol.get("meses_min", 30),
            meses_max=tol.get("meses_max", 31), horas_cierre=tol.get("horas_cierre", 0),
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
        en_alcance = [not d["tipo"] or d["tipo"].upper() in self.tipos for d in dips]

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

        filas, hallazgos = [], []
        for i, (dip, alcance, asoc) in enumerate(zip(dips, en_alcance, asociaciones)):
            if not alcance:
                filas.append(self._fila(dip, None, None, [], [], FUERA_DE_ALCANCE, "", None))
                continue
            fecha = fechas_referencia[i] if fechas_referencia else None
            fecha = None if fecha is None or pd.isna(fecha) else fecha
            ctx = self.contexto(fecha)
            r = auditar_dip(dip, asoc.entrada, ctx)
            self._referencia_tecnica(dip, asoc, ctx, r)
            self._rir(dip, asoc, ctx, r)
            if dip.get("intervalo_de_icam"):
                r.agregar(ctx, "intervalo_de_icam", "Missing Data",
                          f"El Excel de entrada no trae intervalo: se usó el de ICAM "
                          f"({dip['intervalo']:g} {dip['tipo_intervalo_original']}).")
            if asoc.metodo == "REGLAS" and asoc.detalle:
                r.agregar(ctx, "asociacion_aproximada", "Reference Match",
                          f"Fault Name con error de escritura: {asoc.detalle}")
            elif asoc.metodo == "REF_TECNICA":
                r.agregar(ctx, "asociacion_por_referencia_tecnica", "Reference Match",
                          f"Referencia '{asoc.entrada.nombre}' identificada por la referencia "
                          f"técnica {asoc.detalle}, no por el Fault Name.")
            if asoc.entrada is None:
                if asoc.metodo == "AMBIGUA":
                    motivo = f"coincide con varias referencias ({', '.join(asoc.candidatos[:3])})"
                else:
                    motivo = "no se encontró en el catálogo de referencias Others"
                similares = similares_en_tabla(dip["nombre"], self.catalogo)
                pista = "; ".join(f"'{f.descripcion}' ({f.tipo}, fila {f.fila})"
                                  for f, _ in similares)
                r.agregar(ctx, "sin_referencia", "Missing Reference in Table",
                          f"El DIP {motivo}. Revisar manualmente."
                          + (f" Parecido en la tabla: {pista}." if pista else ""))
                otros_tipos = {f.tipo for f, p in similares if p >= 90} - self.tipos
                if otros_tipos and dip["tipo"]:
                    r.agregar(ctx, "tipo_dip_distinto_a_referencia", "Incorrect DIP Type",
                              f"Abierto como {dip['tipo']}, pero se parece a una referencia "
                              f"{'/'.join(sorted(otros_tipos))}.")
            if i in duplicados:
                otro_barcode, otro_nombre = duplicados[i]
                r.agregar(ctx, "duplicado", "Duplicated DIP",
                          f"Posible DIP duplicado de {otro_barcode} ('{otro_nombre}'): mismo "
                          f"avión, mismo componente y abiertos al mismo tiempo.")
            elif i in sn_repetidos:
                r.agregar(ctx, "sn_repetido", "Incorrect S/N",
                          f"El mismo S/N aparece en otro DIP activo del avión: "
                          f"{', '.join(sn_repetidos[i])}.")
            estado = estado_final(r.hallazgos)
            comentario = self._comentario(r)
            filas.append(self._fila(dip, asoc, r, r.hallazgos, r.manuales, estado, comentario,
                                    ctx.fecha_referencia))
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
        su fecha, se anota como observación (salvo en los manuales de revision_opcional de
        config.yaml). El MGM no es referencia técnica. Las task cards JIC de la descripción
        son la tarea donde se encontró la falla, no la referencia del DIP."""
        if not dip.get("datos_referencia"):
            return  # no hay descripción ni referencias: no se puede revisar
        cargadas = referencias_cargadas(dip.get("referencia_tecnica"))
        adjuntos = dip.get("adjuntos")
        descripcion = sin_task_cards(dip.get("descripcion"))
        encontrada = buscar_referencia("; ".join(cargadas), descripcion,
                                       sin_task_cards(dip.get("notas_diferimiento")),
                                       sin_task_cards(dip.get("nombre")))
        evidencia = [*(cargadas or [str(encontrada)]), *(f"Adjunto: {a}" for a in adjuntos or [])]
        dip["referencia_encontrada"] = "; ".join(x for x in dict.fromkeys(evidencia) if x)
        esperada = (self.indice_referencias.por_entrada.get(asoc.entrada.id)
                    if asoc.entrada else None)
        corresponde = f" Corresponde {', '.join(sorted(esperada))}." if esperada else ""
        if not (cargadas or adjuntos or encontrada.manual):
            if adjuntos is None:  # sin datos de ICAM no se sabe si hay captura adjunta
                r.manuales.append("Verificar en ICAM la referencia técnica (Technical References "
                                  "o captura adjunta)." + corresponde)
            else:
                mgm = cita_mgm(dip.get("referencia_tecnica"), descripcion,
                               dip.get("notas_diferimiento"), dip.get("nombre"))
                r.agregar(ctx, "sin_referencia_tecnica", "Missing Technical Reference",
                          "Sin referencia técnica: no está cargada en ICAM, no tiene captura "
                          "adjunta ni se cita en la descripción"
                          + (" (cita el MGM, que no es referencia técnica)." if mgm else ".")
                          + corresponde)
        elif (encontrada.manual and not adjuntos
              and encontrada.faltantes_exigidos(ctx.revision_opcional)):
            r.agregar(ctx, "referencia_tecnica_incompleta", "Missing Technical Reference",
                      f"Referencia técnica sin {' ni '.join(encontrada.faltantes)} "
                      f"({encontrada}).")
        if asoc.entrada:
            texto = "; ".join(x for x in (*cargadas, *(adjuntos or []), descripcion) if x)
            if not extraer_codigos(texto):
                return  # sin número de tarea que comparar con la tabla
            revision = revisar(texto, asoc.entrada, self.catalogo, self.indice_referencias)
            if revision and revision.codigo and revision.codigo != "sin_referencia_tecnica":
                r.agregar(ctx, revision.codigo, "Incorrect Technical Reference",
                          revision.mensaje)

    def _rir(self, dip: dict, asoc: Asociacion, ctx, r) -> None:
        """RIR del DIP (columnas Rir del Excel o Follow-on Tasks de ICAM) contra la referencia y el T/A."""
        if dip.get("rirs") is None:
            return  # sin datos de RIR: queda la verificación manual
        entrada = asoc.entrada
        texto = ""
        if entrada:
            variante = next((v for v in entrada.variantes if v.nombre == r.variante and v.rir), None)
            variante = variante or next((v for v in entrada.variantes if v.rir), None)
            texto = variante.rir if variante else ""
        for codigo, mensaje in revisar_rir(dip["rirs"], rir_requerido(texto), dip):
            r.agregar(ctx, codigo, "RIR", mensaje)
        exigido = rir_requerido(texto)
        if exigido and not dip["rirs"] and not dip.get("historico_rir") and \
                dip.get("estado") not in {"ACTV", "OPEN", "IN WORK"}:
            r.manuales = [m for m in r.manuales if not m.startswith("Verificar RIR")]
            r.manuales.append(f"Verificar RIR cada {exigido} en Follow-on Tasks "
                              "(Show Historical Tasks): el DIP está cerrado.")
        elif dip["rirs"] or exigido:
            r.manuales = [m for m in r.manuales if not m.startswith("Verificar RIR")]

    def _asociar(self, dip: dict) -> Asociacion:
        """Por el Fault Name; si no alcanza, por la referencia técnica cuando corresponde
        a una sola referencia del catálogo."""
        a = asociar(dip["nombre"], self.catalogo)
        if a.entrada is None:
            codigos = extraer_codigos(dip.get("referencia_tecnica"))
            id_ = self.indice_referencias.entrada_unica(codigos)
            if id_:
                return Asociacion(self.catalogo.por_id(id_), "REF_TECNICA",
                                  detalle=", ".join(codigos),
                                  candidatos=a.candidatos)
        return a

    @staticmethod
    def _comentario(r) -> str:
        partes = []
        if r.intervalo_ok:
            partes.append("T/A aperturado correctamente")
        for h in r.hallazgos:
            if h.severidad != "OBSERVACION":
                partes.append(h.mensaje)
        return " // ".join(partes)

    @staticmethod
    def _fila(dip: dict, asoc: Asociacion | None, r, hallazgos: list[Hallazgo],
              manuales: list[str], estado: str, comentario: str, fecha) -> dict:
        entrada: EntradaCatalogo | None = asoc.entrada if asoc else None
        orden = {"CRITICA": 0, "NO CRITICA": 1, "REVISAR": 2, "OBSERVACION": 3}
        hallazgos = sorted(hallazgos, key=lambda h: orden[h.severidad])
        en_alcance = estado != FUERA_DE_ALCANCE
        # Apertura: DIP abierto. Cierre: DIP COMPLETE (se informan también los de apertura).
        cierre = en_alcance and dip["estado"] == "COMPLETE"
        de_cierre = [h for h in hallazgos if etapa(h.codigo) == "CIERRE"]
        de_apertura = [h for h in hallazgos if etapa(h.codigo) == "APERTURA"]
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
            "ESTADO APERTURA": estado_final(de_apertura) if en_alcance else "",
            "ESTADO CIERRE": estado_final(de_cierre) if cierre else "",
            "HALLAZGOS": "\n".join(
                f"[{MOSTRAR_SEVERIDAD[h.severidad]}]{' [CIERRE]' if h in de_cierre else ''} {h.mensaje}"
                for h in hallazgos),
            "COMENTARIO SUGERIDO": comentario,
            "VERIFICACIÓN MANUAL": "\n".join(f"- {m}" for m in manuales),
            "REFERENCIA ASOCIADA": entrada.nombre if entrada else "",
            "ASOCIACIÓN": (f"{asoc.metodo} ({asoc.confianza})" if asoc else ""),
            "TA SEGÚN REFERENCIA": "\n".join(
                f"{x.descripcion}: {x.ta}" + (f" / RIR {x.rir}" if x.rir else "")
                for x in entrada.referencias) if entrada else "",
            "REFERENCIA TÉCNICA ESPERADA": entrada.referencias_tecnicas if entrada else "",
            "REFERENCIA TÉCNICA DEL DIP": dip.get("referencia_encontrada") or "",
            "RIR EN ICAM": ("" if dip.get("rirs") is None
                            else "; ".join(map(str, dip["rirs"])) or "Sin RIR"),
            "ADJUNTOS EN ICAM": ("" if dip.get("adjuntos") is None
                                 else f"{len(dip['adjuntos'])}: " + ", ".join(dip["adjuntos"])
                                 if dip["adjuntos"] else "0"),
        }
