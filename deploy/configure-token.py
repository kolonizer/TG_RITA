"""Run interactively as root over ssh -t; the token is never echoed."""
import getpass
import os
import re
from pathlib import Path

if os.geteuid() != 0:
    raise SystemExit("Run as root")
path = Path('/etc/rita-bot/.env')
token = getpass.getpass('Telegram BOT_TOKEN (input hidden): ')
if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+', token):
    raise SystemExit('Invalid token format; file unchanged.')
lines = path.read_text().splitlines()
lines = [line for line in lines if not line.startswith('BOT_TOKEN=')]
lines.insert(0, 'BOT_TOKEN=' + token)
# Root-only parent directory and mode 600; no secret in arguments or output.
fd = os.open(path, os.O_WRONLY | os.O_TRUNC, 0o600)
with os.fdopen(fd, 'w') as output:
    output.write('\n'.join(lines) + '\n')
path.chmod(0o600)
print('BOT_TOKEN saved; service has not been started.')
