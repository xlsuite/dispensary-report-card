"""
SQLite persistence for the Dispensary Report Card.

Two tables:
  scans — every report ever generated, keyed by a short random token.
          The token is the shareable report URL (/r/<token>).
  leads — emails captured by the report gate, linked to the scan that
          produced them, with an explicit marketing-consent flag (CASL:
          only emails with marketing_consent=1 should be imported into
          marketing lists; the rest unlocked a report and nothing more).

DB file location comes from the DB_PATH env var. On Render this points to
the persistent disk (/data/reports.db); locally it defaults to ./reports.db.
"""

from __future__ import annotations

import csv
import io
import os
import secrets
import sqlite3


def _db_path() -> str:
    return os.environ.get("DB_PATH", "reports.db")


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_db_path())
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS scans (
                token       TEXT PRIMARY KEY,
                url         TEXT NOT NULL,
                hostname    TEXT,
                score       REAL,
                grade       TEXT,
                report_html TEXT,
                created_at  TEXT DEFAULT (datetime('now'))
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                email             TEXT NOT NULL,
                scan_token        TEXT,
                marketing_consent INTEGER DEFAULT 0,
                created_at        TEXT DEFAULT (datetime('now'))
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_scans_host ON scans(hostname)")


def save_scan(url: str, hostname: str, score: float, grade: str,
              report_html: str) -> str:
    """Persist a finished scan; returns the shareable token."""
    token = secrets.token_urlsafe(8)
    with _conn() as c:
        c.execute(
            "INSERT INTO scans (token, url, hostname, score, grade, report_html) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (token, url, hostname, score, grade, report_html),
        )
    return token


def get_recent_scan(url: str, max_age_seconds: int = 3600):
    """Most recent stored scan of this exact URL within the window, or None."""
    with _conn() as c:
        return c.execute(
            "SELECT token FROM scans WHERE url = ? AND "
            "created_at >= datetime('now', ?) "
            "ORDER BY created_at DESC LIMIT 1",
            (url, f"-{int(max_age_seconds)} seconds"),
        ).fetchone()


def get_scan(token: str):
    with _conn() as c:
        return c.execute(
            "SELECT * FROM scans WHERE token = ?", (token,)
        ).fetchone()


def save_lead(email: str, scan_token: str, marketing_consent: bool) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO leads (email, scan_token, marketing_consent) "
            "VALUES (?, ?, ?)",
            (email.strip().lower(), scan_token, 1 if marketing_consent else 0),
        )


def list_leads(limit: int = 500):
    """Leads newest-first, joined with the scan that captured them."""
    with _conn() as c:
        return c.execute("""
            SELECT l.email, l.marketing_consent, l.created_at,
                   s.hostname, s.url, s.score, s.grade, l.scan_token
            FROM leads l LEFT JOIN scans s ON s.token = l.scan_token
            ORDER BY l.id DESC LIMIT ?
        """, (limit,)).fetchall()


def list_scans(limit: int = 500):
    with _conn() as c:
        return c.execute("""
            SELECT token, url, hostname, score, grade, created_at
            FROM scans ORDER BY created_at DESC LIMIT ?
        """, (limit,)).fetchall()


def counts() -> tuple[int, int]:
    with _conn() as c:
        n_scans = c.execute("SELECT COUNT(*) FROM scans").fetchone()[0]
        n_leads = c.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
    return n_scans, n_leads


def leads_csv() -> str:
    """All leads as CSV (for import into an ESP — filter on consent!)."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["email", "marketing_consent", "captured_at_utc",
                "scanned_site", "scanned_url", "score", "grade"])
    for r in list_leads(limit=100000):
        w.writerow([r["email"], r["marketing_consent"], r["created_at"],
                    r["hostname"] or "", r["url"] or "",
                    r["score"] if r["score"] is not None else "",
                    r["grade"] or ""])
    return buf.getvalue()
