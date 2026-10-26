"""Busqueda de estaciones por cercania o a lo largo de un trayecto."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from . import geo
from .fuente import Estacion
from .horarios import ahora

# Cuanto se tolera que cueste el desvio. Ordenar solo por precio manda al
# usuario 12 km para ahorrar 20 centimos, asi que el ranking penaliza la
# distancia: ida y vuelta, a un consumo tipico, convertido a euros.
CONSUMO_L_100KM = 6.5


@dataclass(frozen=True)
class Resultado:
    estacion: Estacion
    precio: float
    distancia_km: float          # a la posicion del usuario, o desvio de la ruta
    km_desde_origen: float | None = None   # solo en consultas de trayecto
    abierta: bool | None = None

    @property
    def icono(self) -> str:
        return {True: "🟢", False: "🔴", None: "⚪"}[self.abierta]


@dataclass(frozen=True)
class Informe:
    resultados: list[Resultado]
    fecha_fuente: str
    producto: str
    media: float | None          # media de la zona o del corredor
    minimo: float | None
    maximo: float | None
    n_consideradas: int
    n_descartadas_cerradas: int

    def ahorro_vs_media(self, r: Resultado, litros: float = 50.0) -> float | None:
        return None if self.media is None else (self.media - r.precio) * litros


def _coste_desvio(km: float, precio: float) -> float:
    """Euros de combustible que cuesta ir y volver km kilometros."""
    return 2 * km * (CONSUMO_L_100KM / 100.0) * precio


def _informe(
    candidatos: list[Resultado], fecha: str, producto: str, descartadas: int
) -> Informe:
    precios = sorted(r.precio for r in candidatos)
    return Informe(
        resultados=candidatos,
        fecha_fuente=fecha,
        producto=producto,
        media=sum(precios) / len(precios) if precios else None,
        minimo=precios[0] if precios else None,
        maximo=precios[-1] if precios else None,
        n_consideradas=len(precios),
        n_descartadas_cerradas=descartadas,
    )


def cerca(
    estaciones: list[Estacion],
    fecha: str,
    lat: float,
    lon: float,
    producto: str,
    radio_km: float = 10.0,
    n: int = 5,
    solo_abiertas: bool = True,
    cuando: datetime | None = None,
    penalizar_desvio: bool = True,
) -> Informe:
    cuando = cuando or ahora()
    candidatos: list[Resultado] = []
    descartadas = 0
    for e in estaciones:
        precio = e.precio(producto)
        if precio is None:
            continue
        d = geo.haversine(lat, lon, e.lat, e.lon)
        if d > radio_km:
            continue
        ab = e.abierta(cuando)
        # Una estacion con horario dudoso (ab is None) se mantiene: descartarla
        # perderia el 4,3% del padron por un fallo de declaracion ajeno.
        if solo_abiertas and ab is False:
            descartadas += 1
            continue
        candidatos.append(Resultado(e, precio, d, None, ab))

    inf = _informe(candidatos, fecha, producto, descartadas)
    clave = (
        (lambda r: (r.precio + _coste_desvio(r.distancia_km, r.precio) / 50.0, r.distancia_km))
        if penalizar_desvio
        else (lambda r: (r.precio, r.distancia_km))
    )
    return Informe(
        resultados=sorted(candidatos, key=clave)[:n],
        fecha_fuente=inf.fecha_fuente,
        producto=inf.producto,
        media=inf.media,
        minimo=inf.minimo,
        maximo=inf.maximo,
        n_consideradas=inf.n_consideradas,
        n_descartadas_cerradas=inf.n_descartadas_cerradas,
    )


def trayecto(
    estaciones: list[Estacion],
    fecha: str,
    pts: list[geo.Punto],
    producto: str,
    desvio_km: float = 3.0,
    n: int = 8,
    solo_abiertas: bool = True,
    cuando: datetime | None = None,
) -> Informe:
    """Estaciones a <= desvio_km de la polilinea, ordenadas por precio.

    Aqui no se penaliza el desvio: el trayecto ya hay que hacerlo, y el coste
    marginal de 2 km es irrelevante frente a llenar el deposito.
    """
    cuando = cuando or ahora()
    via = geo.submuestrear(pts)
    if not via:
        return _informe([], fecha, producto, 0)

    import math

    grado_lat = desvio_km / geo.KM_POR_GRADO
    grado_lon = desvio_km / (geo.KM_POR_GRADO * math.cos(math.radians(via[0][0])))
    lats = [q[0] for q in via]
    lons = [q[1] for q in via]
    lo_la, hi_la = min(lats) - grado_lat, max(lats) + grado_lat
    lo_lo, hi_lo = min(lons) - grado_lon, max(lons) + grado_lon

    acum = [0.0]
    for a, b in zip(via, via[1:]):
        acum.append(acum[-1] + geo.haversine(*a, *b))

    candidatos: list[Resultado] = []
    descartadas = 0
    for e in estaciones:
        precio = e.precio(producto)
        if precio is None:
            continue
        if not (lo_la <= e.lat <= hi_la and lo_lo <= e.lon <= hi_lo):
            continue  # descarte barato antes de medir contra cada segmento
        mejor, mejor_i = float("inf"), 0
        for i, (a, b) in enumerate(zip(via, via[1:])):
            d = geo.dist_a_segmento((e.lat, e.lon), a, b)
            if d < mejor:
                mejor, mejor_i = d, i
                if d < 0.05:
                    break
        if mejor > desvio_km:
            continue
        ab = e.abierta(cuando)
        if solo_abiertas and ab is False:
            descartadas += 1
            continue
        candidatos.append(Resultado(e, precio, mejor, acum[mejor_i], ab))

    inf = _informe(candidatos, fecha, producto, descartadas)
    return Informe(
        resultados=sorted(candidatos, key=lambda r: (r.precio, r.distancia_km))[:n],
        fecha_fuente=inf.fecha_fuente,
        producto=inf.producto,
        media=inf.media,
        minimo=inf.minimo,
        maximo=inf.maximo,
        n_consideradas=inf.n_consideradas,
        n_descartadas_cerradas=inf.n_descartadas_cerradas,
    )
