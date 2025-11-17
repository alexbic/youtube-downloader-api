#!/usr/bin/env sh
set -e

# Ensure required directories exist
mkdir -p /app/tasks /app/downloads /var/log/supervisor /var/run/supervisor

# Fix ownership for mounted volumes (ignore if not root)
if [ "$(id -u)" = "0" ]; then
  chown -R app:app /app || true
  chown -R app:app /var/log/supervisor /var/run/supervisor || true
fi

# Relax permissions to avoid issues on some host filesystems
chmod -R u+rwX,g+rwX /app || true

# Start supervisord as root; programs drop to user=app per config
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
