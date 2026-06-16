"""SQLite 데이터베이스 — 스키마 + CRUD."""
import sqlite3
import json
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager


class Database:
    def __init__(self, db_path: str):
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ── 초기화 ──────────────────────────────────────────────

    def init_db(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    code TEXT UNIQUE NOT NULL,
                    car_type TEXT DEFAULT '',
                    model_path TEXT,
                    face_a_class TEXT,
                    face_b_class TEXT,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TEXT DEFAULT (datetime('now','localtime')),
                    updated_at TEXT DEFAULT (datetime('now','localtime'))
                );

                CREATE TABLE IF NOT EXISTS product_parts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                    part_type TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    face TEXT NOT NULL CHECK(face IN ('A','B')),
                    required_count INTEGER NOT NULL DEFAULT 1,
                    yolo_class_name TEXT NOT NULL,
                    confidence_threshold REAL DEFAULT 0.5,
                    UNIQUE(product_id, part_type, face)
                );

                CREATE TABLE IF NOT EXISTS inspections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER REFERENCES products(id),
                    product_name TEXT NOT NULL,
                    result TEXT NOT NULL CHECK(result IN ('OK','NG')),
                    missing_parts TEXT,
                    a_face_photo TEXT,
                    b_face_photo TEXT,
                    duration_sec REAL,
                    inspected_at TEXT DEFAULT (datetime('now','localtime'))
                );

                CREATE TABLE IF NOT EXISTS daily_stats (
                    date TEXT NOT NULL,
                    product_id INTEGER NOT NULL,
                    total_count INTEGER DEFAULT 0,
                    ok_count INTEGER DEFAULT 0,
                    ng_count INTEGER DEFAULT 0,
                    PRIMARY KEY (date, product_id)
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)

    # ── 제품 ────────────────────────────────────────────────

    def get_products(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM products ORDER BY is_active DESC, name"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_product(self, product_id: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM products WHERE id=?", (product_id,)
            ).fetchone()
            return dict(row) if row else None

    def create_product(self, name: str, code: str, car_type: str = "",
                       model_path: str | None = None,
                       face_a_class: str | None = None,
                       face_b_class: str | None = None) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO products (name, code, car_type, model_path,
                   face_a_class, face_b_class)
                   VALUES (?,?,?,?,?,?)""",
                (name, code, car_type, model_path, face_a_class, face_b_class),
            )
            return cur.lastrowid

    def update_product(self, product_id: int, **fields) -> bool:
        if not fields:
            return False
        fields["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sets = ", ".join(f"{k}=?" for k in fields)
        vals = list(fields.values()) + [product_id]
        with self._conn() as conn:
            conn.execute(f"UPDATE products SET {sets} WHERE id=?", vals)
            return True

    def delete_product(self, product_id: int) -> bool:
        with self._conn() as conn:
            conn.execute("DELETE FROM products WHERE id=?", (product_id,))
            return True

    def get_active_products(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM products WHERE is_active=1 ORDER BY name"
            ).fetchall()
            return [dict(r) for r in rows]

    # ── 부자재 ──────────────────────────────────────────────

    def get_product_parts(self, product_id: int) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM product_parts WHERE product_id=? ORDER BY face, part_type",
                (product_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_product_parts_by_face(self, product_id: int, face: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM product_parts WHERE product_id=? AND face=?",
                (product_id, face),
            ).fetchall()
            return [dict(r) for r in rows]

    def add_product_part(self, product_id: int, part_type: str,
                         display_name: str, face: str,
                         required_count: int, yolo_class_name: str,
                         confidence_threshold: float = 0.5) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO product_parts
                   (product_id, part_type, display_name, face,
                    required_count, yolo_class_name, confidence_threshold)
                   VALUES (?,?,?,?,?,?,?)""",
                (product_id, part_type, display_name, face,
                 required_count, yolo_class_name, confidence_threshold),
            )
            return cur.lastrowid

    def update_product_part(self, part_id: int, **fields) -> bool:
        if not fields:
            return False
        sets = ", ".join(f"{k}=?" for k in fields)
        vals = list(fields.values()) + [part_id]
        with self._conn() as conn:
            conn.execute(f"UPDATE product_parts SET {sets} WHERE id=?", vals)
            return True

    def delete_product_part(self, part_id: int) -> bool:
        with self._conn() as conn:
            conn.execute("DELETE FROM product_parts WHERE id=?", (part_id,))
            return True

    # ── 검사 기록 ───────────────────────────────────────────

    def save_inspection(self, product_id: int, product_name: str,
                        result: str, missing_parts: list | None = None,
                        a_face_photo: str | None = None,
                        b_face_photo: str | None = None,
                        duration_sec: float | None = None) -> int:
        mp_json = json.dumps(missing_parts, ensure_ascii=False) if missing_parts else None
        with self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO inspections
                   (product_id, product_name, result, missing_parts,
                    a_face_photo, b_face_photo, duration_sec)
                   VALUES (?,?,?,?,?,?,?)""",
                (product_id, product_name, result, mp_json,
                 a_face_photo, b_face_photo, duration_sec),
            )
            # 일별 통계 UPSERT
            today = datetime.now().strftime("%Y-%m-%d")
            ok_inc = 1 if result == "OK" else 0
            ng_inc = 1 if result == "NG" else 0
            conn.execute(
                """INSERT INTO daily_stats (date, product_id, total_count, ok_count, ng_count)
                   VALUES (?, ?, 1, ?, ?)
                   ON CONFLICT(date, product_id) DO UPDATE SET
                   total_count = total_count + 1,
                   ok_count = ok_count + ?,
                   ng_count = ng_count + ?""",
                (today, product_id, ok_inc, ng_inc, ok_inc, ng_inc),
            )
            return cur.lastrowid

    def get_inspections(self, date: str | None = None,
                        product_id: int | None = None,
                        result: str | None = None,
                        limit: int = 100, offset: int = 0) -> list[dict]:
        query = "SELECT * FROM inspections WHERE 1=1"
        params: list = []
        if date:
            query += " AND DATE(inspected_at)=?"
            params.append(date)
        if product_id:
            query += " AND product_id=?"
            params.append(product_id)
        if result:
            query += " AND result=?"
            params.append(result)
        query += " ORDER BY inspected_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_inspection(self, inspection_id: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM inspections WHERE id=?", (inspection_id,)
            ).fetchone()
            return dict(row) if row else None

    # ── 통계 ────────────────────────────────────────────────

    def get_daily_stats(self, date: str | None = None,
                        product_id: int | None = None) -> list[dict]:
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        query = "SELECT * FROM daily_stats WHERE date=?"
        params: list = [date]
        if product_id:
            query += " AND product_id=?"
            params.append(product_id)
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_stats_range(self, start_date: str, end_date: str,
                        product_id: int | None = None) -> list[dict]:
        query = "SELECT * FROM daily_stats WHERE date BETWEEN ? AND ?"
        params: list = [start_date, end_date]
        if product_id:
            query += " AND product_id=?"
            params.append(product_id)
        query += " ORDER BY date"
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def delete_inspections_by_date(self, date: str):
        """해당 날짜 검사 기록 + 일별 통계 삭제."""
        with self._conn() as conn:
            conn.execute("DELETE FROM inspections WHERE DATE(inspected_at)=?", (date,))
            conn.execute("DELETE FROM daily_stats WHERE date=?", (date,))

    # ── 설정 ────────────────────────────────────────────────

    def get_settings(self) -> dict:
        with self._conn() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
            return {r["key"]: r["value"] for r in rows}

    def set_setting(self, key: str, value: str):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=?",
                (key, value, value),
            )

    # ── 시드 데이터 ─────────────────────────────────────────

    def seed_sp3_products(self):
        """SP3 초기 4종 제품 시드."""
        products = [
            ("RR PILLAR TRIM LH OVS", "85851-DE000OVS", "SP3"),
            ("RR PILLAR TRIM RH OVS", "85861-DE000OVS", "SP3"),
            ("RR PILLAR TRIM LH GYT", "85851-DE000GYT", "SP3"),
            ("RR PILLAR TRIM RH GYT", "85861-DE000GYT", "SP3"),
        ]
        with self._conn() as conn:
            for name, code, car in products:
                existing = conn.execute(
                    "SELECT id FROM products WHERE code=?", (code,)
                ).fetchone()
                if not existing:
                    conn.execute(
                        """INSERT INTO products (name, code, car_type)
                           VALUES (?,?,?)""",
                        (name, code, car),
                    )
