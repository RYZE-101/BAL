#!/usr/bin/env bash
# Einmalige Einrichtung des BAL-Servers (als root ausführen).
# Setzt Nginx (Reverse Proxy, HTTP), systemd-Service für Gunicorn und eine .env.
set -euo pipefail

APP_DIR="/opt/bal"
DJANGO_USER="www-data"
SERVICE_FILE="/etc/systemd/system/bal.service"
NGINX_CONF="/etc/nginx/sites-available/bal"

echo "==> Grundpakete installieren"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq nginx python3-venv python3-pip

echo "==> App-Verzeichnis anlegen"
mkdir -p "$APP_DIR"
chown "$DJANGO_USER":"$DJANGO_USER" "$APP_DIR"

echo "==> .env erzeugen (falls nicht vorhanden)"
if [ ! -f "$APP_DIR/.env" ]; then
    SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")
    cat > "$APP_DIR/.env" <<EOF
DJANGO_SECRET_KEY=$SECRET
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=212.227.39.26,localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=http://212.227.39.26
EOF
    echo "   .env erzeugt."
else
    echo "   .env existiert bereits – unverändert."
fi

echo "==> systemd-Service schreiben"
cat > "$SERVICE_FILE" <<'EOF'
[Unit]
Description=Gunicorn for BAL
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/opt/bal
RuntimeDirectory=bal
EnvironmentFile=/opt/bal/.env
ExecStart=/opt/bal/.venv/bin/gunicorn --workers 3 --bind unix:/run/bal/bal.sock bal.wsgi:application
Restart=always

[Install]
WantedBy=multi-user.target
EOF

echo "==> Nginx-Konfiguration schreiben (HTTP, SSL-Block kommentiert)"
cat > "$NGINX_CONF" <<'EOF'
server {
    listen 80;
    server_name _;

    client_max_body_size 10M;

    location /static/ {
        alias /opt/bal/staticfiles/;
    }

    location /media/ {
        alias /opt/bal/media/;
    }

    location / {
        include proxy_params;
        proxy_pass http://unix:/run/bal/bal.sock;
    }

    # ---------------------------------------------------------------------
    # SSL-Nachrüstung (sobald eine (Sub-)Domain auf diese IP zeigt):
    #   sudo certbot --nginx -d deine-domain.de
    # certbot ergänzt diesen Block automatisch (listen 443 ssl + Redirect).
    # ---------------------------------------------------------------------
}
EOF
ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/bal

echo "==> systemd aktivieren + starten"
systemctl daemon-reload
systemctl enable bal

echo "==> Eigentümer korrigieren (Gunicorn-Socket kommt nach /run/bal)"
chown -R root:root "$APP_DIR"
chown "$DJANGO_USER":"$DJANGO_USER" "$APP_DIR/media" "$APP_DIR/staticfiles" 2>/dev/null || true
# SQLite braucht Schreibzugriff auf das Verzeichnis (Journal/WAL-Dateien):
chown root:www-data "$APP_DIR"
chmod 2775 "$APP_DIR"

echo "==> Nginx-Konfig testen + aktivieren"
nginx -t
rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true
systemctl enable nginx

echo "Fertig. Danach Deploy ausführen (deploy.sh), dann: systemctl start bal && systemctl reload nginx"
