#!/usr/bin/env python3
"""Bot de Telegram: gasolineras mas baratas por zona o por trayecto.

Arranque:
    export TELEGRAM_TOKEN=...            # el que da @BotFather
    export GASOLINERAS_ALLOWED_IDS=123   # opcional, limita quien puede usarlo
    python3 bot.py
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import sys
from pathlib import Path

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from gasolineras import consulta, fuente, geo
from gasolineras.horarios import ahora

log = logging.getLogger("gasolineras.bot")

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
PERMITIDOS = {int(x) for x in os.environ.get("GASOLINERAS_ALLOWED_IDS", "").replace(",", " ").split() if x.strip()}
PREFS = fuente.CACHE_DIR / "prefs.json"
MEM_TTL = 1800  # mismo ritmo al que publica la fuente

DEFECTOS = {"producto": "goa", "radio": 10.0, "solo_abiertas": True}

# ------------------------------------------------------------------ datos

_datos: tuple[list[fuente.Estacion], str] | None = None
_lock = asyncio.Lock()


async def _recargar() -> None:
    """Descarga y parsea el padron nacional en un hilo aparte.

    Son ~12 MB y unos 11.300 objetos: entre 5 y 20 s segun la linea. Va a un
    hilo porque urllib es bloqueante y congelaria el event loop del bot.
    """
    global _datos
    est, fecha = await asyncio.to_thread(fuente.cargar)
    async with _lock:
        _datos = (est, fecha)
    log.info("padron cargado: %d estaciones, fuente %s", len(est), fecha)


async def datos() -> tuple[list[fuente.Estacion], str]:
    """Padron en memoria. No bloquea salvo que el precalentado haya fallado."""
    async with _lock:
        if _datos is not None:
            return _datos
    await _recargar()
    async with _lock:
        if _datos is None:
            raise fuente.FuenteError("no hay datos de precios disponibles")
        return _datos


async def _refrescador() -> None:
    """Relee la fuente cada MEM_TTL sin que ninguna consulta espere por ello."""
    while True:
        await asyncio.sleep(MEM_TTL)
        try:
            await _recargar()
        except Exception:
            log.exception("fallo el refresco periodico; sigo con los datos anteriores")


async def post_init(app: Application) -> None:
    """Precalienta el padron antes de atender a nadie y arranca el refresco."""
    try:
        await _recargar()
    except Exception:
        log.exception("no se pudo precargar el padron; se intentara en la primera consulta")
    app.bot_data["refrescador"] = asyncio.create_task(_refrescador())


async def post_shutdown(app: Application) -> None:
    tarea = app.bot_data.get("refrescador")
    if tarea:
        tarea.cancel()


# ------------------------------------------------------- preferencias

def _leer_prefs() -> dict:
    try:
        return json.loads(PREFS.read_text())
    except (OSError, ValueError):
        return {}


def _prefs(uid: int) -> dict:
    return {**DEFECTOS, **_leer_prefs().get(str(uid), {})}


def _guardar_pref(uid: int, clave: str, valor) -> None:
    todo = _leer_prefs()
    todo.setdefault(str(uid), {})[clave] = valor
    PREFS.parent.mkdir(parents=True, exist_ok=True)
    tmp = PREFS.with_suffix(".tmp")
    tmp.write_text(json.dumps(todo, indent=1))
    tmp.replace(PREFS)  # escritura atomica: no deja el fichero a medias


def autorizado(update: Update) -> bool:
    return not PERMITIDOS or (update.effective_user and update.effective_user.id in PERMITIDOS)


# ---------------------------------------------------------------- formato

def _linea(inf: consulta.Informe, r: consulta.Resultado, trayecto: bool) -> str:
    e = r.estacion
    rotulo = html.escape(e.rotulo or "sin rotulo", quote=False)
    donde = html.escape(f"{e.direccion}, {e.municipio}", quote=False)
    if trayecto:
        sitio = f"km {r.km_desde_origen:.0f} · desvio {r.distancia_km:.1f} km"
    else:
        sitio = f"a {r.distancia_km:.1f} km"
    ahorro = inf.ahorro_vs_media(r)
    extra = f" · ahorras {ahorro:.2f} € / 50 L" if ahorro and ahorro > 0.5 else ""
    horario = html.escape(e.horario.descripcion(), quote=False)
    return (
        f"{r.icono} <b>{r.precio:.3f} €/L</b> — {rotulo}\n"
        f"   {sitio}{extra}\n"
        f"   <a href=\"{e.maps_url}\">{donde}</a>\n"
        f"   <i>{horario}</i>"
    )


def _cabecera(inf: consulta.Informe, titulo: str) -> str:
    nombre = fuente.PRODUCTOS[inf.producto][1]
    if inf.media is None:
        return f"<b>{titulo}</b>\nNo hay ninguna estacion con {nombre} en ese ambito."
    cerradas = f" · {inf.n_descartadas_cerradas} cerradas ahora" if inf.n_descartadas_cerradas else ""
    return (
        f"<b>{titulo}</b>\n"
        f"{nombre} · {inf.n_consideradas} estaciones{cerradas}\n"
        f"media {inf.media:.3f} · rango {inf.minimo:.3f}–{inf.maximo:.3f} €/L\n"
        f"<i>datos del ministerio: {inf.fecha_fuente}</i>"
    )


def _responder(inf: consulta.Informe, titulo: str, trayecto: bool = False) -> str:
    partes = [_cabecera(inf, titulo)]
    partes += [_linea(inf, r, trayecto) for r in inf.resultados]
    if any(r.abierta is None for r in inf.resultados):
        partes.append("⚪ = la estacion declara un horario incompleto al ministerio; no puedo confirmar que este abierta.")
    return "\n\n".join(partes)


# --------------------------------------------------------------- comandos

AYUDA = """<b>Gasolineras baratas</b>

