"""Persistent runtime settings shared by Telegram and terminal commands."""


def init_settings(connection, default_test_mode):
    connection.execute('CREATE TABLE IF NOT EXISTS runtime_settings (name TEXT PRIMARY KEY, value INTEGER NOT NULL)')
    connection.execute('INSERT OR IGNORE INTO runtime_settings(name, value) VALUES(?, ?)', ('test_mode', int(default_test_mode)))


def get_test_mode(connection):
    return bool(connection.execute("SELECT value FROM runtime_settings WHERE name='test_mode'").fetchone()[0])


def set_test_mode(connection, enabled):
    with connection:
        connection.execute(
            'INSERT INTO runtime_settings(name, value) VALUES(?, ?) ON CONFLICT(name) DO UPDATE SET value=excluded.value',
            ('test_mode', int(enabled)),
        )
