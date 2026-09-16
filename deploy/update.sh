#!/usr/bin/env bash
set -euo pipefail
umask 077
if [[ "$EUID" -ne 0 || "$#" -ne 1 || ! "$1" =~ ^[0-9a-f]{40}$ ]]; then
    echo 'Usage: sudo bash deploy/update.sh <full-tested-commit-SHA>' >&2
    exit 1
fi
# Serialise updates and refuse an unreviewed branch tip.
exec 9>/var/lib/rita-bot/deploy.lock
flock -n 9
revision="$1"
repo=/opt/rita-bot/repo
release="/opt/rita-bot/releases/$revision"
sudo -u rita-bot git -C "$repo" fetch origin
sudo -u rita-bot git -C "$repo" cat-file -e "$revision^{commit}"
if [[ ! -d "$release" ]]; then
    install -d -o rita-bot -g rita-bot -m 0750 "$release"
    sudo -u rita-bot git -C "$repo" archive "$revision" | sudo -u rita-bot tar -x -C "$release"
fi
sudo -u rita-bot python3 -m venv "$release/.venv"
sudo -u rita-bot "$release/.venv/bin/python" -m pip install -r "$release/requirements.txt"
(
    cd "$release"
    sudo -u rita-bot "$release/.venv/bin/python" -W error::ResourceWarning -m unittest discover -s tests -v
    sudo -u rita-bot "$release/.venv/bin/python" -m compileall -q bot.py bot_stats.py bot_settings.py bot_receipts.py tests deploy
)
old_release=''
if [[ -L /opt/rita-bot/current ]]; then
    old_release="$(readlink -f /opt/rita-bot/current)"
fi
systemctl stop rita-bot.service
# Preserve users and queue with a consistent SQLite backup; never delete the DB.
if [[ -f /var/lib/rita-bot/bot.sqlite3 ]]; then
    python3 - <<'PY'
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ.sqlite3')
path = Path('/var/backups/rita-bot') / name
with closing(sqlite3.connect('file:/var/lib/rita-bot/bot.sqlite3?mode=ro', uri=True)) as source, closing(sqlite3.connect(path)) as target:
    source.backup(target)
path.chmod(0o600)
PY
fi
ln -s "$release" /opt/rita-bot/current.next
mv -Tf /opt/rita-bot/current.next /opt/rita-bot/current
systemctl start rita-bot.service
sleep 10
if ! systemctl is-active --quiet rita-bot.service ||
   [[ "$(systemctl show -p NRestarts --value rita-bot.service)" != '0' ]]; then
    systemctl stop rita-bot.service
    if [[ -n "$old_release" ]]; then
        ln -s "$old_release" /opt/rita-bot/current.next
        mv -Tf /opt/rita-bot/current.next /opt/rita-bot/current
        systemctl start rita-bot.service
    fi
    echo 'New release failed; previous code restored when available. Database retained.' >&2
    exit 1
fi
systemctl enable rita-bot.service
systemctl status rita-bot.service --no-pager
journalctl -u rita-bot.service -n 30 --no-pager
