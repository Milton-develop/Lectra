"""Data access layer backed by Supabase (PostgreSQL).

All persistence goes through a single lazily-initialised Supabase client so
every route reuses the same connection. Authentication is handled by Flask
(bcrypt + sessions); Supabase is used purely as the database.
"""

import uuid
import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import bcrypt
from supabase import create_client

from config import Config

try:
    from pywebpush import WebPushException, webpush
except ImportError:  # Allows in-app notifications before push is configured.
    WebPushException = Exception
    webpush = None

_client = None


def db():
    """Return the shared Supabase client (created on first use)."""
    global _client
    if _client is None:
        if not Config.SUPABASE_URL or not Config.SUPABASE_KEY:
            raise RuntimeError(
                "Supabase is not configured. Copy .env.example to .env and "
                "set SUPABASE_URL and SUPABASE_KEY."
            )
        _client = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)
    return _client


def utc_now():
    """ISO-8601 UTC timestamp string."""
    return datetime.now(timezone.utc).isoformat()


def new_uuid():
    return str(uuid.uuid4())


def _rows(result):
    """Extract a list of rows from a supabase-py execute() result.

    supabase-py can return ``None`` (e.g. ``maybe_single`` with no match),
    so this helper tolerates it and always returns a list.
    """
    if result is None:
        return []
    data = getattr(result, "data", None) or []
    return data


def _first(result):
    """Extract the first row from an execute() result, or None."""
    if result is None:
        return None
    data = getattr(result, "data", None)
    if data is None:
        return None
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        return data[0] if data else None
    return None


def _count(result):
    """Extract a row count from an execute() result, or 0."""
    if result is None:
        return 0
    return getattr(result, "count", None) or 0


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def get_user_by_email(email):
    result = (
        db().table("users")
        .select("*")
        .eq("email", email.lower().strip())
        .maybe_single()
        .execute()
    )
    return _first(result)


