"""Data access layer backed by Supabase (PostgreSQL).

All persistence goes through a single lazily-initialised Supabase client so
every route reuses the same connection. Authentication is handled by Flask
(bcrypt + sessions); Supabase is used purely as the database.

The domain is project defence: an administrator posts the full defence roster
(Lv400 students, two venues) and lecturers tick the defences they want to
attend. Ticked defences produce reminders that point at the venue.
"""

import uuid
import json
import threading
import urllib.request
from datetime import date, datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import bcrypt
import httpx
from postgrest._sync import request_builder as _postgrest_request_builder
from supabase import create_client

from config import Config

ONESIGNAL_API = "https://api.onesignal.com/notifications"

_thread_local = threading.local()


def db():
    """Return the Supabase client for the current thread.

    The postgrest/httpx sync client is not thread-safe, so a client is created
    per thread instead of being shared. This keeps request threads and the
    background reminder-scheduler thread from sharing one connection pool,
    which caused ``httpx.ReadError`` on concurrent reads.
    """
    client = getattr(_thread_local, "client", None)
    if client is None:
        if not Config.SUPABASE_URL or not Config.SUPABASE_KEY:
            raise RuntimeError(
                "Supabase is not configured. Copy .env.example to .env and "
                "set SUPABASE_URL and SUPABASE_KEY."
            )
        client = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)
        _thread_local.client = client
    return client


def _reset_client():
    """Drop the cached client for the current thread so the next call rebuilds
    it. The old httpx connection pool is closed when it is garbage collected."""
    if hasattr(_thread_local, "client"):
        del _thread_local.client


_orig_send_with_retry = _postgrest_request_builder.send_with_retry


def _send_with_retry(req):
    """Retry idempotent requests once with a fresh client on transport errors.

    Stale pooled connections (e.g. after a free-tier instance sleeps) can raise
    ``httpx.TransportError`` (including ``ReadError``). Only GET/HEAD requests
    are retried to avoid duplicating writes.
    """
    try:
        return _orig_send_with_retry(req)
    except httpx.TransportError:
        method = getattr(req, "http_method", "GET")
        if method not in ("GET", "HEAD"):
            raise
        _reset_client()
        return _orig_send_with_retry(req)


_postgrest_request_builder.send_with_retry = _send_with_retry


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
                institution=None, phone=None, is_admin=False):
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
            "is_admin": bool(is_admin),
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


def count_users():
    result = db().table("users").select("id", count="exact").execute()
    return _count(result)


def count_admins():
    result = (
        db().table("users").select("id", count="exact")
        .eq("is_admin", True).execute()
    )
    return _count(result)


def list_users(limit=1000):
    """All registered users, oldest first (for the admin Users page)."""
    result = (
        db().table("users")
        .select("*")
        .order("created_at")
        .limit(limit)
        .execute()
    )
    return _rows(result)


def interest_counts():
    """Map of user_id -> number of defences the user has ticked."""
    rows = _rows(
        db().table("defence_interests").select("user_id").execute()
    )
    counts = {}
    for row in rows:
        counts[row["user_id"]] = counts.get(row["user_id"], 0) + 1
    return counts


def delete_user(user_id):
    """Delete a user account.

    Child rows (interests, notifications, settings, push subscriptions,
    activity logs) are removed by the foreign-key cascade. Scheduled OneSignal
    pushes are cancelled first so reminders don't fire after the account is
    gone. Defences created by the user keep their ``created_by`` nulled by the
    ON DELETE SET NULL reference.
    """
    if onesignal_is_configured():
        interests = _rows(
            db().table("defence_interests")
            .select("id")
            .eq("user_id", user_id)
            .execute()
        )
        for interest_id in [i["id"] for i in interests]:
            cancel_push_for_interest(interest_id)
    result = db().table("users").delete().eq("id", user_id).execute()
    return bool(_rows(result))


def set_admin(user_id, is_admin):
    """Grant or revoke the admin role for a user."""
    result = (
        db().table("users")
        .update({"is_admin": bool(is_admin), "updated_at": utc_now()})
        .eq("id", user_id)
        .execute()
    )
    return _first(result)


def ensure_admin_flag(email):
    """Promote a user whose email is on the ADMIN_EMAILS allow-list.

    Returns True if the user's admin flag changed.
    """
    if email not in Config.ADMIN_EMAILS:
        return False
    user = get_user_by_email(email)
    if user and not user.get("is_admin"):
        set_admin(user["id"], True)
        return True
    return False


# ---------------------------------------------------------------------------
# Defences (the project-defence roster)
# ---------------------------------------------------------------------------

def create_defence(data, created_by=None):
    row = {**data, "created_by": created_by or None}
    result = db().table("defences").insert(row).execute()
    return _first(result)


