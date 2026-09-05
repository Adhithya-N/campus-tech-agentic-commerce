import os
import sqlite3

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "app.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    price_paise INTEGER NOT NULL,
    category TEXT NOT NULL,
    stock INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    razorpay_order_id TEXT UNIQUE,
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL,
    amount_paise INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending_confirmation'
        CHECK(status IN ('pending_confirmation', 'confirming', 'created', 'paid', 'failed')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    details TEXT,
    order_id INTEGER REFERENCES orders(id)
);
"""

# (name, description, price_paise, category, stock) - price_paise = price_inr * 100
SEED_PRODUCTS = [
    ("Wireless Earbuds", "Bluetooth 5.3 in-ear earbuds, 24h battery with case", 149900, "audio", 25),
    ("Phone Case (Clear)", "Shockproof clear case, fits most 6.1-inch phones", 29900, "accessories", 50),
    ("20W Fast Charger", "USB-C PD wall charger, 20W fast charging", 59900, "power", 40),
    ("USB-C Cable (1m)", "Braided USB-C to USB-C cable, 60W rated", 19900, "power", 60),
    ("Laptop Sleeve 14-inch", "Padded neoprene sleeve for 14-inch laptops", 79900, "accessories", 30),
    ("Notebook Set (3-pack)", "A5 ruled notebooks, 100 pages each", 24900, "stationery", 80),
    ("Mechanical Keyboard", "Compact 65% mechanical keyboard, hot-swappable", 299900, "electronics", 15),
    ("Wireless Mouse", "Silent-click wireless mouse, 1600 DPI", 89900, "electronics", 35),
]


def get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = get_connection()
    conn.executescript(SCHEMA)
    count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    if count == 0:
        conn.executemany(
            "INSERT INTO products (name, description, price_paise, category, stock) VALUES (?, ?, ?, ?, ?)",
            SEED_PRODUCTS,
        )
        conn.commit()
    conn.close()


def log_audit(actor: str, action: str, details: str = "", order_id: int | None = None) -> None:
    conn = get_connection()
    conn.execute(
        "INSERT INTO audit_log (actor, action, details, order_id) VALUES (?, ?, ?, ?)",
        (actor, action, details, order_id),
    )
    conn.commit()
    conn.close()
