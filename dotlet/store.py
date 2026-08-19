from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
from pathlib import Path

from .core import Record, Zone, canonical_host, canonical_zone, next_serial, validate_networks, validate_owner, validate_record, validate_ttl


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY, salt BLOB NOT NULL, password_hash BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS zones (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, default_ttl INTEGER NOT NULL,
    primary_ns TEXT NOT NULL, admin_email TEXT NOT NULL, serial INTEGER NOT NULL,
    refresh INTEGER NOT NULL DEFAULT 3600, retry INTEGER NOT NULL DEFAULT 900,
    expire INTEGER NOT NULL DEFAULT 1209600, minimum INTEGER NOT NULL DEFAULT 300
);
CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY, zone_id INTEGER NOT NULL REFERENCES zones(id) ON DELETE CASCADE,
    name TEXT NOT NULL, type TEXT NOT NULL, value TEXT NOT NULL, ttl INTEGER,
    UNIQUE(zone_id, name, type, value)
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)
            db.executemany("INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)", [
                ("recursion", "no"),
                ("trusted_networks", "127.0.0.0/8\n::1/128"),
            ])

    def set_password(self, username: str, password: str) -> None:
        if not username or len(username) > 64 or not username.replace("-", "").replace("_", "").isalnum():
            raise ValueError("Invalid username")
        if len(password) < 12:
            raise ValueError("Password must contain at least 12 characters")
        salt = os.urandom(16)
        digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
        with self.connect() as db:
            db.execute(
                "INSERT INTO users(username, salt, password_hash) VALUES(?, ?, ?) "
                "ON CONFLICT(username) DO UPDATE SET salt=excluded.salt, password_hash=excluded.password_hash",
                (username, salt, digest),
            )
            self._audit(db, username, "password-set", username)

    def authenticate(self, username: str, password: str) -> bool:
        with self.connect() as db:
            row = db.execute("SELECT salt, password_hash FROM users WHERE username=?", (username,)).fetchone()
        if row is None:
            hashlib.scrypt(password.encode(), salt=b"0" * 16, n=2**14, r=8, p=1)
            return False
        digest = hashlib.scrypt(password.encode(), salt=row["salt"], n=2**14, r=8, p=1)
        return hmac.compare_digest(digest, row["password_hash"])

    def has_users(self) -> bool:
        with self.connect() as db:
            return db.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None

    def add_zone(self, name: str, ttl: int | str, primary_ns: str, admin_email: str, actor: str) -> int:
        name = canonical_zone(name)
        ttl_value = validate_ttl(ttl)
        primary_ns = canonical_host(primary_ns)
        admin_email = canonical_host(admin_email)
        serial = next_serial(0)
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO zones(name, default_ttl, primary_ns, admin_email, serial) VALUES(?, ?, ?, ?, ?)",
                (name, ttl_value, primary_ns, admin_email, serial),
            )
            self._audit(db, actor, "zone-add", name)
            return int(cursor.lastrowid)

    def delete_zone(self, zone_id: int, actor: str) -> None:
        with self.connect() as db:
            row = db.execute("SELECT name FROM zones WHERE id=?", (zone_id,)).fetchone()
            if row:
                db.execute("DELETE FROM zones WHERE id=?", (zone_id,))
                self._audit(db, actor, "zone-delete", row["name"])

    def add_record(self, zone_id: int, name: str, record_type: str, value: str, ttl: int | str | None, actor: str) -> int:
        name = validate_owner(name)
        raw_value = value.strip()
        record_type, rendered_value = validate_record(record_type, raw_value)
        value = raw_value if record_type in {"TXT", "CAA"} else rendered_value
        ttl_value = validate_ttl(ttl, optional=True)
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO records(zone_id, name, type, value, ttl) VALUES(?, ?, ?, ?, ?)",
                (zone_id, name, record_type, value, ttl_value),
            )
            self._bump_serial(db, zone_id)
            self._audit(db, actor, "record-add", f"zone={zone_id} {name} {record_type} {value}")
            return int(cursor.lastrowid)

    def delete_record(self, record_id: int, actor: str) -> None:
        with self.connect() as db:
            row = db.execute("SELECT zone_id, name, type, value FROM records WHERE id=?", (record_id,)).fetchone()
            if row:
                db.execute("DELETE FROM records WHERE id=?", (record_id,))
                self._bump_serial(db, row["zone_id"])
                self._audit(db, actor, "record-delete", f'{row["name"]} {row["type"]} {row["value"]}')

    def update_settings(self, recursion: bool, trusted_networks: str, actor: str) -> None:
        networks = validate_networks(trusted_networks)
        with self.connect() as db:
            db.executemany("INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)", [
                ("recursion", "yes" if recursion else "no"),
                ("trusted_networks", "\n".join(networks)),
            ])
            self._audit(db, actor, "settings-update", f"recursion={recursion}; networks={','.join(networks)}")

    def snapshot(self) -> tuple[list[Zone], list[Record], dict[str, str]]:
        with self.connect() as db:
            zones = [Zone(**dict(row)) for row in db.execute("SELECT * FROM zones ORDER BY name")]
            records = [Record(**dict(row)) for row in db.execute("SELECT * FROM records ORDER BY zone_id, name, type")]
            settings = {row["key"]: row["value"] for row in db.execute("SELECT key, value FROM settings")}
        return zones, records, settings

    def audits(self, limit: int = 20) -> list[sqlite3.Row]:
        with self.connect() as db:
            return list(db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)))

    @staticmethod
    def _audit(db: sqlite3.Connection, actor: str, action: str, detail: str) -> None:
        db.execute("INSERT INTO audit(actor, action, detail) VALUES(?, ?, ?)", (actor, action, detail))

    @staticmethod
    def _bump_serial(db: sqlite3.Connection, zone_id: int) -> None:
        row = db.execute("SELECT serial FROM zones WHERE id=?", (zone_id,)).fetchone()
        if row is None:
            raise ValueError("Zone does not exist")
        db.execute("UPDATE zones SET serial=? WHERE id=?", (next_serial(row["serial"]), zone_id))


def random_password(length: int = 24) -> str:
    return secrets.token_urlsafe(length)[:length]
