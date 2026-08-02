"""Data access layer backed by Supabase (PostgreSQL).

All persistence goes through a single lazily-initialised Supabase client so
every route reuses the same connection. Authentication is handled by Flask
(bcrypt + sessions); Supabase is used purely as the database.
"""

import uuid
import json
import logging
import urllib.request
from datetime import date, datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import bcrypt
from supabase import create_client

from config import Config

ONESIGNAL_API = "https://api.onesignal.com/notifications"

logger = logging.getLogger(__name__)

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


def get_reminder(reminder_id):
    result = (
        db().table("reminders")
        .select("*")
        .eq("id", reminder_id)
        .maybe_single()
        .execute()
    )
    return _first(result)


def replace_reminders(schedule_id, minutes):
    """Set the reminder set for a schedule to ``minutes``.

    New reminders are created before old ones are removed so a failure
    (e.g. a database constraint) leaves the previous state intact instead
    of wiping the existing reminders and then crashing.
    """
    desired = {int(m) for m in minutes}
    existing = list_reminders(schedule_id)
    existing_by_minutes = {r["reminder_minutes"]: r["id"] for r in existing}
    for minutes_count in desired - set(existing_by_minutes):
        create_reminder(schedule_id, minutes_count)
    for reminder in existing:
        if reminder["reminder_minutes"] not in desired:
            delete_reminder(reminder["id"])


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
# Browser push via OneSignal (scheduled delivery)
#   Pushes are scheduled against OneSignal's API with ``send_after`` when a
#   schedule's reminders are saved, so OneSignal's servers deliver them even
#   while this app is asleep (e.g. Render's free tier). Delivery is best
#   effort: failures never prevent the durable in-app notification.
# ---------------------------------------------------------------------------

def onesignal_config_error():
    """Return a human-readable reason OneSignal is unavailable, or None if it
    is fully configured."""
    if not Config.ONESIGNAL_APP_ID:
        return "ONESIGNAL_APP_ID is not set on the server."
    if not Config.ONESIGNAL_REST_API_KEY:
        return "ONESIGNAL_REST_API_KEY is not set on the server."
    return None


def onesignal_is_configured():
    return onesignal_config_error() is None


def _onesignal_request(method, url, payload=None):
    """Call the OneSignal REST API and return the parsed JSON response."""
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url, data=body, headers={
            "Authorization": "Key " + Config.ONESIGNAL_REST_API_KEY,
            "Content-Type": "application/json",
        }, method=method,
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def _reminder_send_after(schedule, reminder, user_tz):
    """The timezone-aware datetime at which a reminder's push should fire."""
    event_date = schedule.get("event_date")
    start_time = schedule.get("start_time")
    if not event_date or not start_time:
        return None
    try:
        event_dt = datetime.combine(
            date.fromisoformat(event_date),
            datetime.strptime(start_time[:5], "%H:%M").time(),
            tzinfo=user_tz,
        )
    except (ValueError, TypeError):
        return None
    try:
        minutes = int(reminder.get("reminder_minutes") or 0)
    except (TypeError, ValueError):
        return None
    return event_dt - timedelta(minutes=minutes)


def _reminder_push_text(schedule, minutes):
    title = ("Time to start" if minutes == 0 else "Reminder") + ": " + (
        schedule.get("title") or "Schedule reminder"
    )
    message = f"{schedule['event_date']} at {str(schedule['start_time'])[:5]}"
    if schedule.get("location"):
        message += f" — {schedule['location']}"
    return title, message


def schedule_push_for_reminder(reminder_id, user_id, title, message, send_after):
    """Ask OneSignal to deliver a push at ``send_after`` and record the created
    notification id on the reminder so it can be cancelled later."""
    if not onesignal_is_configured():
        return None
    payload = {
        "app_id": Config.ONESIGNAL_APP_ID,
        "contents": {"en": message},
        "headings": {"en": title},
        "include_aliases": {"external_id": [str(user_id)]},
        "target_channel": "push",
        "send_after": send_after.isoformat(),
        "priority": "high",
        "ttl": 86400,
    }
    try:
        response = _onesignal_request("POST", ONESIGNAL_API, payload)
    except (HTTPError, URLError, OSError, ValueError) as error:
        # Do not prevent saving a schedule when the push provider is down, but
        # make the failure visible. Previously this was swallowed, leaving a
        # reminder with no OneSignal id and no way to diagnose why it did not
        # reach a closed browser.
        logger.warning("Unable to schedule OneSignal push for reminder %s: %s", reminder_id, error)
        return None
    notification_id = (response or {}).get("id") or None
    if notification_id:
        db().table("reminders").update(
            {"onesignal_id": notification_id}
        ).eq("id", reminder_id).execute()
    else:
        logger.warning(
            "OneSignal did not create a push for reminder %s; the user has no "
            "active push subscription or the API rejected the target: %s",
            reminder_id, response,
        )
    return notification_id


def cancel_push_for_reminder(reminder_id):
    """Cancel and clear any scheduled OneSignal notification for a reminder."""
    if not onesignal_is_configured():
        return
    row = _first(db().table("reminders").select(
        "onesignal_id"
    ).eq("id", reminder_id).maybe_single().execute())
    notification_id = (row or {}).get("onesignal_id")
    if notification_id:
        try:
            _onesignal_request(
                "DELETE",
                f"{ONESIGNAL_API}/{notification_id}?app_id={Config.ONESIGNAL_APP_ID}",
            )
        except (HTTPError, URLError, OSError, ValueError):
            pass
    db().table("reminders").update(
        {"onesignal_id": None}
    ).eq("id", reminder_id).execute()


def cancel_push_for_schedule(schedule_id):
    """Cancel scheduled OneSignal notifications for every reminder on a
    schedule. Call before changing a schedule's reminders, while the old
    reminder rows still exist."""
    for reminder in list_reminders(schedule_id):
        cancel_push_for_reminder(reminder["id"])


def schedule_push_for_schedule(schedule_id):
    """Schedule future OneSignal pushes for a schedule's unscheduled reminders.

    Only reminders that do not already carry a OneSignal notification id are
    scheduled, so the call is safe to repeat after adding a single reminder.
    """
    if not onesignal_is_configured():
        return
    schedule = get_schedule(schedule_id)
    if not schedule:
        return
    if not get_settings_or_default(schedule.get("user_id")).get("push_notifications"):
        return
    if schedule.get("status") not in ("upcoming", "rescheduled"):
        return
    user_tz = _user_timezone(schedule["user_id"])
    now_utc = datetime.now(timezone.utc)
    for reminder in list_reminders(schedule_id):
        if reminder.get("onesignal_id"):
            continue
        send_after = _reminder_send_after(schedule, reminder, user_tz)
        if not send_after or send_after <= now_utc:
            continue
        title, message = _reminder_push_text(schedule, reminder["reminder_minutes"])
        schedule_push_for_reminder(
            reminder["id"], schedule["user_id"], title, message, send_after
        )


def resync_push_for_user(user_id):
    """Cancel and re-schedule every scheduled push a user owns. Called when the
    push preference or timezone changes so existing reminders pick it up."""
    if not onesignal_is_configured():
        return
    schedules = list_schedules(user_id)
    for schedule in schedules:
        cancel_push_for_schedule(schedule["id"])
    for schedule in schedules:
        schedule_push_for_schedule(schedule["id"])


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
