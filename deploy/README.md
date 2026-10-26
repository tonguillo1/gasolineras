# Despliegue en un LXC de Proxmox

Contenedor Debian 12 sin privilegios, 512 MB de RAM y 2 GB de disco sobran.
El proceso se queda en unos 100-150 MB con el padron nacional en memoria.

```bash
# en el LXC
apt update && apt install -y python3 python3-venv git
adduser --system --group --home /opt/gasolineras gasolineras

git clone https://github.com/tonguillo1/gasolineras /opt/gasolineras
cd /opt/gasolineras
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# token y permisos
cp .env.example /etc/gasolineras.env
chmod 600 /etc/gasolineras.env
$EDITOR /etc/gasolineras.env        # TELEGRAM_TOKEN y GASOLINERAS_ALLOWED_IDS

chown -R gasolineras:gasolineras /opt/gasolineras
install -m 644 deploy/gasolineras-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now gasolineras-bot
journalctl -u gasolineras-bot -f
```

## Cosas a tener en cuenta

- **No hace falta cron.** El bot se refresca solo cada 30 min en segundo plano,
  al mismo ritmo al que publica el ministerio.
- **No necesita puertos abiertos ni TLS**: habla con Telegram por *long polling*,
  conexion saliente. No expongas nada.
- **Salida a Internet necesaria**: `sedeaplicaciones.minetur.gob.es`,
  `api.telegram.org` y, para `/ruta`, `router.project-osrm.org` y
  `nominatim.openstreetmap.org`.
- `MemoryMax=400M` corta por lo sano si algo se desmadra. Si el padron crece,
  sube el limite antes de que systemd mate el servicio.
- Este bot no es critico: no lo metas en el mismo contenedor que nada de
  produccion.
