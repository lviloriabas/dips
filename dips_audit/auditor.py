"""Orquesta la auditoría: carga, asociación, reglas, duplicados y resultado."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

from .asociacion import Asociacion, ParametrosAsociacion, asociar, similares_en_tabla
from .cargador import Lote, cargar_export, completar_con_icam
from .llm import ClienteOllama
from .referencia_tecnica import IndiceReferencias, buscar_referencia, extraer_codigos, revisar
from .referencias import Catalogo, EntradaCatalogo, cargar_catalogo, cargar_referencias
from .reglas import (Contexto, Hallazgo, auditar_dip, buscar_duplicados, buscar_sn_repetidos,
                     estado_final)

RAIZ = Path(__file__).resolve().parent.parent
FUERA_DE_ALCANCE = "FUERA DE ALCANCE"
# Resultado para el auditor: tres categorías (el estado detallado queda en ESTADO IA).
RESULTADOS = {"DISCREPANCIA CRÍTICA": "DISCREPANCIA", "DISCREPANCIA NO CRÍTICA": "DISCREPANCIA",
              "REVISAR": "POSIBLE DISCREPANCIA", "OK": "OK", FUERA_DE_ALCANCE: FUERA_DE_ALCANCE}


def cargar_configuracion(ruta: Path | None = None) -> dict:
    ruta = Path(ruta) if ruta else RAIZ / "config" / "config.yaml"
    config = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    for clave in ("referencias", "catalogo", "carpeta_salida"):
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
    consultas_llm: int = 0
    asociaciones: list[Asociacion | None] = field(default_factory=list)  # una por DIP

    def conteo_estados(self) -> dict[str, int]:
        return self.filas["ESTADO IA"].value_counts().to_dict()


class Auditor:
    def __init__(self, config: dict, llm: ClienteOllama | None = None,
                 fecha_auditoria: date | None = None):
        self.config = config
        self.llm = llm
        self.fecha_auditoria = fecha_auditoria or date.today()
        referencias = cargar_referencias(config["referencias"], config.get("hoja_referencias",
                                                                             "References"))
        self.catalogo: Catalogo = cargar_catalogo(config["catalogo"], referencias)
        self.indice_referencias = IndiceReferencias.desde_catalogo(self.catalogo)
        self.tipos = {t.upper() for t in config.get("tipos_auditados", ["Others"])}
        self.parametros = ParametrosAsociacion.desde_config(config.get("llm", {}))
        tol = config.get("tolerancias", {})
        self._ctx_base = dict(
            severidades=config.get("severidades", {}),
            tol_dias=tol.get("dias", 1), meses_min=tol.get("meses_min", 30),
            meses_max=tol.get("meses_max", 31))

    def contexto(self, fecha: date | None = None) -> Contexto:
        return Contexto(fecha_referencia=fecha or self.fecha_auditoria, **self._ctx_base)

    def auditar_archivo(self, ruta: Path, hoja: str | None = None,
                        icam: Path | None = None) -> ResultadoAuditoria:
        """`icam`: archivo con datos extraídos de ICAM (referencia técnica), por barcode."""
        lote = cargar_export(ruta, hoja)
        if icam:
            completar_con_icam(lote, icam)
        return self.auditar_lote(lote)

    def auditar_lote(self, lote: Lote, fechas_referencia: list[date] | None = None,
                     progreso: Callable[[int], None] | None = None) -> ResultadoAuditoria:
        """`progreso(i)` se llama después de asociar el DIP i (lo lento es el modelo local)."""
        inicio = time.perf_counter()
        consultas_previas = self.llm.consultas if self.llm else 0
        dips = lote.datos.to_dict("records")
        en_alcance = [not d["tipo"] or d["tipo"].upper() in self.tipos for d in dips]

        asociaciones: list[Asociacion | None] = []
        for i, (dip, alcance) in enumerate(zip(dips, en_alcance)):
            asociaciones.append(self._asociar(dip) if alcance else None)
            if progreso:
                progreso(i)
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
                filas.append(self._fila(dip, None, None, [], [], FUERA_DE_ALCANCE, ""))
                continue
            fecha = fechas_referencia[i] if fechas_referencia else None
            ctx = self.contexto(fecha)
            r = auditar_dip(dip, asoc.entrada, ctx)
            self._referencia_tecnica(dip, asoc, ctx, r)
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
            if asoc.metodo == "IA":
                r.hallazgos.append(Hallazgo(
                    "asociacion_ia", "Reference Match", "REVISAR",
                    f"Referencia sugerida por el modelo local: {asoc.entrada.nombre}. Confirmar."
                    + (f" ({asoc.detalle})" if asoc.detalle else "")))
            elif asoc.entrada is None:
                if asoc.metodo == "AMBIGUA":
                    motivo = f"coincide con varias referencias ({', '.join(asoc.candidatos[:3])})"
                else:
                    motivo = "no se encontró en el catálogo de referencias Others"
                similares = similares_en_tabla(dip["nombre"], self.catalogo)
                pista = "; ".join(f"'{f.descripcion}' ({f.tipo}, fila {f.fila})"
                                  for f, _ in similares)
                r.hallazgos.append(Hallazgo(
                    "sin_referencia", "Missing Reference in Table", "REVISAR",
                    f"El DIP {motivo}. Revisar manualmente."
                    + (f" Parecido en la tabla: {pista}." if pista else "")
                    + (f" IA: {asoc.detalle}" if asoc.detalle else "")))
                otros_tipos = {f.tipo for f, p in similares if p >= 90} - self.tipos
                if otros_tipos and dip["tipo"]:
                    r.hallazgos.append(Hallazgo(
                        "tipo_dip_distinto_a_referencia", "Incorrect DIP Type", "OBSERVACION",
                        f"Abierto como {dip['tipo']}, pero se parece a una referencia "
                        f"{'/'.join(sorted(otros_tipos))}."))
            severidades = self._ctx_base["severidades"]
            if i in duplicados:
                otro_barcode, otro_nombre = duplicados[i]
                r.hallazgos.append(Hallazgo(
                    "duplicado", "Duplicated DIP", severidades.get("duplicado", "NO CRITICA"),
                    f"Posible DIP duplicado de {otro_barcode} ('{otro_nombre}'): mismo avión, "
                    f"mismo componente y abiertos al mismo tiempo."))
            elif i in sn_repetidos:
                r.hallazgos.append(Hallazgo(
                    "sn_repetido", "Incorrect S/N", severidades.get("sn_repetido", "NO CRITICA"),
                    f"El mismo S/N aparece en otro DIP activo del avión: "
                    f"{', '.join(sn_repetidos[i])}."))
            estado = estado_final(r.hallazgos)
            comentario = self._comentario(r)
            filas.append(self._fila(dip, asoc, r, r.hallazgos, r.manuales, estado, comentario))
            for h in r.hallazgos:
                hallazgos.append({
                    "Fila Excel": dip["fila"], "Fault Barcode": dip["barcode"],
                    "Aircraft": dip["avion"], "Fault Name": dip["nombre"],
                    "Severidad": h.severidad, "Tipo de discrepancia": h.categoria,
                    "Código": h.codigo, "Detalle": h.mensaje,
                })

        resultado = ResultadoAuditoria(
            lote=lote, filas=pd.DataFrame(filas),
            hallazgos=pd.DataFrame(hallazgos, columns=[
                "Fila Excel", "Fault Barcode", "Aircraft", "Fault Name", "Severidad",
                "Tipo de discrepancia", "Código", "Detalle"]),
            advertencias=list(lote.notas),
            segundos=time.perf_counter() - inicio,
            consultas_llm=(self.llm.consultas - consultas_previas) if self.llm else 0,
            asociaciones=asociaciones,
        )
        return resultado

    def _referencia_tecnica(self, dip: dict, asoc: Asociacion, ctx, r) -> None:
        """El DIP debe citar la referencia del manual con su revisión y la fecha de la
        revisión (en la descripción o en cualquier otro campo), y debe ser la de la tabla."""
        if not dip.get("datos_referencia"):
            return  # no hay descripción ni referencias: no se puede revisar
        encontrada = buscar_referencia(dip.get("descripcion"), dip.get("referencia_tecnica"),
                                       dip.get("notas_diferimiento"), dip.get("nombre"))
        dip["referencia_encontrada"] = str(encontrada)
        esperada = (self.indice_referencias.por_entrada.get(asoc.entrada.id)
                    if asoc.entrada else None)
        corresponde = f" Corresponde {', '.join(sorted(esperada))}." if esperada else ""
        if not encontrada.manual:
            r.agregar(ctx, "sin_referencia_tecnica", "Missing Technical Reference",
                      "Sin referencia técnica (manual, REV y fecha)." + corresponde)
        elif encontrada.faltantes:
            r.agregar(ctx, "referencia_tecnica_incompleta", "Missing Technical Reference",
                      f"Referencia técnica incompleta ({encontrada}): falta "
                      f"{' y '.join(encontrada.faltantes)}.")
        if asoc.entrada and encontrada.manual:
            texto = "; ".join(x for x in (dip.get("referencia_tecnica"), dip.get("descripcion"))
                              if x)
            revision = revisar(texto, asoc.entrada, self.catalogo, self.indice_referencias)
            if revision and revision.codigo and revision.codigo != "sin_referencia_tecnica":
                r.agregar(ctx, revision.codigo, "Incorrect Technical Reference",
                          revision.mensaje)

    def _asociar(self, dip: dict) -> Asociacion:
        """Por el Fault Name (reglas y, si hay, modelo local); si no alcanza, por la
        referencia técnica cuando corresponde a una sola referencia del catálogo."""
        a = asociar(dip["nombre"], self.catalogo, self.llm, dip["intervalo"], dip["unidad"],
                    self.parametros)
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
            if h.severidad in ("CRITICA", "NO CRITICA"):
                partes.append(h.mensaje)
        return " // ".join(partes)

    @staticmethod
    def _fila(dip: dict, asoc: Asociacion | None, r, hallazgos: list[Hallazgo],
              manuales: list[str], estado: str, comentario: str) -> dict:
        entrada: EntradaCatalogo | None = asoc.entrada if asoc else None
        orden = {"CRITICA": 0, "NO CRITICA": 1, "REVISAR": 2, "OBSERVACION": 3}
        hallazgos = sorted(hallazgos, key=lambda h: orden[h.severidad])
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
            "HALLAZGOS": "\n".join(f"[{h.severidad}] {h.mensaje}" for h in hallazgos),
            "TIPO DE DISCREPANCIA": ", ".join(dict.fromkeys(
                h.categoria for h in hallazgos if h.severidad in ("CRITICA", "NO CRITICA"))),
            "COMENTARIO SUGERIDO": comentario,
            "VERIFICACIÓN MANUAL": "\n".join(f"- {m}" for m in manuales),
            "REFERENCIA ASOCIADA": entrada.nombre if entrada else "",
            "ASOCIACIÓN": (f"{asoc.metodo} ({asoc.confianza})" if asoc else ""),
            "TA SEGÚN REFERENCIA": "\n".join(
                f"{x.descripcion}: {x.ta}" + (f" / RIR {x.rir}" if x.rir else "")
                for x in entrada.referencias) if entrada else "",
            "REFERENCIA TÉCNICA ESPERADA": entrada.referencias_tecnicas if entrada else "",
            "REFERENCIA TÉCNICA DEL DIP": dip.get("referencia_encontrada") or "",
            "ADJUNTOS EN ICAM": ("" if dip.get("adjuntos") is None
                                 else f"{len(dip['adjuntos'])}: " + ", ".join(dip["adjuntos"])
                                 if dip["adjuntos"] else "0"),
        }
