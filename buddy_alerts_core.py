"""
Buddy alerts: shared DB logic for main.py and scripts/run_buddy_daily_digest.py.
Daily digest runs on host OS with direct PostgreSQL access (no HTTP internal route).
"""
from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from psycopg2.extras import Json, RealDictCursor

DEFAULT_BUDDY_ALERT_TZ = os.getenv("BUDDY_ALERT_TZ", "Europe/Moscow")


def buddy_alert_tz() -> ZoneInfo:
    try:
        return ZoneInfo(DEFAULT_BUDDY_ALERT_TZ)
    except Exception:
        return ZoneInfo("Europe/Moscow")


def ensure_buddy_alerts_schema(cur) -> None:
    """Idempotent schema bootstrap (sandbox without manual migration)."""
    cur.execute("""
        ALTER TABLE user_buddy_links
            ADD COLUMN IF NOT EXISTS alert_steps_enabled BOOLEAN NOT NULL DEFAULT FALSE
    """)
    cur.execute("""
        ALTER TABLE user_buddy_links
            ADD COLUMN IF NOT EXISTS alert_reports_enabled BOOLEAN NOT NULL DEFAULT FALSE
    """)
    cur.execute("""
        ALTER TABLE users
            ADD COLUMN IF NOT EXISTS buddy_alert_daily_at TIME NOT NULL DEFAULT '23:00:00'
    """)
    cur.execute("""
        ALTER TABLE users ADD COLUMN IF NOT EXISTS timezone VARCHAR(64) NULL
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS buddy_step_daily_reports (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            report_date DATE NOT NULL,
            sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            send_method VARCHAR(16) NOT NULL CHECK (send_method IN ('copy', 'share')),
            UNIQUE (user_id, report_date)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS buddy_alert_notifications (
            id BIGSERIAL PRIMARY KEY,
            recipient_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            subject_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            alert_type VARCHAR(32) NOT NULL
                CHECK (alert_type IN ('steps_success_100', 'steps_missed', 'report_not_sent')),
            report_date DATE NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            read_at TIMESTAMPTZ NULL,
            UNIQUE (recipient_id, subject_id, alert_type, report_date)
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_buddy_alert_notif_recipient_created
            ON buddy_alert_notifications (recipient_id, created_at DESC)
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS buddy_daily_digest_runs (
            id BIGSERIAL PRIMARY KEY,
            subject_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            report_date DATE NOT NULL,
            digest_kind VARCHAR(32) NOT NULL
                CHECK (digest_kind IN ('steps_missed', 'report_not_sent')),
            ran_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (subject_id, report_date, digest_kind)
        )
    """)


def _user_display_name(row: Optional[dict]) -> str:
    if not row:
        return "Участник"
    name = f"{row.get('name') or ''} {row.get('surname') or ''}".strip()
    return name or f"Участник #{row.get('id', '')}"


def fetch_subject_name(cur, subject_id: int) -> str:
    cur.execute("SELECT id, name, surname FROM users WHERE id = %s", (subject_id,))
    return _user_display_name(cur.fetchone())


def fetch_day_steps(cur, user_id: int, report_date: date) -> List[dict]:
    """Steps scheduled on report_date (deadline), not deleted."""
    day_iso = report_date.isoformat()
    sql_with_waived = """
        SELECT s.id, s.title, s.completed, COALESCE(s.waived, false) AS waived
        FROM dreams_steps s
        JOIN dreams d ON d.id = s.dream_id
        WHERE d.user_id = %s
          AND s.deadline = %s
          AND COALESCE(s.deleted, false) = false
        ORDER BY s.id
    """
    sql_no_waived = """
        SELECT s.id, s.title, s.completed, false AS waived
        FROM dreams_steps s
        JOIN dreams d ON d.id = s.dream_id
        WHERE d.user_id = %s
          AND s.deadline = %s
          AND COALESCE(s.deleted, false) = false
        ORDER BY s.id
    """
    for sql in (sql_with_waived, sql_no_waived):
        try:
            cur.execute(sql, (user_id, day_iso))
            return [dict(r) for r in cur.fetchall()]
        except Exception:
            try:
                cur.connection.rollback()
            except Exception:
                pass
    return []


