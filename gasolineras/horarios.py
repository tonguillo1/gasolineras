"""Parseo del campo 'Horario' de los datos del MITECO.

El formato no esta documentado. Lo que sigue se deriva de inspeccionar los
11.380 registros nacionales (26/10/2026): 1.165 cadenas distintas.

Gramatica observada:
    horario   := tramo (';' tramo)*
    tramo     := etiqueta ':' horas
    etiqueta  := dia | dia '-' dia            # L M X J V S D (X = miercoles)
    horas     := '24H' | franja (' y ' franja)*
    franja    := H[H]:MM '-' H[H]:MM

Particularidades reales:
  - '24H' en 5.162 de 11.380 registros.
  - Franjas partidas con ' y ': '09:00-14:00 y 16:00-19:00'.
  - Hora sin cero inicial: '7:00-22:00'.
  - Fin '00:00' significa medianoche del dia siguiente, no franja nula.
  - 14 franjas cruzan medianoche ('06:00-02:00').
  - 477 estaciones declaran un unico dia ('L: 06:00-22:00'), repartidas por
    50 de las 52 provincias. Que abran solo los lunes es inverosimil: es
    ruido de declaracion en origen. No se pueden corregir, pero tampoco
    tratar como cerradas, asi que se marcan no fiables.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

DIAS = "LMXJVSD"  # indice 0..6, igual que datetime.weekday()

# Los horarios del padron son hora local espanola. Un servidor en UTC (lo
# normal en un LXC recien creado) desplazaria el filtro una o dos horas, asi
# que nunca se usa datetime.now() a secas. Canarias queda fuera: alli el
# desfase es de una hora mas y habria que resolverlo por provincia.
TZ_PENINSULA = ZoneInfo("Europe/Madrid")


def ahora() -> datetime:
    """Hora local peninsular, sea cual sea la zona del servidor."""
    return datetime.now(TZ_PENINSULA)
_FRANJA = re.compile(r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$")
_VEINTICUATRO = re.compile(r"^24\s*H(ORAS)?$")
_DIA_ENTERO = (0, 1440)


def _dias_de(etiqueta: str) -> list[int]:
    e = etiqueta.strip().upper()
    if "-" in e:
        a, _, b = e.partition("-")
        a, b = a.strip(), b.strip()
        if a in DIAS and b in DIAS:
            i, j = DIAS.index(a), DIAS.index(b)
            # Un rango invertido ('D-L') envuelve el fin de semana.
            return list(range(i, j + 1)) if i <= j else [*range(i, 7), *range(0, j + 1)]
        return []
    return [DIAS.index(e)] if e in DIAS else []


def _franjas_de(texto: str) -> list[tuple[int, int]]:
    t = texto.strip().upper()
    if _VEINTICUATRO.match(t):
        return [_DIA_ENTERO]
    out = []
    for parte in re.split(r"\s+Y\s+", t):
        m = _FRANJA.match(parte.strip())
        if not m:
            continue
        h1, m1, h2, m2 = (int(x) for x in m.groups())
        if not (0 <= h1 <= 24 and 0 <= h2 <= 24 and m1 < 60 and m2 < 60):
            continue
        ini, fin = h1 * 60 + m1, h2 * 60 + m2
        if fin == 0:
            fin = 1440  # '06:00-00:00' cierra a medianoche, no a las 0 del mismo dia
        if fin <= ini:
            # '06:00-02:00' cierra de madrugada; '00:00-00:00' es dia completo.
            fin += 1440
        out.append((ini, fin))
    return out


@dataclass(frozen=True)
class Horario:
    """Franjas por dia de la semana, en minutos desde medianoche."""

    tramos: dict[int, list[tuple[int, int]]] = field(default_factory=dict)
    fiable: bool = True
    crudo: str = ""

    def abierta(self, cuando: datetime) -> bool | None:
        """True/False, o None si el horario declarado no es de fiar."""
        if not self.fiable:
            return None
        mins = cuando.hour * 60 + cuando.minute
        return any(i <= mins < f for i, f in self.tramos.get(cuando.weekday(), ()))

    def es_24h(self) -> bool:
        return self.fiable and all(
            any(i <= 0 and f >= 1440 for i, f in self.tramos.get(d, ())) for d in range(7)
        )

    def descripcion(self) -> str:
        if not self.fiable:
            return f"{self.crudo} (horario dudoso en origen)"
        return "24 h" if self.es_24h() else self.crudo


def parse(crudo: str) -> Horario:
    crudo = (crudo or "").strip()
    tramos: dict[int, list[tuple[int, int]]] = {d: [] for d in range(7)}
    declarados: set[int] = set()
    reconocido = False

    for seg in crudo.split(";"):
        if ":" not in seg:
            continue
        etiqueta, _, horas = seg.partition(":")  # el primer ':' separa dia de hora
        dias = _dias_de(etiqueta)
        franjas = _franjas_de(horas)
        if dias and franjas:
            reconocido = True
        for ini, fin in franjas:
            for d in dias:
                declarados.add(d)
                if fin <= 1440:
                    tramos[d].append((ini, fin))
                else:
                    # Cruza medianoche: parte del dia y arrastre al siguiente.
                    tramos[d].append((ini, 1440))
                    tramos[(d + 1) % 7].append((0, fin - 1440))

    # Un solo dia declarado, o nada reconocible, no permite decidir.
    fiable = reconocido and len(declarados) >= 2
    return Horario(tramos=tramos, fiable=fiable, crudo=crudo)
