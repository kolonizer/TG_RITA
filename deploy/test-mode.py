"""Toggle accelerated admin timers without displaying secrets."""
import argparse
import os
import subprocess
import tempfile
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('mode', choices=('on', 'off'))
args = parser.parse_args()
if os.geteuid() != 0:
    raise SystemExit('Run as root')
path = Path('/etc/rita-bot/.env')
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
