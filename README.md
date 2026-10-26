# gasolineras

Bot de Telegram que dice qué gasolinera te sale más barata **en tu zona** o **a lo
largo de un trayecto**, con los datos abiertos del Ministerio para la Transición
Ecológica.

```
🟢 1.469 €/L — PLENERGY
   a 5.7 km · ahorras 14.53 € / 50 L
   CARRETERA DEL MIG KM. 36, Hospitalet de Llobregat
   24 h
```

## Por qué la API oficial y no scrapear un visor

Los mapas de prensa que circulan (Datadista y compañía) pintan estos mismos datos.
La fuente es la [API REST del MITECO](https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/PreciosCarburantes/Help):
pública, sin clave, actualizada cada 30 minutos. Da además horarios, tipo de venta,
margen de la vía e `IDEESS` estable, que los visores no exponen. Scrapear HTML
ajeno sería más frágil y daría menos.

## Uso

Manda tu **ubicación** por Telegram y devuelve las más baratas alrededor.

| Comando | Qué hace |
|---|---|
| (ubicación) | Las 5 más baratas en tu radio |
| `/ruta Barcelona a Lleida` | Las más baratas a lo largo del camino |
| `/producto goa` | `g95` `g98` `goa` `goa+` `glp` `gnc` `adblue` |
| `/radio 15` | Radio de búsqueda en km |
| `/abiertas` | Alternar si se descartan las cerradas |
| `/ajustes` | Ver la configuración actual |

El ranking por cercanía **descuenta lo que cuesta el desvío** (ida y vuelta a
6,5 L/100 km), para no mandarte 12 km a ahorrar dos céntimos. En trayecto no se
descuenta: el camino ya lo haces.

## Instalación

Despliegue en LXC con systemd: **[`deploy/README.md`](deploy/README.md)**.
No necesita puertos abiertos, ni TLS, ni cron.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export TELEGRAM_TOKEN=...          # de @BotFather
export GASOLINERAS_ALLOWED_IDS=... # tu ID de @userinfobot, recomendado
.venv/bin/python bot.py
```

## Rarezas de la fuente, por si tocas el código

Todo esto está verificado contra el servicio real (26/10/2026) y es la razón de
que `fuente.py` y `horarios.py` parezcan más complicados de lo necesario:

| Rareza | Consecuencia |
|---|---|
| El endpoint lleva barra: `/EstacionesTerrestres/FiltroProvincia/08` | Sin ella responde **404 con HTML**, no JSON |
| Las respuestas traen **BOM UTF-8** | `json.loads` falla sin `utf-8-sig` |
| Decimal con **coma**, campo vacío = producto no servido | Normalización obligatoria |
| `/Listados/Provincias/` devuelve **`IDPovincia`** (typo en origen) | Pero dentro de la estación el campo sí es `IDProvincia` |
| Los nombres de `/Listados/ProductosPetroliferos` no coinciden con las claves de precio | `Gasóleo A habitual` vs `Precio Gasoleo A`: el mapeo es manual |
| Hay estaciones sin coordenadas | Se descartan: no sirven para buscar por cercanía |

### Horarios

El campo `Horario` no está documentado. El parser se derivó inspeccionando las
1.165 cadenas distintas de los 11.380 registros nacionales:

- `L-D: 24H` en 5.162 registros. Días en castellano, **`X` es miércoles**.
- Franjas partidas con ` y `: `09:00-14:00 y 16:00-19:00`.
- Horas sin cero inicial: `7:00-22:00`.
- Fin `00:00` significa medianoche del día siguiente, no franja nula.
- 14 franjas cruzan medianoche (`06:00-02:00`) y arrastran al día siguiente.
- **477 estaciones declaran un solo día** (`L: 06:00-22:00`), repartidas por 50 de
  las 52 provincias. Que abran solo los lunes es inverosímil: es ruido de
  declaración en origen. No se pueden arreglar, pero tampoco tratarlas como
  cerradas, así que se marcan **no fiables** (⚪) y nunca se descartan.

Cobertura actual: 95,7 % de las estaciones con franjas utilizables, 4,3 % marcadas
no fiables, 0 que el parser acepte y deje sin horario.

Los horarios son **hora peninsular**, no la del servidor: un LXC en UTC desplazaría
el filtro. Por eso nunca se usa `datetime.now()` a secas, sino
`horarios.ahora()` con `ZoneInfo("Europe/Madrid")`.

## Limitaciones conocidas

- **Canarias**: el filtro de apertura usa hora peninsular. Allí va una hora
  desplazado. Habría que resolverlo por provincia.
- **`/ruta` depende del servidor público de demostración de OSRM**, que no tiene
  SLA. Si se cae, el comando falla; el resto del bot sigue funcionando. Para uso
  intensivo, levantar OSRM propio u openrouteservice con clave.
- **Sin histórico**: solo se ve la foto actual. Guardar los snapshots permitiría
  responder "¿está caro hoy?"; no está hecho.
- Los precios son los que **declara cada estación** al ministerio. Un error de
  declaración se propaga tal cual.

## Tests

```bash
python3 tests/test_horarios.py
python3 tests/test_geo.py
python3 tests/cobertura.py '~/.cache/gasolineras/*EstacionesTerrestres%2F.json'
```

`cobertura.py` no es un test unitario: pasa el parser por todos los horarios
reales descargados y cuenta cuántos no reconoce.
