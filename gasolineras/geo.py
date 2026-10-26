"""Geometria y rutas. Nada aqui necesita una dependencia externa."""
from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request

KM_POR_GRADO = 111.32
OSRM = "https://router.project-osrm.org/route/v1/driving"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
UA = "gasolineras-bot/1.0 (uso personal; +https://github.com/tonguillo1/gasolineras)"

Punto = tuple[float, float]  # (lat, lon)


class RutaError(RuntimeError):
    pass


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _get(url: str, timeout: int = 60) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def geocodificar(texto: str) -> Punto:
    """Nombre de lugar -> (lat, lon) via Nominatim, limitado a Espana.

    Nominatim pide un User-Agent identificable y max 1 req/s: no llamar en bucle.
    """
    q = urllib.parse.urlencode(
        {"q": texto, "format": "json", "limit": 1, "countrycodes": "es", "addressdetails": 0}
    )
    try:
        res = _get(f"{NOMINATIM}?{q}", timeout=30)
    except Exception as exc:
        raise RutaError(f"no se pudo geocodificar {texto!r}: {exc}") from exc
    if not res:
        raise RutaError(f"no encuentro ningun sitio llamado {texto!r} en Espana")
    return float(res[0]["lat"]), float(res[0]["lon"])


def ruta(origen: Punto, destino: Punto) -> tuple[list[Punto], float]:
    """Polilinea (lat, lon) y km totales.

    Usa el servidor de demostracion publico de OSRM, que no tiene SLA ni
    garantia de disponibilidad. Para uso intensivo, levantar OSRM propio.
    """
    url = f"{OSRM}/{origen[1]},{origen[0]};{destino[1]},{destino[0]}?overview=full&geometries=geojson"
    try:
        d = _get(url)
    except Exception as exc:
        raise RutaError(f"el servicio de rutas no responde: {exc}") from exc
    if d.get("code") != "Ok" or not d.get("routes"):
        raise RutaError(f"no hay ruta por carretera entre esos puntos (OSRM: {d.get('code')})")
    r0 = d["routes"][0]
    return [(lat, lon) for lon, lat in r0["geometry"]["coordinates"]], r0["distance"] / 1000.0


def submuestrear(pts: list[Punto], paso_km: float = 1.0) -> list[Punto]:
    """Un vertice cada ~paso_km. Introduce hasta paso_km/2 de error al recortar
    curvas cerradas, despreciable frente a desvios medidos en kilometros."""
    if not pts:
        return []
    out = [pts[0]]
    acc = 0.0
    for a, b in zip(pts, pts[1:]):
        acc += haversine(*a, *b)
        if acc >= paso_km:
            out.append(b)
            acc = 0.0
    if out[-1] != pts[-1]:
        out.append(pts[-1])
    return out


def dist_a_segmento(p: Punto, a: Punto, b: Punto) -> float:
    """Km de p al segmento ab, en proyeccion plana local (valida a esta escala)."""
    cos_lat = math.cos(math.radians(p[0]))
    ax, ay = a[1] * cos_lat * KM_POR_GRADO, a[0] * KM_POR_GRADO
    bx, by = b[1] * cos_lat * KM_POR_GRADO, b[0] * KM_POR_GRADO
    px, py = p[1] * cos_lat * KM_POR_GRADO, p[0] * KM_POR_GRADO
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))
