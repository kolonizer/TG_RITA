"""Toggle accelerated admin timers without displaying secrets."""
import argparse
import os
import subprocess
import sqlite3
import sys
import time
import tempfile
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('mode', choices=('on', 'off', 'status', 'reset-stats'))
args = parser.parse_args()
if os.geteuid() != 0:
    raise SystemExit('Run as root')
path = Path('/etc/rita-bot/.env')
if args.mode in {'status', 'reset-stats'}:
    values = dict(line.split('=', 1) for line in path.read_text().splitlines() if '=' in line and not line.startswith('#'))
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from bot_stats import get_stats, reset_stats, format_stats
    db_path = values.get('DB_PATH', '/var/lib/rita-bot/bot.sqlite3')
    connection = sqlite3.connect('file:' + db_path + '?mode=rw', uri=True)
    try:
        if args.mode == 'reset-stats':
            reset_stats(connection, time.time())
            print('New statistics period started; users and timers retained.')
        print(format_stats(get_stats(connection)).replace('<b>', '').replace('</b>', ''))
    finally:
        connection.close()
    print('TEST_MODE=' + values.get('TEST_MODE', 'false'))
    subprocess.run(['systemctl', 'show', 'rita-bot.service', '-p', 'ActiveState', '-p', 'SubState', '-p', 'NRestarts'], check=True)
    raise SystemExit(0)
lines = [line for line in path.read_text().splitlines() if not line.startswith('TEST_MODE=')]
enabled = args.mode == 'on'
lines.append('TEST_MODE=' + str(enabled).lower())
with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.env-', delete=False) as output:
    output.write('\n'.join(lines) + '\n')
    temporary_path = Path(output.name)
temporary_path.chmod(0o600)
os.replace(temporary_path, path)
subprocess.run(['systemctl', 'restart', 'rita-bot.service'], check=True)
print('TEST_MODE=' + str(enabled).lower() + '; service restarted. Admin timers only.')