def get_user_by_id(user_id):
    result = (
        db().table("users")
        .select("*")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    return _first(result)


def create_user(fullname, email, password, department=None,
                institution=None, phone=None):
    password_hash = bcrypt.hashpw(
        password.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")
    result = (
        db().table("users")
        .insert({
            "fullname": fullname.strip(),
            "email": email.lower().strip(),
            "password_hash": password_hash,
            "department": department or None,
            "institution": institution or None,
            "phone": phone or None,
        })
        .execute()
    )
    return _first(result)


def verify_password(password, password_hash):
    return bcrypt.checkpw(
        password.encode("utf-8"), password_hash.encode("utf-8")
    )


def update_user(user_id, **fields):
    fields = {k: (v if v != "" else None) for k, v in fields.items()}
    fields["updated_at"] = utc_now()
    result = (
        db().table("users")
        .update(fields)
        .eq("id", user_id)
        .execute()
    )
    return _first(result)


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------

def create_schedule(user_id, data):
    row = {**data, "user_id": user_id}
    result = db().table("schedules").insert(row).execute()
    return _first(result)


def get_schedule(schedule_id, user_id=None):
    query = db().table("schedules").select("*").eq("id", schedule_id)
    if user_id:
        query = query.eq("user_id", user_id)
    result = query.maybe_single().execute()
    return _first(result)


def list_schedules(user_id):
    result = (
        db().table("schedules")
        .select("*")
        .eq("user_id", user_id)
        .order("event_date")
        .order("start_time")
        .execute()
    )
    return _rows(result)


def list_schedules_between(user_id, start_date, end_date):
    result = (
        db().table("schedules")
        .select("*")
        .eq("user_id", user_id)
        .gte("event_date", start_date)
        .lte("event_date", end_date)
        .order("event_date")
        .order("start_time")
        .execute()
    )
    return _rows(result)


def list_upcoming(user_id, start_date, limit=100):
    result = (
        db().table("schedules")
        .select("*")
        .eq("user_id", user_id)
        .in_("status", ["upcoming", "rescheduled"])
        .gte("event_date", start_date)
        .order("event_date")
        .order("start_time")
        .limit(limit)
        .execute()
    )
    return _rows(result)


def list_completed(user_id, limit=100):
    result = (
        db().table("schedules")
        .select("*")
        .eq("user_id", user_id)
        .eq("status", "completed")
        .order("event_date", desc=True)
        .limit(limit)
        .execute()
    )
    return _rows(result)


def search_schedules(user_id, q=None, status=None, category=None):
    query = db().table("schedules").select("*").eq("user_id", user_id)
    if q:
        term = q.strip().replace("%", "")
        query = query.or_(
            f"title.ilike.%{term}%,description.ilike.%{term}%,"
            f"location.ilike.%{term}%,category.ilike.%{term}%"
        )
    if status:
        query = query.eq("status", status)
    if category:
        query = query.eq("category", category)
    result = (
        query.order("event_date", desc=True)
        .order("start_time")
        .execute()
    )
    return _rows(result)


def update_schedule(schedule_id, data):
    data = dict(data)
    data["updated_at"] = utc_now()
    result = (
        db().table("schedules")
        .update(data)
        .eq("id", schedule_id)
        .execute()
    )
    return _first(result)


def delete_schedule(schedule_id, user_id=None):
    query = db().table("schedules").delete().eq("id", schedule_id)
    if user_id:
        query = query.eq("user_id", user_id)
    result = query.execute()
    return bool(_rows(result))


def count_schedules(user_id, status=None):
    query = (
        db().table("schedules")
        .select("*", count="exact")
        .eq("user_id", user_id)
    )
    if status:
        query = query.eq("status", status)
    result = query.execute()
    return _count(result)


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------

def create_reminder(schedule_id, reminder_minutes):
    result = (
        db().table("reminders")
        .insert({
            "schedule_id": schedule_id,
            "reminder_minutes": int(reminder_minutes),
        })
        .execute()
    )
    return _first(result)


def list_reminders(schedule_id):
    result = (
        db().table("reminders")
        .select("*")
        .eq("schedule_id", schedule_id)
        .order("reminder_minutes")
        .execute()
    )
    return _rows(result)


def replace_reminders(schedule_id, minutes):
    db().table("reminders").delete().eq("schedule_id", schedule_id).execute()
    for minutes_count in minutes:
        create_reminder(schedule_id, minutes_count)


def delete_reminder(reminder_id):
    result = (
        db().table("reminders")
        .delete()
        .eq("id", reminder_id)
        .execute()
    )
    return bool(_rows(result))


def get_due_reminders(user_id):
    """All unsent reminders for one user, joined with their schedule.

    Reminders without a schedule are excluded via the ``!inner`` join.
    """
    result = (
        db().table("reminders")
        .select("*, schedules!inner(*)")
        .eq("schedules.user_id", user_id)
        .eq("notification_sent", False)
        .execute()
    )
    return _rows(result)


def _user_timezone(user_id):
    """Return the user's configured IANA timezone (UTC fallback)."""
    settings = get_settings(user_id)
    tz_name = (settings or {}).get("timezone") or "UTC"
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def process_due_reminders(user_id, now_utc=None):
    """Create notifications for due, unsent reminders and mark them sent.

    A reminder is due once the reminder time (event time in the user's
    configured timezone minus ``reminder_minutes``) has arrived. Returns the
    number of notifications created. Safe to call frequently: already-sent
    reminders are skipped.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    user_tz = _user_timezone(user_id)
    created = 0
    for reminder in get_due_reminders(user_id):
        schedule = reminder.get("schedules") or {}
        if schedule.get("user_id") != user_id:
            continue

        event_date = schedule.get("event_date")
        start_time = schedule.get("start_time")
        if not event_date or not start_time:
            continue
        try:
            event_dt = datetime.combine(
                date.fromisoformat(event_date),
                datetime.strptime(start_time[:5], "%H:%M").time(),
                tzinfo=user_tz,
            )
        except (ValueError, TypeError):
            continue

        try:
            minutes = int(reminder.get("reminder_minutes") or 0)
        except (TypeError, ValueError):
            continue

        reminder_dt = event_dt - timedelta(minutes=minutes)
        if reminder_dt > now_utc:
            continue

        # Atomically claim the reminder before creating the notification so
        # concurrent workers/threads cannot double-fire the same reminder.
        claimed = (
            db().table("reminders")
            .update({"notification_sent": True})
            .eq("id", reminder.get("id"))
            .eq("notification_sent", False)
            .execute()
        )
        if not _rows(claimed):
            continue

        schedule_title = schedule.get("title") or "Schedule reminder"
        time_label = start_time[:5] if start_time else ""
        prefix = "Time to start" if minutes == 0 else "Reminder"
        message = f"{event_date} at {time_label}"
        if schedule.get("location"):
            message += f" — {schedule['location']}"
        try:
            notification = create_notification(
                user_id=user_id,
                title=f"{prefix}: {schedule_title}",
                message=message,
                schedule_id=schedule.get("id"),
            )
        except Exception:
            # Creation failed; release the claim so it is retried next pass.
            db().table("reminders").update(
                {"notification_sent": False}
            ).eq("id", reminder.get("id")).execute()
            continue
        send_push_notification(user_id, notification)
        created += 1

    return created


def process_all_due_reminders(now_utc=None):
    """Process reminders for every user; intended for a scheduled worker."""
    result = db().table("users").select("id").execute()
    return sum(
        process_due_reminders(user["id"], now_utc)
        for user in _rows(result)
    )


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

def create_notification(user_id, title, message=None, schedule_id=None):
    result = (
        db().table("notifications")
        .insert({
            "user_id": user_id,
            "schedule_id": schedule_id,
            "title": title,
            "message": message,
        })
        .execute()
    )
    return _first(result)


def list_notifications(user_id, limit=20):
    result = (
        db().table("notifications")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return _rows(result)


def count_unread_notifications(user_id):
    result = (
        db().table("notifications")
        .select("*", count="exact")
        .eq("user_id", user_id)
        .eq("is_read", False)
        .execute()
    )
    return _count(result)


def mark_notification_read(notification_id, user_id):
    result = (
        db().table("notifications")
        .update({"is_read": True})
        .eq("id", notification_id)
        .eq("user_id", user_id)
        .execute()
    )
    return bool(_rows(result))


def mark_all_notifications_read(user_id):
    result = (
        db().table("notifications")
        .update({"is_read": True})
        .eq("user_id", user_id)
        .eq("is_read", False)
        .execute()
    )
    return bool(_rows(result))


def delete_notification(notification_id, user_id):
    result = (
        db().table("notifications")
        .delete()
        .eq("id", notification_id)
        .eq("user_id", user_id)
        .execute()
    )
    return bool(_rows(result))


# ---------------------------------------------------------------------------
# Browser push subscriptions and delivery
# ---------------------------------------------------------------------------

def save_push_subscription(user_id, subscription):
    """Store the current browser's Push API subscription for this user."""
    keys = subscription.get("keys") or {}
    endpoint = subscription.get("endpoint")
    p256dh = keys.get("p256dh")
    auth = keys.get("auth")
    if not all(isinstance(value, str) and value for value in (endpoint, p256dh, auth)):
        raise ValueError("Invalid push subscription.")

    # An endpoint identifies one browser profile. Remove its old owner before
    # storing it so it cannot receive notifications for a previous account.
    db().table("push_subscriptions").delete().eq("endpoint", endpoint).execute()
    result = db().table("push_subscriptions").insert({
        "user_id": user_id,
        "endpoint": endpoint,
        "p256dh": p256dh,
        "auth": auth,
    }).execute()
    return _first(result)


def delete_push_subscription(user_id, endpoint):
    db().table("push_subscriptions").delete().eq("user_id", user_id).eq(
        "endpoint", endpoint
    ).execute()


def push_is_configured():
    return bool(webpush and Config.VAPID_PUBLIC_KEY and Config.VAPID_PRIVATE_KEY)


def send_push_notification(user_id, notification):
    """Deliver a notification to opted-in browsers. Delivery failures never
    prevent the in-app notification from being created.
    """
    if not notification or not push_is_configured():
        return
    settings = get_settings_or_default(user_id)
    if not settings.get("push_notifications"):
        return

    result = db().table("push_subscriptions").select("*").eq(
        "user_id", user_id
    ).execute()
    payload = json.dumps({
        "title": notification.get("title", "Lectra"),
        "body": notification.get("message") or "You have a new reminder.",
        "url": "/dashboard",
        "tag": "lectra-" + str(notification.get("id", "reminder")),
    })
    for subscription in _rows(result):
        endpoint = subscription["endpoint"]
        try:
            webpush(
                subscription_info={
                    "endpoint": endpoint,
                    "keys": {"p256dh": subscription["p256dh"], "auth": subscription["auth"]},
                },
                data=payload,
                vapid_private_key=Config.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": Config.VAPID_SUBJECT},
            )
        except WebPushException as exc:
            response = getattr(exc, "response", None)
            if getattr(response, "status_code", None) in (404, 410):
                delete_push_subscription(user_id, endpoint)
        except Exception:
            # Push is best-effort. Keep the durable in-app notification even
            # if a gateway is temporarily unavailable.
            continue


# ---------------------------------------------------------------------------
# User settings
# ---------------------------------------------------------------------------

DEFAULT_SETTINGS = {
    "push_notifications": True,
    "dark_mode": False,
    "default_reminder": 30,
    "timezone": "UTC",
}


def get_settings(user_id):
    result = (
        db().table("user_settings")
        .select("*")
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    return _first(result)


def get_settings_or_default(user_id):
    settings = get_settings(user_id)
    if settings is None:
        return dict(DEFAULT_SETTINGS)
    merged = dict(DEFAULT_SETTINGS)
    merged.update(settings)
    return merged


def create_settings(user_id):
    row = dict(DEFAULT_SETTINGS)
    row["user_id"] = user_id
    result = db().table("user_settings").insert(row).execute()
    return _first(result)


def update_settings(user_id, fields):
    existing = get_settings(user_id)
    if existing:
        db().table("user_settings").update(fields).eq("user_id", user_id).execute()
    else:
        row = dict(DEFAULT_SETTINGS)
        row.update(fields)
        row["user_id"] = user_id
        db().table("user_settings").insert(row).execute()
    return get_settings(user_id)


# ---------------------------------------------------------------------------
# Activity logs
# ---------------------------------------------------------------------------

def log_activity(user_id, action, description=None):
    result = (
        db().table("activity_logs")
        .insert({
            "user_id": user_id,
            "action": action,
            "description": description,
        })
        .execute()
    )
    return _first(result)


def list_activity(user_id, limit=50):
    result = (
        db().table("activity_logs")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return _rows(result)
