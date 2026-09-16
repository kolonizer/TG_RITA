#!/usr/bin/env bash
set -euo pipefail
if [[ "$EUID" -ne 0 ]]; then
    echo 'Run this script as root.' >&2
    exit 1
fi
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends python3-venv git ca-certificates
if ! id rita-bot >/dev/null 2>&1; then
    useradd --system --user-group --home-dir /opt/rita-bot --shell /usr/sbin/nologin rita-bot
fi
install -d -o rita-bot -g rita-bot -m 0750 /opt/rita-bot /opt/rita-bot/releases /var/lib/rita-bot
install -d -o root -g root -m 0700 /etc/rita-bot /var/backups/rita-bot
if [[ ! -e /etc/rita-bot/.env ]]; then
    install -o root -g root -m 0600 /dev/null /etc/rita-bot/.env
    printf 'BOT_TOKEN=\nDB_PATH=/var/lib/rita-bot/bot.sqlite3\n' > /etc/rita-bot/.env
fi
chmod 0600 /etc/rita-bot/.env
chown root:root /etc/rita-bot/.env
# The repository is transferred separately, without secrets or database files.
test -d /opt/rita-bot/repo/.git
install -o root -g root -m 0644 /opt/rita-bot/repo/deploy/rita-bot.service /etc/systemd/system/rita-bot.service
systemctl daemon-reload
# Enable boot startup only at the final activation, once BOT_TOKEN and migration are ready.
echo 'Provisioned. Service has not been started.'