def compute_day_efficiency(steps: List[dict]) -> Optional[Dict[str, Any]]:
    """100% = all steps completed with ✓ (not waived). Returns None if no steps."""
    if not steps:
        return None
    total = len(steps)
    completed = sum(1 for s in steps if s.get("completed") and not s.get("waived"))
    missed = [
        {"step_id": s["id"], "title": (s.get("title") or "").strip() or f"Шаг #{s['id']}"}
        for s in steps
        if not (s.get("completed") and not s.get("waived"))
    ]
    pct = round(100 * completed / total) if total else 0
    return {
        "total": total,
        "completed": completed,
        "efficiency_pct": pct,
        "missed_steps": missed,
    }


def list_alert_recipients(cur, subject_id: int, *, for_reports: bool) -> List[int]:
    col = "alert_reports_enabled" if for_reports else "alert_steps_enabled"
    cur.execute(
        f"""
        SELECT viewer_id FROM user_buddy_links
        WHERE subject_id = %s AND status = 'active' AND can_read = true
          AND {col} = true
        """,
        (subject_id,),
    )
    return [int(r["viewer_id"]) for r in cur.fetchall()]


def insert_buddy_notification(
    cur,
    recipient_id: int,
    subject_id: int,
    alert_type: str,
    report_date: date,
    payload: dict,
) -> bool:
    """Insert notification; return True if a new row was created."""
    cur.execute(
        """
        INSERT INTO buddy_alert_notifications
            (recipient_id, subject_id, alert_type, report_date, payload)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (recipient_id, subject_id, alert_type, report_date) DO NOTHING
        RETURNING id
        """,
        (recipient_id, subject_id, alert_type, report_date.isoformat(), Json(payload)),
    )
    return cur.fetchone() is not None


def record_digest_run(cur, subject_id: int, report_date: date, digest_kind: str) -> bool:
    cur.execute(
        """
        INSERT INTO buddy_daily_digest_runs (subject_id, report_date, digest_kind)
        VALUES (%s, %s, %s)
        ON CONFLICT (subject_id, report_date, digest_kind) DO NOTHING
        RETURNING id
        """,
        (subject_id, report_date.isoformat(), digest_kind),
    )
    return cur.fetchone() is not None


def report_was_sent(cur, user_id: int, report_date: date) -> bool:
    cur.execute(
        "SELECT 1 FROM buddy_step_daily_reports WHERE user_id = %s AND report_date = %s",
        (user_id, report_date.isoformat()),
    )
    return cur.fetchone() is not None


def mark_daily_report_sent(cur, user_id: int, report_date: date, send_method: str) -> bool:
    cur.execute(
        """
        INSERT INTO buddy_step_daily_reports (user_id, report_date, send_method)
        VALUES (%s, %s, %s)
        ON CONFLICT (user_id, report_date) DO NOTHING
        RETURNING id
        """,
        (user_id, report_date.isoformat(), send_method),
    )
    return cur.fetchone() is not None


def fan_out_steps_success_100(cur, subject_id: int, report_date: date) -> int:
    stats = compute_day_efficiency(fetch_day_steps(cur, subject_id, report_date))
    if not stats or stats["efficiency_pct"] != 100:
        return 0
    subject_name = fetch_subject_name(cur, subject_id)
    payload = {
        "efficiency_pct": stats["efficiency_pct"],
        "completed": stats["completed"],
        "total": stats["total"],
        "subject_name": subject_name,
    }
    created = 0
    for recipient_id in list_alert_recipients(cur, subject_id, for_reports=False):
        if insert_buddy_notification(
            cur, recipient_id, subject_id, "steps_success_100", report_date, payload
        ):
            created += 1
    return created