def bulk_create_defences(rows, created_by=None):
    """Insert many roster rows at once; returns (inserted_count, rows)."""
    payload = [{**row, "created_by": created_by or None} for row in rows]
    if not payload:
        return 0, []
    result = db().table("defences").insert(payload).execute()
    inserted = _rows(result)
    return len(inserted), inserted


def get_defence(defence_id):
    result = (
        db().table("defences")
        .select("*")
        .eq("id", defence_id)
        .maybe_single()
        .execute()
    )
    return _first(result)


def update_defence(defence_id, data):
    data = dict(data)
    data["updated_at"] = utc_now()
    result = (
        db().table("defences")
        .update(data)
        .eq("id", defence_id)
        .execute()
    )
    return _first(result)


def delete_defence(defence_id):
    result = db().table("defences").delete().eq("id", defence_id).execute()
    return bool(_rows(result))


def delete_all_defences():
    """Cancel pending pushes and delete the entire defence roster.

    ``defence_interests`` are removed by the foreign-key cascade. Returns the
    number of defences deleted.
    """
    if onesignal_is_configured():
        interests = _rows(
            db().table("defence_interests").select("id").execute()
        )
        for interest_id in [i["id"] for i in interests]:
            cancel_push_for_interest(interest_id)
    result = (
        db().table("defences")
        .delete()
        .gt("id", "00000000-0000-0000-0000-000000000000")
        .execute()
    )
    return len(_rows(result))


def count_defences(status=None):
    query = db().table("defences").select("id", count="exact")
    if status:
        query = query.eq("status", status)
    result = query.execute()
    return _count(result)


def distinct_venues():
    result = db().table("defences").select("venue").not_.is_("venue", None).execute()
    venues = []
    for row in _rows(result):
        venue = (row.get("venue") or "").strip()
        if venue and venue not in venues:
            venues.append(venue)
    return venues


def _user_timezone(user_id):
    """Return the user's configured IANA timezone (UTC fallback)."""
    settings = get_settings(user_id)
    tz_name = (settings or {}).get("timezone") or "UTC"
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def _defence_start(defence, tz):
    """A timezone-aware datetime for the defence start, or None."""
    event_date = defence.get("event_date")
    start_time = defence.get("start_time")
    if not event_date or not start_time:
        return None
    try:
        return datetime.combine(
            date.fromisoformat(event_date),
            datetime.strptime(str(start_time)[:5], "%H:%M").time(),
            tzinfo=tz,
        )
    except (ValueError, TypeError):
        return None


def _defence_end(defence, tz):
    """A timezone-aware datetime for the defence end (start when absent)."""
    start = _defence_start(defence, tz)
    if start is None:
        return None
    end_time = defence.get("end_time")
    if end_time:
        try:
            return start.replace(
                hour=int(str(end_time)[:2]), minute=int(str(end_time)[3:5])
            )
        except (ValueError, TypeError):
            pass
    return start


