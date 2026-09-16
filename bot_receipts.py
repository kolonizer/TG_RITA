"""Persistent payment quotes and receipt forwarding in the existing SQLite DB."""


def init_receipts(connection):
    columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
    if "receipt_quote_id" not in columns:
        connection.execute("ALTER TABLE users ADD COLUMN receipt_quote_id INTEGER")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS payment_quotes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            price_without INTEGER NOT NULL,
            price_with INTEGER NOT NULL,
            created_at REAL NOT NULL,
            UNIQUE(user_id, chat_id, message_id)
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS receipt_deliveries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            generation INTEGER NOT NULL,
            source_chat_id INTEGER NOT NULL,
            source_message_id INTEGER NOT NULL,
            admin_id INTEGER NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('photo', 'document')),
            file_id TEXT NOT NULL,
            caption TEXT NOT NULL,
            created_at REAL NOT NULL,
            sent_at REAL,
            retry_at REAL,
            sending_at REAL,
            last_error TEXT,
            UNIQUE(source_chat_id, source_message_id, admin_id)
        )
    """)
    connection.execute("""
        CREATE INDEX IF NOT EXISTS receipts_pending ON receipt_deliveries(retry_at, id)
        WHERE sent_at IS NULL
    """)
    connection.execute("CREATE INDEX IF NOT EXISTS receipts_user_generation ON receipt_deliveries(user_id, generation)")
    # Receipt forwarding favours eventual delivery; interrupted forwards are retried.
    connection.execute("UPDATE receipt_deliveries SET sending_at=NULL WHERE sent_at IS NULL")


def save_quote(connection, user_id, chat_id, message_id, prices, timestamp):
    with connection:
        connection.execute("""
            INSERT INTO payment_quotes(user_id, chat_id, message_id, price_without, price_with, created_at)
            VALUES(?,?,?,?,?,?) ON CONFLICT(user_id, chat_id, message_id) DO NOTHING
        """, (user_id, chat_id, message_id, *prices, timestamp))


def select_quote(connection, user_id, chat_id, message_id):
    row = connection.execute(
        "SELECT id FROM payment_quotes WHERE user_id=? AND chat_id=? AND message_id=?", (user_id, chat_id, message_id)
    ).fetchone()
    with connection:
        connection.execute("UPDATE users SET awaiting_receipt=1, receipt_quote_id=? WHERE user_id=? AND paid=0",
                           (row[0] if row else None, user_id))


def receipt_prices(connection, user_id):
    return connection.execute("""
        SELECT q.price_without, q.price_with FROM payment_quotes AS q JOIN users AS u
        ON u.receipt_quote_id=q.id AND u.user_id=q.user_id WHERE u.user_id=?
    """, (user_id,)).fetchone()


def save_receipt(connection, user_id, chat_id, message_id, kind, file_id, caption, timestamp, admins):
    with connection:
        user = connection.execute("""
            SELECT (SELECT MIN(id) FROM queue WHERE user_id=users.user_id AND step BETWEEN 2 AND 10), awaiting_receipt
            FROM users WHERE user_id=?
        """, (user_id,)).fetchone()
        if not user or user[0] is None or not user[1]:
            return []
        connection.executemany("""
            INSERT OR IGNORE INTO receipt_deliveries
            (user_id, generation, source_chat_id, source_message_id, admin_id, kind, file_id, caption, created_at)
            VALUES(?,?,?,?,?,?,?,?,?)
        """, [(user_id, user[0], chat_id, message_id, admin, kind, file_id, caption, timestamp) for admin in admins])
        connection.execute("UPDATE users SET receipt_received_at=COALESCE(receipt_received_at, ?) WHERE user_id=?", (timestamp, user_id))
        return [row[0] for row in connection.execute(
            "SELECT id FROM receipt_deliveries WHERE source_chat_id=? AND source_message_id=?", (chat_id, message_id)
        )]


def claim_delivery(connection, delivery_id, timestamp, stale_before):
    with connection:
        claimed = connection.execute("""
            UPDATE receipt_deliveries SET sending_at=? WHERE id=? AND sent_at IS NULL
            AND (sending_at IS NULL OR sending_at<=?) AND COALESCE(retry_at, 0)<=?
        """, (timestamp, delivery_id, stale_before, timestamp))
        if not claimed.rowcount:
            return None
        return connection.execute(
            "SELECT admin_id, kind, file_id, caption FROM receipt_deliveries WHERE id=?", (delivery_id,)
        ).fetchone()


def finish_delivery(connection, delivery_id, timestamp):
    with connection:
        row = connection.execute(
            "SELECT user_id, generation FROM receipt_deliveries WHERE id=?", (delivery_id,)
        ).fetchone()
        connection.execute("UPDATE receipt_deliveries SET sent_at=?, sending_at=NULL, retry_at=NULL, last_error=NULL WHERE id=?",
                           (timestamp, delivery_id))
        updated = connection.execute("""
            UPDATE users SET paid=1, awaiting_receipt=0
            WHERE user_id=? AND paid=0 AND EXISTS (
                SELECT 1 FROM queue WHERE user_id=users.user_id AND id=?
            )
        """, row)
        if updated.rowcount:
            connection.execute("""
                UPDATE queue SET cancelled_at=? WHERE user_id=?
                AND sent_at IS NULL AND cancelled_at IS NULL
            """, (timestamp, row[0]))


def defer_delivery(connection, delivery_id, timestamp, error_name):
    with connection:
        connection.execute("""
            UPDATE receipt_deliveries SET sending_at=NULL, retry_at=?, last_error=?
            WHERE id=? AND sent_at IS NULL
        """, (timestamp, error_name, delivery_id))