def run_subject_daily_digest(cur, subject_id: int, report_date: date) -> int:
    """End-of-day digest: missed steps + report not sent. Returns notifications created."""
    steps = fetch_day_steps(cur, subject_id, report_date)
    stats = compute_day_efficiency(steps)
    if not stats:
        return 0

    subject_name = fetch_subject_name(cur, subject_id)
    created = 0
    base_payload = {
        "efficiency_pct": stats["efficiency_pct"],
        "completed": stats["completed"],
        "total": stats["total"],
        "subject_name": subject_name,
    }

    if stats["efficiency_pct"] < 100:
        if record_digest_run(cur, subject_id, report_date, "steps_missed"):
            payload = {**base_payload, "missed_steps": stats["missed_steps"]}
            for recipient_id in list_alert_recipients(cur, subject_id, for_reports=False):
                if insert_buddy_notification(
                    cur, recipient_id, subject_id, "steps_missed", report_date, payload
                ):
                    created += 1
    elif stats["efficiency_pct"] == 100 and not report_was_sent(cur, subject_id, report_date):
        if record_digest_run(cur, subject_id, report_date, "report_not_sent"):
            for recipient_id in list_alert_recipients(cur, subject_id, for_reports=True):
                if insert_buddy_notification(
                    cur, recipient_id, subject_id, "report_not_sent", report_date, base_payload
                ):
                    created += 1
    return created


def _link_flag_aggregate(cur, sql: str, params: tuple) -> bool:
    cur.execute(sql, params)
    rows = cur.fetchall()
    if not rows:
        return False
    return all(bool(r["enabled"]) for r in rows)