📍 <b>Mandame tu ubicacion</b> (clip → Ubicacion) y te doy las mas baratas alrededor.

/ruta Barcelona a Lleida — las mas baratas a lo largo del trayecto
/producto goa — que carburante miro: {prods}
/radio 15 — radio de busqueda en km
/abiertas — alternar si descarto las cerradas
/ajustes — ver como lo tienes

El ranking de cercania descuenta lo que cuesta el desvio (ida y vuelta a {consumo} L/100 km), asi que no te manda 12 km por dos centimos. En trayecto no se descuenta: el camino ya lo haces.

Datos: Ministerio para la Transicion Ecologica, se refrescan cada 30 min."""


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not autorizado(update):
        return
    await update.message.reply_text(
        AYUDA.format(prods=", ".join(fuente.PRODUCTOS), consumo=consulta.CONSUMO_L_100KM),
        parse_mode=ParseMode.HTML,
    )


async def cmd_ajustes(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not autorizado(update):
        return
    p = _prefs(update.effective_user.id)
    await update.message.reply_text(
        f"Producto: {fuente.PRODUCTOS[p['producto']][1]} ({p['producto']})\n"
        f"Radio: {p['radio']:.0f} km\n"
        f"Descartar cerradas: {'si' if p['solo_abiertas'] else 'no'}\n"
        f"Hora peninsular ahora: {ahora():%H:%M}"
    )


async def cmd_producto(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not autorizado(update):
        return
    arg = (ctx.args[0].lower() if ctx.args else "")
    if arg not in fuente.PRODUCTOS:
        await update.message.reply_text("Uso: /producto " + " | ".join(fuente.PRODUCTOS))
        return
    _guardar_pref(update.effective_user.id, "producto", arg)
    await update.message.reply_text(f"Vale, busco {fuente.PRODUCTOS[arg][1]}.")


async def cmd_radio(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not autorizado(update):
        return
    try:
        km = float(ctx.args[0].replace(",", "."))
        if not 0.5 <= km <= 100:
            raise ValueError
    except (IndexError, ValueError):
        await update.message.reply_text("Uso: /radio 15   (entre 0,5 y 100 km)")
        return
    _guardar_pref(update.effective_user.id, "radio", km)
    await update.message.reply_text(f"Radio de busqueda: {km:.0f} km.")


async def cmd_abiertas(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not autorizado(update):
        return
    uid = update.effective_user.id
    nuevo = not _prefs(uid)["solo_abiertas"]
    _guardar_pref(uid, "solo_abiertas", nuevo)
    await update.message.reply_text(
        "Descarto las que estan cerradas ahora." if nuevo else "Te enseno tambien las cerradas."
    )


async def recibir_ubicacion(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not autorizado(update):
        return
    loc = update.message.location
    p = _prefs(update.effective_user.id)
    aviso = await update.message.reply_text("Mirando precios…")
    try:
        est, fecha = await datos()
        inf = await asyncio.to_thread(
            consulta.cerca, est, fecha, loc.latitude, loc.longitude,
            p["producto"], p["radio"], 5, p["solo_abiertas"],
        )
    except fuente.FuenteError as exc:
        await aviso.edit_text(f"No he podido consultar los precios: {exc}")
        return
    await aviso.edit_text(
        _responder(inf, f"Mas baratas en {p['radio']:.0f} km"),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


_SEPARADOR = re.compile(r"\s+(?:a|hasta|->|–>|→|-)\s+|\s*;\s*", re.IGNORECASE)


async def cmd_ruta(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not autorizado(update):
        return
    texto = " ".join(ctx.args).strip()
    partes = [x.strip() for x in _SEPARADOR.split(texto, maxsplit=1) if x.strip()]
    if len(partes) != 2:
        await update.message.reply_text("Uso: /ruta Barcelona a Lleida")
        return

    p = _prefs(update.effective_user.id)
    aviso = await update.message.reply_text(f"Calculando la ruta {partes[0]} → {partes[1]}…")
    try:
        origen = await asyncio.to_thread(geo.geocodificar, partes[0])
        destino = await asyncio.to_thread(geo.geocodificar, partes[1])
        pts, km = await asyncio.to_thread(geo.ruta, origen, destino)
        est, fecha = await datos()
        inf = await asyncio.to_thread(
            consulta.trayecto, est, fecha, pts, p["producto"], 3.0, 8, p["solo_abiertas"],
        )
    except (geo.RutaError, fuente.FuenteError) as exc:
        await aviso.edit_text(str(exc))
        return
    await aviso.edit_text(
        _responder(inf, f"{partes[0].title()} → {partes[1].title()} · {km:.0f} km", trayecto=True),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("fallo manejando una actualizacion", exc_info=ctx.error)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if not TOKEN:
        print("falta TELEGRAM_TOKEN en el entorno", file=sys.stderr)
        return 1
    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    app.add_handler(CommandHandler(["start", "ayuda", "help"], cmd_start))
    app.add_handler(CommandHandler("ajustes", cmd_ajustes))
    app.add_handler(CommandHandler("producto", cmd_producto))
    app.add_handler(CommandHandler("radio", cmd_radio))
    app.add_handler(CommandHandler("abiertas", cmd_abiertas))
    app.add_handler(CommandHandler("ruta", cmd_ruta))
    app.add_handler(MessageHandler(filters.LOCATION, recibir_ubicacion))
    app.add_error_handler(on_error)
    if PERMITIDOS:
        log.info("acceso limitado a %d usuario(s)", len(PERMITIDOS))
    else:
        log.warning("GASOLINERAS_ALLOWED_IDS vacio: cualquiera que encuentre el bot podra usarlo")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
