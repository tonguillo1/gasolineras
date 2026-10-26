"""Descarga y normalizacion de los datos abiertos de carburantes (MITECO).

API publica, sin clave, actualizada cada 30 min. Documentacion informal:
https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/PreciosCarburantes/Help

Verificado el 26/10/2026 contra el servicio real. Rarezas que obligan a esto:
  - El endpoint lleva barra: /EstacionesTerrestres/FiltroProvincia/08
    (sin ella responde 404 con un HTML de error, no JSON).
  - Las respuestas traen BOM UTF-8: hay que decodificar con utf-8-sig.
  - Decimal con coma, y campo vacio = producto no servido en esa estacion.
  - /Listados/Provincias/ devuelve la clave 'IDPovincia' (typo en origen),
    mientras que dentro de la estacion el campo si es 'IDProvincia'.
  - Los nombres de /Listados/ProductosPetroliferos NO coinciden con las claves
    de precio de la estacion ('Gasoleo A habitual' vs 'Precio Gasoleo A'),
    asi que el mapeo de abajo es manual a proposito.
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .horarios import Horario, ahora, parse as parse_horario

BASE = "https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/PreciosCarburantes"
UA = "gasolineras-bot/1.0 (uso personal; +https://github.com/tonguillo1/gasolineras)"
CACHE_DIR = Path(os.environ.get("GASOLINERAS_CACHE", Path.home() / ".cache" / "gasolineras"))
CACHE_TTL = int(os.environ.get("GASOLINERAS_TTL", 1800))  # la fuente no cambia mas rapido

PRODUCTOS: dict[str, tuple[str, str]] = {
    "g95": ("Precio Gasolina 95 E5", "Gasolina 95"),
    "g98": ("Precio Gasolina 98 E5", "Gasolina 98"),
    "goa": ("Precio Gasoleo A", "Gasoleo A"),
    "goa+": ("Precio Gasoleo Premium", "Gasoleo Premium"),
    "glp": ("Precio Gases licuados del petróleo", "GLP"),
    "gnc": ("Precio Gas Natural Comprimido", "GNC"),
    "adblue": ("Precio Adblue", "AdBlue"),
}


class FuenteError(RuntimeError):
    pass


def _fetch(path: str) -> dict | list:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    destino = CACHE_DIR / (urllib.parse.quote(path, safe="") + ".json")
    fresca = destino.exists() and time.time() - destino.stat().st_mtime < CACHE_TTL
    if not fresca:
        req = urllib.request.Request(BASE + path, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                crudo = r.read()
        except Exception as exc:
            if destino.exists():
                crudo = destino.read_bytes()  # mejor datos viejos que ningun dato
            else:
                raise FuenteError(f"no se pudo consultar {path}: {exc}") from exc
        else:
            destino.write_bytes(crudo)
    else:
        crudo = destino.read_bytes()
    return json.loads(crudo.decode("utf-8-sig"))


def _num(v: str | None) -> float | None:
    if not v or not v.strip():
        return None
    try:
        return float(v.replace(",", "."))
    except ValueError:
        return None


@dataclass(frozen=True)
class Estacion:
    id: str
    rotulo: str
    direccion: str
    municipio: str
    provincia: str
    lat: float
    lon: float
    horario: Horario
    precios: dict[str, float]

    def precio(self, producto: str) -> float | None:
        return self.precios.get(producto)

    def abierta(self, cuando: datetime | None = None) -> bool | None:
        """True / False / None cuando el horario declarado no es de fiar."""
        return self.horario.abierta(cuando or ahora())

    @property
    def maps_url(self) -> str:
        return f"https://www.google.com/maps/search/?api=1&query={self.lat},{self.lon}"


def _parse_estacion(e: dict) -> Estacion | None:
    lat, lon = _num(e.get("Latitud")), _num(e.get("Longitud (WGS84)"))
    if lat is None or lon is None:
        return None  # sin coordenadas no sirve para buscar por cercania
    precios = {}
    for alias, (campo, _) in PRODUCTOS.items():
        p = _num(e.get(campo))
        if p is not None:
            precios[alias] = p
    if not precios:
        return None
    return Estacion(
        id=e.get("IDEESS", ""),
        rotulo=(e.get("Rótulo") or "").strip(),
        direccion=(e.get("Dirección") or "").strip(),
        municipio=(e.get("Municipio") or "").strip(),
        provincia=(e.get("Provincia") or "").strip(),
        lat=lat,
        lon=lon,
        horario=parse_horario(e.get("Horario", "")),
        precios=precios,
    )


def cargar(provincia: str | None = None) -> tuple[list[Estacion], str]:
    """(estaciones, fecha declarada por la fuente).

    Sin provincia descarga el fichero nacional (~12 MB, ~11.400 estaciones),
    necesario para consultas de trayecto que cruzan varias provincias.
    """
    path = f"/EstacionesTerrestres/FiltroProvincia/{provincia}" if provincia else "/EstacionesTerrestres/"
    d = _fetch(path)
    if not isinstance(d, dict) or d.get("ResultadoConsulta") != "OK":
        raise FuenteError(f"respuesta inesperada de la fuente: {str(d)[:200]}")
    estaciones = [x for x in (_parse_estacion(e) for e in d.get("ListaEESSPrecio", [])) if x]
    if not estaciones:
        raise FuenteError("la fuente respondio OK pero sin estaciones utilizables")
    return estaciones, d.get("Fecha", "")


def provincias() -> dict[str, str]:
    """{nombre en mayusculas: id}. Ojo a 'IDPovincia', el typo es de la API."""
    return {p["Provincia"].strip().upper(): p["IDPovincia"] for p in _fetch("/Listados/Provincias/")}
