"""Statistics periods share the bot's SQLite storage; resets retain user data."""
from datetime import datetime, timezone


def init_stats(connection):
    columns = [row[1] for row in connection.execute('PRAGMA table_info(users)')]
    if 'receipt_received_at' not in columns:
        connection.execute('ALTER TABLE users ADD COLUMN receipt_received_at REAL')
    connection.execute('CREATE TABLE IF NOT EXISTS stats_period (id INTEGER PRIMARY KEY CHECK(id=1), since REAL NOT NULL)')
    connection.execute('INSERT OR IGNORE INTO stats_period(id, since) VALUES(1, 0)')


def get_stats(connection):
    since = connection.execute('SELECT since FROM stats_period WHERE id=1').fetchone()[0]
    started = connection.execute('SELECT COUNT(*) FROM users WHERE started_at >= ?', (since,)).fetchone()[0]
    receipts = connection.execute(
        'SELECT COUNT(*) FROM users WHERE receipt_received_at >= ? OR (?=0 AND paid=1)', (since, since)
    ).fetchone()[0]
    awaiting = connection.execute('SELECT COUNT(*) FROM users WHERE awaiting_receipt=1').fetchone()[0]
    total = connection.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    return since, started, receipts, awaiting, total


def reset_stats(connection, timestamp):
    with connection:
        connection.execute('UPDATE stats_period SET since=? WHERE id=1', (timestamp,))


def format_stats(snapshot):
    since, started, receipts, awaiting, total = snapshot
    period = datetime.fromtimestamp(since, tz=timezone.utc).strftime('%d.%m.%Y %H:%M:%S UTC') if since else 'за всё время'
    return (
        f'📊 <b>Статистика</b> ({period})\n'
        f'Начали воронку за период: <b>{started}</b>\n'
        f'Получено чеков за период: <b>{receipts}</b>\n'
        f'Сейчас ожидается отправка чека: <b>{awaiting}</b>\n'
        f'Всего пользователей в базе: <b>{total}</b>\n\n'
        'Чеки — поступившие подтверждения перевода, их оплату проверяет администратор.\n'
        '/reset_stats — начать новый период подсчёта.'
    )