def get_buddy_alert_settings(cur, user_id: int) -> dict:
    ensure_buddy_alerts_schema(cur)
    share_steps = _link_flag_aggregate(
        cur,
        """
        SELECT alert_steps_enabled AS enabled FROM user_buddy_links
        WHERE subject_id = %s AND status = 'active'
        """,
        (user_id,),
    )
    share_reports = _link_flag_aggregate(
        cur,
        """
        SELECT alert_reports_enabled AS enabled FROM user_buddy_links
        WHERE subject_id = %s AND status = 'active'
        """,
        (user_id,),
    )
    receive_steps = _link_flag_aggregate(
        cur,
        """
        SELECT alert_steps_enabled AS enabled FROM user_buddy_links
        WHERE viewer_id = %s AND status = 'active'
        """,
        (user_id,),
    )
    receive_reports = _link_flag_aggregate(
        cur,
        """
        SELECT alert_reports_enabled AS enabled FROM user_buddy_links
        WHERE viewer_id = %s AND status = 'active'
        """,
        (user_id,),
    )
    daily_at = time(23, 0)
    try:
        cur.execute("SELECT buddy_alert_daily_at FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        if row and row.get("buddy_alert_daily_at"):
            daily_at = row["buddy_alert_daily_at"]
    except Exception:
        pass
    daily_str = daily_at.strftime("%H:%M") if hasattr(daily_at, "strftime") else "23:00"
    return {
        "share_steps": share_steps,
        "share_reports": share_reports,
        "receive_steps": receive_steps,
        "receive_reports": receive_reports,
        "daily_alert_at": daily_str,
        "timezone": DEFAULT_BUDDY_ALERT_TZ,
    }


def patch_buddy_alert_settings(
    cur,
    user_id: int,
    *,
    share_steps: Optional[bool] = None,
    share_reports: Optional[bool] = None,
    receive_steps: Optional[bool] = None,
    receive_reports: Optional[bool] = None,
    daily_alert_at: Optional[str] = None,
) -> dict:
    ensure_buddy_alerts_schema(cur)
    if share_steps is not None:
        cur.execute(
            """
            UPDATE user_buddy_links SET alert_steps_enabled = %s
            WHERE subject_id = %s AND status = 'active'
            """,
            (share_steps, user_id),
        )
    if share_reports is not None:
        cur.execute(
            """
            UPDATE user_buddy_links SET alert_reports_enabled = %s
            WHERE subject_id = %s AND status = 'active'
            """,
            (share_reports, user_id),
        )
    if receive_steps is not None:
        cur.execute(
            """
            UPDATE user_buddy_links SET alert_steps_enabled = %s
            WHERE viewer_id = %s AND status = 'active'
            """,
            (receive_steps, user_id),
        )
    if receive_reports is not None:
        cur.execute(
            """
            UPDATE user_buddy_links SET alert_reports_enabled = %s
            WHERE viewer_id = %s AND status = 'active'
            """,
            (receive_reports, user_id),
        )
    if daily_alert_at:
        parts = daily_alert_at.strip().split(":")
        if len(parts) >= 2:
            try:
                hh, mm = int(parts[0]), int(parts[1])
                if 0 <= hh <= 23 and 0 <= mm <= 59:
                    cur.execute(
                        "UPDATE users SET buddy_alert_daily_at = %s WHERE id = %s",
                        (time(hh, mm), user_id),
                    )
            except ValueError:
                pass
    return get_buddy_alert_settings(cur, user_id)


def count_unread_buddy_alerts(cur, user_id: int) -> int:
    ensure_buddy_alerts_schema(cur)
    try:
        cur.execute(
            """
            SELECT COUNT(*) AS n FROM buddy_alert_notifications
            WHERE recipient_id = %s AND read_at IS NULL
            """,
            (user_id,),
        )
        row = cur.fetchone()
        return int(row["n"] or 0) if row else 0
    except Exception:
        return 0


def fetch_buddy_notifications(cur, user_id: int, limit: int = 50) -> List[dict]:
    ensure_buddy_alerts_schema(cur)
    try:
        cur.execute(
            """
            SELECT n.id, n.subject_id, n.alert_type, n.report_date, n.payload, n.created_at,
                   u.name, u.surname
            FROM buddy_alert_notifications n
            JOIN users u ON u.id = n.subject_id
            WHERE n.recipient_id = %s
            ORDER BY n.created_at DESC
            LIMIT %s
            """,
            (user_id, limit),
        )
        out = []
        for r in cur.fetchall():
            at_val = r.get("created_at")
            at_str = at_val.isoformat() if at_val and hasattr(at_val, "isoformat") else str(at_val or "")
            report_date = r.get("report_date")
            rd_str = report_date.isoformat() if hasattr(report_date, "isoformat") else str(report_date or "")
            payload = r.get("payload") or {}
            if isinstance(payload, str):
                payload = {}
            subject_name = payload.get("subject_name") or _user_display_name(r)
            out.append({
                "type": r["alert_type"],
                "id": r["id"],
                "subject_id": r["subject_id"],
                "subject_name": subject_name,
                "report_date": rd_str,
                "payload": payload,
                "_at": at_str,
            })
        return out
    except Exception:
        return []


def mark_buddy_notification_read(cur, notification_id: int, user_id: int) -> bool:
    ensure_buddy_alerts_schema(cur)
    cur.execute(
        """
        UPDATE buddy_alert_notifications SET read_at = NOW()
        WHERE id = %s AND recipient_id = %s AND read_at IS NULL
        RETURNING id
        """,
        (notification_id, user_id),
    )
    return cur.fetchone() is not None


def _parse_daily_at(val) -> time:
    if val is None:
        return time(23, 0)
    if isinstance(val, time):
        return val
    s = str(val)
    parts = s.split(":")
    if len(parts) >= 2:
        try:
            return time(int(parts[0]), int(parts[1]))
        except ValueError:
            pass
    return time(23, 0)


def run_daily_digest(cur, now: Optional[datetime] = None) -> Tuple[int, int]:
    """
    Process all subjects whose buddy_alert_daily_at has passed today (Moscow TZ).
    Returns (subjects_processed, notifications_created).
    """
    ensure_buddy_alerts_schema(cur)
    tz = buddy_alert_tz()
    now = now or datetime.now(tz)
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    else:
        now = now.astimezone(tz)
    report_date = now.date()
    now_t = now.time().replace(second=0, microsecond=0)

    cur.execute(
        """
        SELECT DISTINCT d.user_id AS subject_id, u.buddy_alert_daily_at
        FROM dreams_steps s
        JOIN dreams d ON d.id = s.dream_id
        JOIN users u ON u.id = d.user_id
        WHERE s.deadline = %s AND COALESCE(s.deleted, false) = false
        """,
        (report_date.isoformat(),),
    )
    candidates = cur.fetchall()

    subjects_processed = 0
    notifications_created = 0
    for row in candidates:
        subject_id = int(row["subject_id"])
        alert_at = _parse_daily_at(row.get("buddy_alert_daily_at"))
        if now_t < alert_at:
            continue
        subjects_processed += 1
        notifications_created += run_subject_daily_digest(cur, subject_id, report_date)
    return subjects_processed, notifications_created
