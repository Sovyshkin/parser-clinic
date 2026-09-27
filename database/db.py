from __future__ import annotations

import json
from pathlib import Path

import aiosqlite

from database.models import Clinic, ClinicStatus, utc_now_iso


class ClinicRepository:
    def __init__(self, path: Path) -> None:
        self.path = path

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS clinics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain TEXT NOT NULL,
                    website TEXT NOT NULL,
                    clinic_name TEXT NOT NULL DEFAULT '',
                    phones TEXT NOT NULL DEFAULT '[]',
                    emails TEXT NOT NULL DEFAULT '[]',
                    telegram TEXT NOT NULL DEFAULT '[]',
                    whatsapp TEXT NOT NULL DEFAULT '[]',
                    vk TEXT NOT NULL DEFAULT '[]',
                    address TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'new'
                        CHECK(status IN ('new', 'parsed', 'failed')),
                    error TEXT NOT NULL DEFAULT '',
                    parsed_at TEXT,
                    parsed_run_id INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS ux_clinics_domain
                    ON clinics(domain);
                CREATE INDEX IF NOT EXISTS ix_clinics_status
                    ON clinics(status);
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    discovered INTEGER NOT NULL DEFAULT 0,
                    duplicates INTEGER NOT NULL DEFAULT 0,
                    successful INTEGER NOT NULL DEFAULT 0,
                    failed INTEGER NOT NULL DEFAULT 0,
                    stopped INTEGER NOT NULL DEFAULT 0
                );
                """
            )
            cursor = await db.execute("PRAGMA table_info(clinics)")
            columns = {row[1] for row in await cursor.fetchall()}
            if "parsed_run_id" not in columns:
                await db.execute(
                    "ALTER TABLE clinics ADD COLUMN parsed_run_id INTEGER"
                )
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS ix_clinics_parsed_run_id
                    ON clinics(parsed_run_id)
                """
            )
            await db.execute(
                """
                UPDATE clinics
                SET status = 'failed',
                    error = 'Предыдущий запуск был прерван до завершения',
                    updated_at = ?
                WHERE status = 'new'
                """,
                (utc_now_iso(),),
            )
            await db.commit()

    async def get_status(self, domain: str) -> ClinicStatus | None:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("SELECT status FROM clinics WHERE domain = ?", (domain,))
            row = await cursor.fetchone()
        return ClinicStatus(row[0]) if row else None

    async def reserve_new(self, domain: str, website: str) -> bool:
        now = utc_now_iso()
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """
                INSERT OR IGNORE INTO clinics
                    (domain, website, status, created_at, updated_at)
                VALUES (?, ?, 'new', ?, ?)
                """,
                (domain, website, now, now),
            )
            await db.commit()
            return cursor.rowcount == 1

    async def mark_parsed(self, clinic: Clinic, run_id: int | None = None) -> None:
        parsed_at = clinic.parsed_at or utc_now_iso()
        values = (
            clinic.website,
            clinic.clinic_name,
            json.dumps(list(clinic.phones), ensure_ascii=False),
            json.dumps(list(clinic.emails), ensure_ascii=False),
            json.dumps(list(clinic.telegram), ensure_ascii=False),
            json.dumps(list(clinic.whatsapp), ensure_ascii=False),
            json.dumps(list(clinic.vk), ensure_ascii=False),
            clinic.address,
            parsed_at,
            run_id,
            utc_now_iso(),
            clinic.domain,
        )
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                UPDATE clinics SET
                    website = ?, clinic_name = ?, phones = ?, emails = ?,
                    telegram = ?, whatsapp = ?, vk = ?, address = ?,
                    status = 'parsed', error = '', parsed_at = ?,
                    parsed_run_id = ?, updated_at = ?
                WHERE domain = ?
                """,
                values,
            )
            await db.commit()

    async def mark_failed(self, domain: str, error: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                UPDATE clinics
                SET status = 'failed', error = ?, updated_at = ?
                WHERE domain = ?
                """,
                (error[:1000], utc_now_iso(), domain),
            )
            await db.commit()

    async def release_new(self, domain: str) -> None:
        """Remove an unprocessed reservation after a graceful stop."""
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "DELETE FROM clinics WHERE domain = ? AND status = 'new'",
                (domain,),
            )
            await db.commit()

    async def list_failed(self) -> list[Clinic]:
        return await self._list("WHERE status = 'failed' ORDER BY updated_at")

    async def list_parsed(self) -> list[Clinic]:
        return await self._list("WHERE status = 'parsed' ORDER BY parsed_at, domain")

    async def list_parsed_for_run(self, run_id: int) -> list[Clinic]:
        return await self._list(
            "WHERE status = 'parsed' AND parsed_run_id = ? ORDER BY parsed_at, domain",
            (run_id,),
        )

    async def _list(
        self,
        clause: str = "",
        parameters: tuple = (),
    ) -> list[Clinic]:
        query = f"""
            SELECT domain, website, clinic_name, phones, emails, telegram,
                   whatsapp, vk, address, parsed_at, status, error
            FROM clinics {clause}
        """
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, parameters)
            rows = await cursor.fetchall()
        return [self._row_to_clinic(row) for row in rows]

    @staticmethod
    def _row_to_clinic(row: aiosqlite.Row) -> Clinic:
        def values(name: str) -> tuple[str, ...]:
            try:
                return tuple(json.loads(row[name]))
            except (TypeError, json.JSONDecodeError):
                return ()

        return Clinic(
            domain=row["domain"],
            website=row["website"],
            clinic_name=row["clinic_name"],
            phones=values("phones"),
            emails=values("emails"),
            telegram=values("telegram"),
            whatsapp=values("whatsapp"),
            vk=values("vk"),
            address=row["address"],
            parsed_at=row["parsed_at"],
            status=ClinicStatus(row["status"]),
            error=row["error"],
        )

    async def statistics(self) -> dict[str, int | str | None]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(status = 'parsed') AS parsed,
                    SUM(status = 'failed') AS failed,
                    SUM(
                        status = 'parsed'
                        AND date(parsed_at, 'localtime') = date('now', 'localtime')
                    ) AS today
                FROM clinics
                """
            )
            row = await cursor.fetchone()
            cursor = await db.execute(
                "SELECT MAX(started_at) FROM runs"
            )
            last_run = await cursor.fetchone()
        return {
            "total": int(row[0] or 0),
            "parsed": int(row[1] or 0),
            "failed": int(row[2] or 0),
            "today": int(row[3] or 0),
            "last_run": last_run[0],
        }

    async def start_run(self, query: str) -> int:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "INSERT INTO runs(query, started_at) VALUES (?, ?)",
                (query, utc_now_iso()),
            )
            await db.commit()
            return int(cursor.lastrowid)

    async def latest_run_id(self) -> int | None:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("SELECT MAX(id) FROM runs")
            row = await cursor.fetchone()
        return int(row[0]) if row and row[0] is not None else None

    async def finish_run(
        self,
        run_id: int,
        *,
        discovered: int,
        duplicates: int,
        successful: int,
        failed: int,
        stopped: bool,
    ) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                UPDATE runs SET finished_at = ?, discovered = ?, duplicates = ?,
                    successful = ?, failed = ?, stopped = ?
                WHERE id = ?
                """,
                (
                    utc_now_iso(),
                    discovered,
                    duplicates,
                    successful,
                    failed,
                    int(stopped),
                    run_id,
                ),
            )
            await db.commit()
