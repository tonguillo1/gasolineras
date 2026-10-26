# Despliegue en un LXC de Proxmox

Contenedor Debian 12 sin privilegios, 512 MB de RAM y 2 GB de disco sobran.
El proceso se queda en unos 100-150 MB con el padron nacional en memoria.

## Como llega el codigo al contenedor

El repositorio es **privado**, asi que `git clone` dentro del LXC pediria
credenciales. Para no meter un token de GitHub en el contenedor, se copia el
codigo desde una maquina que ya tenga acceso al repo:

```bash
# en la maquina que ya tiene acceso a GitHub (no en el LXC)
git clone https://github.com/tonguillo1/gasolineras /tmp/gasolineras
tar -czf /tmp/gasolineras.tar.gz -C /tmp --exclude='.git' gasolineras

# desde el host Proxmox, al contenedor <CTID>
pct push <CTID> /tmp/gasolineras.tar.gz /tmp/gasolineras.tar.gz
pct exec <CTID> -- tar -xzf /tmp/gasolineras.tar.gz -C /opt
pct exec <CTID> -- mv /opt/gasolineras /opt/gasolineras.tmp
```

Las alternativas, si prefieres actualizar con `git pull` desde dentro:

- **Deploy key de solo lectura**: genera una clave en el LXC
  (`ssh-keygen -t ed25519 -N ''`), anadela en *Settings → Deploy keys* del repo
  sin permiso de escritura, y clona por SSH. Es la opcion limpia para un
  servicio que quieras actualizar solo.
- **Hacer publico el repositorio**: no hay nada sensible en el codigo (el token
  vive en `/etc/gasolineras.env`, que esta en `.gitignore`), pero es tu decision.

## Instalacion

```bash
# en el LXC
apt update && apt install -y python3 python3-venv

adduser --system --group --home /opt/gasolineras gasolineras
# (el codigo ya esta en /opt/gasolineras por el paso anterior)
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
- El token va en `/etc/gasolineras.env` con permisos 600, nunca en el
  repositorio ni en la linea de comandos (quedaria en el historial del shell).