def defence_ended(defence, now_utc=None, tz=None):
    """True once the defence's event time has fully passed."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    tz = tz or timezone.utc
    end = _defence_end(defence, tz)
    return bool(end and end <= now_utc)


def display_status(defence, now_utc=None, tz=None):
    """The effective status shown in the UI.

    'cancelled' and 'completed' come from the stored status; a scheduled
    defence whose event time has passed is reported as 'completed' too.
    """
    status = (defence or {}).get("status") or "scheduled"
    if status == "cancelled":
        return "cancelled"
    if status == "completed":
        return "completed"
    if defence_ended(defence, now_utc, tz):
        return "completed"
    return "scheduled"


def list_defences(user_id=None, q=None, venue=None, date_from=None,
                  date_to=None, show=None, limit=1000):
    """List defences with optional filters, annotated with the user's interest.

    Returns defences ordered by date then start time, each augmented with:
    ``interest``   the user's interest row (or None) and
    ``d_status``   the effective display status.
    """
    query = db().table("defences").select("*")
    if q:
        term = q.strip().replace("%", "")
        query = query.or_(
            f"student_name.ilike.%{term}%,project_title.ilike.%{term}%,"
            f"venue.ilike.%{term}%,supervisor.ilike.%{term}%"
        )
    if venue:
        query = query.eq("venue", venue)
    if date_from:
        query = query.gte("event_date", date_from)
    if date_to:
        query = query.lte("event_date", date_to)
    result = (
        query.order("event_date")
        .order("start_time")
        .limit(limit)
        .execute()
    )
    defences = _rows(result)

    if user_id:
        interests = _rows(
            db().table("defence_interests")
            .select("*")
            .eq("user_id", user_id)
            .execute()
        )
        interest_by_defence = {i["defence_id"]: i for i in interests}
    else:
        interest_by_defence = {}

    now_utc = datetime.now(timezone.utc)
    tz = _user_timezone(user_id) if user_id else timezone.utc

    annotated = []
    for defence in defences:
        item = dict(defence)
        item["interest"] = interest_by_defence.get(defence["id"])
        item["d_status"] = display_status(item, now_utc, tz)
        annotated.append(item)

    if show == "mine":
        annotated = [d for d in annotated if d["interest"]]
    elif show == "upcoming":
        annotated = [
            d for d in annotated if d["d_status"] == "scheduled"
            and not defence_ended(d, now_utc, tz)
        ]
    return annotated


def list_upcoming_defences(limit=200):
    """Scheduled defences from today onward (for the dashboard)."""
    result = (
        db().table("defences")
        .select("*")
        .gte("event_date", date.today().isoformat())
        .eq("status", "scheduled")
        .order("event_date")
        .order("start_time")
        .limit(limit)
        .execute()
    )
    return _rows(result)


def list_today_defences():
    today = date.today().isoformat()
    result = (
        db().table("defences")
        .select("*")
        .eq("event_date", today)
        .eq("status", "scheduled")
        .order("start_time")
        .execute()
    )
    return _rows(result)


def list_all_defences(limit=1000):
    result = (
        db().table("defences")
        .select("*")
        .order("event_date")
        .order("start_time")
        .limit(limit)
        .execute()
    )
    return _rows(result)


# ---------------------------------------------------------------------------
# Defence interests (a lecturer ticking a defence to attend it)
# ---------------------------------------------------------------------------

def get_interest(user_id, defence_id):
    result = (
        db().table("defence_interests")
        .select("*")
        .eq("user_id", user_id)
        .eq("defence_id", defence_id)
        .maybe_single()
        .execute()
    )
    return _first(result)


def list_interests(user_id):
    result = (
        db().table("defence_interests")
        .select("*, defences!inner(*)")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return _rows(result)


def count_interests(user_id):
    result = (
        db().table("defence_interests")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .execute()
    )
    return _count(result)


def set_interest(user_id, defence_id, reminder_minutes):
    """Tick a defence for a lecturer with their chosen reminder lead time.

    Cancels any previously scheduled push for this interest first, then stores
    the new preference and schedules a fresh push. Returns the interest row.
    """
    defence = get_defence(defence_id)
    if not defence:
        return None
    minutes = int(reminder_minutes or 0)
    if minutes < 0:
        minutes = 0

    existing = get_interest(user_id, defence_id)
    if existing:
        cancel_push_for_interest(existing["id"])
        fields = {
            "reminder_minutes": minutes,
            "onesignal_id": None,
            "updated_at": utc_now(),
        }
        # Only re-arm a reminder that has already been delivered if the newly
        # chosen lead time is still in the future. Otherwise a lecturer who
        # changes the time after the reminder fired would be reminded again.
        tz = _user_timezone(user_id)
        start_dt = _defence_start(defence, tz)
        already_due = bool(
            start_dt
            and start_dt - timedelta(minutes=minutes)
            <= datetime.now(timezone.utc)
        )
        if not existing.get("notified") or not already_due:
            fields["notified"] = False
        result = (
            db().table("defence_interests")
            .update(fields)
            .eq("id", existing["id"])
            .execute()
        )
        interest = _first(result) or existing
    else:
        result = (
            db().table("defence_interests")
            .insert({
                "defence_id": defence_id,
                "user_id": user_id,
                "reminder_minutes": minutes,
            })
            .execute()
        )
        interest = _first(result)

    if interest:
        schedule_push_for_interest(interest["id"])
    return interest


def delete_interest(user_id, defence_id):
    interest = get_interest(user_id, defence_id)
    if not interest:
        return False
    cancel_push_for_interest(interest["id"])
    result = (
        db().table("defence_interests")
        .delete()
        .eq("id", interest["id"])
        .execute()
    )
    return bool(_rows(result))


def _interest_text(defence, minutes):
    """Notification title/message for a defence interest reminder."""
    title = ("Time to start" if minutes == 0 else "Reminder") + ": " + (
        defence.get("project_title") or "Project defence"
    )
    message = defence.get("student_name") or "Student defence"
    event_date = defence.get("event_date")
    start_time = defence.get("start_time")
    if event_date:
        message += f" · {event_date}"
    if start_time:
        message += f" at {str(start_time)[:5]}"
    if defence.get("venue"):
        message += f" — {defence['venue']}"
    return title, message


def process_due_defence_interests(user_id, now_utc=None):
    """Create in-app notifications for due defence interests and mark them sent.

    A reminder is due once the defence start time (in the lecturer's configured
    timezone) minus their chosen ``reminder_minutes`` has arrived. Defences
    that have already ended are skipped. Returns the number of notifications
    created. Idempotent thanks to the ``notified`` flag.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    tz = _user_timezone(user_id)
    interests = _rows(
        db().table("defence_interests")
        .select("*, defences!inner(*)")
        .eq("user_id", user_id)
        .eq("notified", False)
        .execute()
    )
    created = 0
    for interest in interests:
        defence = interest.get("defences") or {}
        if (defence.get("status") or "scheduled") == "cancelled":
            continue
        if defence_ended(defence, now_utc, tz):
            continue
        start_dt = _defence_start(defence, tz)
        if start_dt is None:
            continue
        try:
            minutes = int(interest.get("reminder_minutes") or 0)
        except (TypeError, ValueError):
            continue
        if start_dt - timedelta(minutes=minutes) > now_utc:
            continue

        claimed = (
            db().table("defence_interests")
            .update({"notified": True, "updated_at": utc_now()})
            .eq("id", interest.get("id"))
            .eq("notified", False)
            .execute()
        )
        if not _rows(claimed):
            continue

        title, message = _interest_text(defence, minutes)
        try:
            create_notification(
                user_id=user_id,
                title=title,
                message=message,
            )
        except Exception:
            db().table("defence_interests").update(
                {"notified": False}
            ).eq("id", interest.get("id")).execute()
            continue
        # The OneSignal push for this interest has (or is about to) fire at
        # send_after == now; clear the reference so re-ticking starts fresh.
        cancel_push_for_interest(interest.get("id"))
        created += 1

    return created


