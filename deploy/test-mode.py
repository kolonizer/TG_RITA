"""Control admin test mode and reporting without displaying secrets."""
import argparse
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('on', 'off', 'status', 'reset-stats'))
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('Run as root')
    values = dict(line.split('=', 1) for line in Path('/etc/rita-bot/.env').read_text().splitlines() if '=' in line and not line.startswith('#'))
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from bot_settings import get_test_mode, set_test_mode
    from bot_stats import get_stats, reset_stats, format_stats

    connection = sqlite3.connect('file:' + values.get('DB_PATH', '/var/lib/rita-bot/bot.sqlite3') + '?mode=rw', uri=True)
    try:
        if args.mode in {'on', 'off'}:
            set_test_mode(connection, args.mode == 'on')
        elif args.mode == 'reset-stats':
            reset_stats(connection, time.time())
            print('New statistics period started; users and timers retained.')
        print('TEST_MODE=' + str(get_test_mode(connection)).lower())
        if args.mode in {'status', 'reset-stats'}:
            print(format_stats(get_stats(connection)).replace('<b>', '').replace('</b>', ''))
    finally:
        connection.close()
    if args.mode in {'on', 'off'}:
        subprocess.run(['systemctl', 'restart', 'rita-bot.service'], check=True)
        print('Service restarted. Admin timers only.')
    else:
        subprocess.run(['systemctl', 'show', 'rita-bot.service', '-p', 'ActiveState', '-p', 'SubState', '-p', 'NRestarts'], check=True)


if __name__ == "__main__":
    main()