def process_all_due_defence_interests(now_utc=None):
    """Process due reminders for every lecturer with pending interests."""
    rows = _rows(
        db().table("defence_interests")
        .select("user_id")
        .eq("notified", False)
        .execute()
    )
    user_ids = {row["user_id"] for row in rows}
    return sum(
        process_due_defence_interests(user_id, now_utc)
        for user_id in user_ids
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
#   defence is ticked, so OneSignal's servers deliver them even while this app
#   is asleep (e.g. Render's free tier). Delivery is best effort: failures
#   never prevent the durable in-app notification.
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


def schedule_push_for_interest(interest_id):
    """Ask OneSignal to deliver a push for an interest at its reminder time."""
    if not onesignal_is_configured():
        return None
    interest = _first(
        db().table("defence_interests")
        .select("*, defences!inner(*)")
        .eq("id", interest_id)
        .maybe_single()
        .execute()
    )
    if not interest:
        return None
    defence = interest.get("defences") or {}
    user_id = interest.get("user_id")
    if (defence.get("status") or "scheduled") == "cancelled":
        return None
    if not get_settings_or_default(user_id).get("push_notifications"):
        return None

    tz = _user_timezone(user_id)
    start_dt = _defence_start(defence, tz)
    if start_dt is None or defence_ended(defence, datetime.now(timezone.utc), tz):
        return None
    try:
        minutes = int(interest.get("reminder_minutes") or 0)
    except (TypeError, ValueError):
        return None
    send_after = start_dt - timedelta(minutes=minutes)
    if send_after <= datetime.now(timezone.utc):
        return None

    title, message = _interest_text(defence, minutes)
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
    except (HTTPError, URLError, OSError, ValueError):
        return None
    notification_id = (response or {}).get("id") or None
    if notification_id:
        db().table("defence_interests").update(
            {"onesignal_id": notification_id}
        ).eq("id", interest_id).execute()
    return notification_id


def cancel_push_for_interest(interest_id):
    """Cancel and clear any scheduled OneSignal notification for an interest."""
    if not onesignal_is_configured():
        return
    row = _first(db().table("defence_interests").select(
        "onesignal_id"
    ).eq("id", interest_id).maybe_single().execute())
    notification_id = (row or {}).get("onesignal_id")
    if notification_id:
        try:
            _onesignal_request(
                "DELETE",
                f"{ONESIGNAL_API}/{notification_id}?app_id={Config.ONESIGNAL_APP_ID}",
            )
        except (HTTPError, URLError, OSError, ValueError):
            pass
    db().table("defence_interests").update(
        {"onesignal_id": None}
    ).eq("id", interest_id).execute()


def resync_push_for_user(user_id):
    """Cancel and re-schedule every scheduled push a user owns. Called when the
    push preference or timezone changes so existing interests pick it up."""
    if not onesignal_is_configured():
        return
    interests = _rows(
        db().table("defence_interests")
        .select("id")
        .eq("user_id", user_id)
        .execute()
    )
    ids = [i["id"] for i in interests]
    for interest_id in ids:
        cancel_push_for_interest(interest_id)
    for interest_id in ids:
        schedule_push_for_interest(interest_id)


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
