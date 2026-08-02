"""Application routes.

Server-rendered pages plus JSON API endpoints (CSRF-protected) so the app can
later be extended with a mobile client, native PWA components, etc.
"""

import secrets
from datetime import date, datetime, timedelta, timezone
from functools import wraps

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

import models

bp = Blueprint("main", __name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    user = models.get_user_by_id(user_id)
    if user is None:
        session.pop("user_id", None)
        return None
    return user


@bp.before_app_request
def load_user():
    g.user = current_user()
    g.settings = models.get_settings_or_default(g.user["id"]) if g.user else None
    if g.user:
        _check_due_reminders()


def _check_due_reminders():
    """Create notifications for due reminders, at most once every 2 minutes.

    Lightweight in-app alternative to a background worker; swapped for a
    proper scheduler (e.g. Celery) when email/push delivery is added.
    """
    now = datetime.now(timezone.utc)
    last = session.get("last_reminder_check")
    if last:
        try:
            last_dt = datetime.fromisoformat(last)
        except (TypeError, ValueError):
            last_dt = None
        if last_dt and (now - last_dt).total_seconds() < 120:
            return
    try:
        models.process_due_reminders(g.user["id"], now)
    except Exception:
        pass
    session["last_reminder_check"] = now.isoformat()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("Please sign in to continue.", "warning")
            return redirect(url_for("main.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def generate_csrf_token():
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_urlsafe(32)
    return session["_csrf_token"]


def validate_csrf():
    submitted = (
        request.form.get("_csrf_token") or request.headers.get("X-CSRF-Token")
    )
    token = session.get("_csrf_token")
    if not token or not submitted or not secrets.compare_digest(token, submitted):
        abort(400, "Invalid or missing CSRF token.")


def csrf_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        validate_csrf()
        return view(*args, **kwargs)

    return wrapped


def _schedule_payload(form):
    return {
        "title": form.get("title", "").strip(),
        "description": form.get("description", "").strip() or None,
        "category": form.get("category", "").strip() or None,
        "location": form.get("location", "").strip() or None,
        "event_date": form.get("event_date") or None,
        "start_time": form.get("start_time") or None,
        "end_time": form.get("end_time") or None,
        "repeat_type": form.get("repeat_type", "none"),
        "priority": form.get("priority", "normal"),
        "color": form.get("color", "#4F46E5"),
        "status": form.get("status", "upcoming"),
    }


def _reminder_minutes(form):
    minutes = []
    for value in form.getlist("reminder_minutes"):
        value = value.strip()
        if value.isdigit() and int(value) >= 0:
            minutes.append(int(value))
    return sorted(set(minutes))


def _default_reminder():
    settings = g.get("settings") or {}
    default = settings.get("default_reminder") or 30
    try:
        return int(default)
    except (TypeError, ValueError):
        return 30


def _resolved_reminder_minutes(form):
    """Reminder minutes the user picked, falling back to their default
    reminder setting so every schedule gets at least one reminder."""
    minutes = _reminder_minutes(form)
    if minutes:
        return minutes
    return [_default_reminder()]


def _validate_schedule(payload):
    errors = []
    if not payload.get("title"):
        errors.append("Title is required.")
    if not payload.get("event_date"):
        errors.append("Date is required.")
    if not payload.get("start_time"):
        errors.append("Start time is required.")
    if payload.get("end_time") and payload["start_time"] and \
            payload["end_time"] < payload["start_time"]:
        errors.append("End time must be after the start time.")
    return errors


def inject_globals():
    unread = 0
    if g.get("user"):
        try:
            unread = models.count_unread_notifications(g.user["id"])
        except Exception:
            unread = 0
    return {
        "csrf_token": generate_csrf_token,
        "unread_count": unread,
    }


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if g.user:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        validate_csrf()
        fullname = request.form.get("fullname", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        errors = []
        if not fullname or not email or not password:
            errors.append("Full name, email and password are required.")
        if password != confirm:
            errors.append("Passwords do not match.")
        if password and len(password) < 8:
            errors.append("Password must be at least 8 characters long.")
        if "@" not in email or "." not in email:
            errors.append("Please enter a valid email address.")
        if not errors and models.get_user_by_email(email):
            errors.append("An account with that email already exists.")

        if errors:
            for error in errors:
                flash(error, "error")
            return render_template(
                "signup.html", form=request.form, status_code=400
            )

        user = models.create_user(
            fullname=fullname,
            email=email,
            password=password,
            department=request.form.get("department", "").strip(),
            institution=request.form.get("institution", "").strip(),
            phone=request.form.get("phone", "").strip(),
        )
        models.create_settings(user["id"])
        models.create_notification(
            user_id=user["id"],
            title="Welcome to Lectra",
            message="Create your first schedule to get started.",
        )
        models.log_activity(user["id"], "signup", "Created a new account")

        session.clear()
        session["user_id"] = user["id"]
        session.permanent = True
        flash("Welcome to Lectra!", "success")
        return redirect(url_for("main.dashboard"))

    return render_template("signup.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        validate_csrf()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = models.get_user_by_email(email) if email else None
        if user and models.verify_password(password, user["password_hash"]):
            session.clear()
            session["user_id"] = user["id"]
            session.permanent = True
            models.log_activity(user["id"], "login", "Signed in")
            next_url = request.args.get("next") or request.form.get("next")
            if next_url and next_url.startswith("/") and not next_url.startswith("//"):
                return redirect(next_url)
            return redirect(url_for("main.dashboard"))

        flash("Invalid email or password.", "error")
        return render_template(
            "login.html", form=request.form, status_code=401
        )

    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
@csrf_required
def logout():
    if g.user:
        models.log_activity(g.user["id"], "logout", "Signed out")
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("main.login"))


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@bp.route("/")
def index():
    if g.user:
        return redirect(url_for("main.dashboard"))
    return redirect(url_for("main.login"))


@bp.route("/dashboard")
@login_required
def dashboard():
    user_id = g.user["id"]
    today = date.today()
    week_end = today + timedelta(days=7)

    today_events = models.list_schedules_between(
        user_id, today.isoformat(), today.isoformat()
    )
    upcoming = models.list_schedules_between(
        user_id, today.isoformat(), week_end.isoformat()
    )
    notifications = models.list_notifications(user_id, limit=5)
    activity = models.list_activity(user_id, limit=6)

    stats = {
        "today": len(today_events),
        "upcoming": models.count_schedules(user_id),
        "completed": models.count_schedules(user_id, status="completed"),
    }

    return render_template(
        "dashboard.html",
        stats=stats,
        today_schedules=today_events,
        upcoming=upcoming,
        notifications=notifications,
        activity=activity,
        today=today.isoformat(),
    )


@bp.route("/calendar")
@login_required
def calendar_page():
    return render_template("calendar.html")


@bp.route("/schedule/new", methods=["GET", "POST"])
@login_required
def create_schedule():
    default_date = request.args.get("date") or date.today().isoformat()
    default_category = request.args.get("category") or ""
    if request.method == "POST":
        validate_csrf()
        payload = _schedule_payload(request.form)
        errors = _validate_schedule(payload)
        if errors:
            for error in errors:
                flash(error, "error")
            return render_template(
                "create_schedule.html", form=request.form, schedule=None,
                default_date=default_date, default_category=default_category,
                reminder_minutes=[str(m) for m in _reminder_minutes(request.form)],
                status_code=400,
            )

        schedule = models.create_schedule(g.user["id"], payload)
        models.replace_reminders(schedule["id"], _resolved_reminder_minutes(request.form))
        models.log_activity(
            g.user["id"], "create_schedule", f"Created schedule '{schedule['title']}'"
        )
        flash("Schedule created.", "success")
        return redirect(url_for("main.calendar_page"))

    return render_template(
        "create_schedule.html", schedule=None,
        default_date=default_date, default_category=default_category,
        reminder_minutes=["0", str(_default_reminder())],
    )


@bp.route("/schedule/<schedule_id>/edit", methods=["GET", "POST"])
@login_required
def edit_schedule(schedule_id):
    schedule = models.get_schedule(schedule_id, g.user["id"])
    if not schedule:
        abort(404)

    if request.method == "POST":
        validate_csrf()
        payload = _schedule_payload(request.form)
        errors = _validate_schedule(payload)
        if errors:
            for error in errors:
                flash(error, "error")
            return render_template(
                "create_schedule.html", form=request.form, schedule=schedule,
                default_date=schedule["event_date"],
                reminder_minutes=[str(m) for m in _reminder_minutes(request.form)],
                status_code=400,
            )

        models.update_schedule(schedule_id, payload)
        models.replace_reminders(schedule_id, _reminder_minutes(request.form))
        models.log_activity(
            g.user["id"], "update_schedule", f"Updated schedule '{schedule['title']}'"
        )
        flash("Schedule updated.", "success")
        return redirect(url_for("main.calendar_page"))

    reminder_minutes = [
        str(r["reminder_minutes"]) for r in models.list_reminders(schedule_id)
    ]
    return render_template(
        "create_schedule.html", schedule=schedule,
        default_date=schedule["event_date"], reminder_minutes=reminder_minutes,
    )


@bp.route("/history")
@login_required
def history():
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()
    category = request.args.get("category", "").strip()
    schedules = models.search_schedules(
        g.user["id"], q=q or None, status=status or None,
        category=category or None
    )
    return render_template(
        "history.html", schedules=schedules, q=q, status=status, category=category
    )


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        validate_csrf()
        action = request.form.get("action")

        if action == "update_profile":
            models.update_user(
                g.user["id"],
                fullname=request.form.get("fullname", "").strip(),
                department=request.form.get("department", "").strip(),
                institution=request.form.get("institution", "").strip(),
                phone=request.form.get("phone", "").strip(),
            )
            models.log_activity(g.user["id"], "update_profile", "Updated profile")
            flash("Profile updated.", "success")

        elif action == "update_settings":
            models.update_settings(g.user["id"], {
                "push_notifications": request.form.get("push_notifications") == "on",
                "dark_mode": request.form.get("dark_mode") == "on",
                "default_reminder": int(
                    request.form.get("default_reminder") or 30
                ),
                "timezone": request.form.get("timezone") or "UTC",
            })
            models.log_activity(g.user["id"], "update_settings", "Updated settings")
            flash("Settings updated.", "success")

        return redirect(url_for("main.profile"))

    settings = models.get_settings_or_default(g.user["id"])
    return render_template("profile.html", settings=settings)


# ---------------------------------------------------------------------------
# JSON API — Schedules
# ---------------------------------------------------------------------------

@bp.route("/api/schedules", methods=["GET"])
@login_required
def api_list_schedules():
    start = request.args.get("start")
    end = request.args.get("end")
    if start and end:
        rows = models.list_schedules_between(g.user["id"], start, end)
    else:
        rows = models.list_schedules(g.user["id"])
    return jsonify({"data": rows})


@bp.route("/api/schedules", methods=["POST"])
@login_required
@csrf_required
def api_create_schedule():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"error": "Invalid payload."}), 400

    reminder_minutes = payload.get("reminder_minutes") or []
    if isinstance(reminder_minutes, (int, str)):
        reminder_minutes = [reminder_minutes]

    data = {
        "title": payload.get("title", "").strip(),
        "description": payload.get("description", "").strip() or None,
        "category": payload.get("category", "").strip() or None,
        "location": payload.get("location", "").strip() or None,
        "event_date": payload.get("event_date") or None,
        "start_time": payload.get("start_time") or None,
        "end_time": payload.get("end_time") or None,
        "repeat_type": payload.get("repeat_type", "none"),
        "priority": payload.get("priority", "normal"),
        "color": payload.get("color") or "#4F46E5",
        "status": payload.get("status", "upcoming"),
    }

    errors = _validate_schedule(data)
    if errors:
        return jsonify({"error": " ".join(errors)}), 400

    minutes = []
    for value in reminder_minutes:
        try:
            value = int(value)
        except (TypeError, ValueError):
            continue
        if value >= 0:
            minutes.append(value)
    minutes = sorted(set(minutes)) or [_default_reminder()]

    schedule = models.create_schedule(g.user["id"], data)
    models.replace_reminders(schedule["id"], minutes)
    models.log_activity(
        g.user["id"], "create_schedule", f"Created schedule '{schedule['title']}'"
    )
    return jsonify({"data": schedule}), 201


@bp.route("/api/schedules/<schedule_id>", methods=["GET"])
@login_required
def api_get_schedule(schedule_id):
    schedule = models.get_schedule(schedule_id, g.user["id"])
    if not schedule:
        return jsonify({"error": "Schedule not found."}), 404
    return jsonify(schedule)


@bp.route("/api/schedules/<schedule_id>", methods=["DELETE"])
@login_required
@csrf_required
def api_delete_schedule(schedule_id):
    schedule = models.get_schedule(schedule_id, g.user["id"])
    if not schedule:
        return jsonify({"error": "Schedule not found."}), 404
    models.delete_schedule(schedule_id, g.user["id"])
    models.log_activity(
        g.user["id"], "delete_schedule", f"Deleted schedule '{schedule['title']}'"
    )
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# JSON API — Reminders
# ---------------------------------------------------------------------------

@bp.route("/api/schedules/<schedule_id>/reminders", methods=["POST"])
@login_required
@csrf_required
def api_add_reminder(schedule_id):
    schedule = models.get_schedule(schedule_id, g.user["id"])
    if not schedule:
        return jsonify({"error": "Schedule not found."}), 404
    payload = request.get_json(silent=True) or {}
    try:
        minutes = int(payload.get("reminder_minutes", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "reminder_minutes must be an integer."}), 400
    if minutes < 0:
        return jsonify({"error": "reminder_minutes must be 0 or greater."}), 400
    reminder = models.create_reminder(schedule_id, minutes)
    return jsonify({"data": reminder}), 201


@bp.route("/api/reminders/<reminder_id>", methods=["DELETE"])
@login_required
@csrf_required
def api_delete_reminder(reminder_id):
    deleted = models.delete_reminder(reminder_id)
    if not deleted:
        return jsonify({"error": "Reminder not found."}), 404
    return jsonify({"ok": True})


@bp.route("/notifications")
@login_required
def notifications_page():
    notifications = models.list_notifications(g.user["id"], limit=100)
    return render_template("notifications.html", notifications=notifications)


# ---------------------------------------------------------------------------
# JSON API — Notifications
# ---------------------------------------------------------------------------

@bp.route("/api/notifications", methods=["GET"])
@login_required
def api_list_notifications():
    rows = models.list_notifications(g.user["id"], limit=30)
    return jsonify({"data": rows})


@bp.route("/api/notifications/unread-count", methods=["GET"])
@login_required
def api_unread_count():
    return jsonify({"count": models.count_unread_notifications(g.user["id"])})


@bp.route("/api/notifications/<notification_id>/read", methods=["POST"])
@login_required
@csrf_required
def api_mark_notification_read(notification_id):
    ok = models.mark_notification_read(notification_id, g.user["id"])
    if not ok:
        return jsonify({"error": "Notification not found."}), 404
    return jsonify({"ok": True})


@bp.route("/api/notifications/<notification_id>", methods=["DELETE"])
@login_required
@csrf_required
def api_delete_notification(notification_id):
    deleted = models.delete_notification(notification_id, g.user["id"])
    if not deleted:
        return jsonify({"error": "Notification not found."}), 404
    return jsonify({"ok": True})


@bp.route("/api/notifications/read-all", methods=["POST"])
@login_required
@csrf_required
def api_mark_all_notifications_read():
    models.mark_all_notifications_read(g.user["id"])
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# JSON API — Browser push
# ---------------------------------------------------------------------------

@bp.route("/api/push/public-key", methods=["GET"])
@login_required
def api_push_public_key():
    from config import Config
    reason = models.push_config_error()
    if reason:
        return jsonify({"error": "Browser push is not configured: " + reason}), 503
    return jsonify({"publicKey": Config.VAPID_PUBLIC_KEY})


@bp.route("/api/push/subscription", methods=["POST", "DELETE"])
@login_required
@csrf_required
def api_push_subscription():
    if request.method == "DELETE":
        payload = request.get_json(silent=True) or {}
        endpoint = payload.get("endpoint")
        if isinstance(endpoint, str) and endpoint:
            models.delete_push_subscription(g.user["id"], endpoint)
        return jsonify({"ok": True})

    try:
        subscription = request.get_json(silent=True) or {}
        models.save_push_subscription(g.user["id"], subscription)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True}), 201


# ---------------------------------------------------------------------------
# JSON API — Settings
# ---------------------------------------------------------------------------

@bp.route("/api/settings", methods=["PUT"])
@login_required
@csrf_required
def api_update_settings():
    payload = request.get_json(silent=True) or {}
    allowed = {"push_notifications", "dark_mode", "default_reminder", "timezone"}
    fields = {k: v for k, v in payload.items() if k in allowed}

    if "dark_mode" in fields:
        fields["dark_mode"] = bool(fields["dark_mode"])
    if "push_notifications" in fields:
        fields["push_notifications"] = bool(fields["push_notifications"])
    if "default_reminder" in fields:
        try:
            fields["default_reminder"] = int(fields["default_reminder"])
        except (TypeError, ValueError):
            fields.pop("default_reminder")

    if not fields:
        return jsonify({"error": "No valid settings provided."}), 400

    models.update_settings(g.user["id"], fields)
    models.log_activity(g.user["id"], "update_settings", "Updated settings")
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@bp.app_errorhandler(404)
def not_found(_error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Not found."}), 404
    return render_template("error.html", code=404,
                           message="The page you are looking for does not exist."), 404


@bp.app_errorhandler(403)
def forbidden(_error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Forbidden."}), 403
    return render_template("error.html", code=403,
                           message="You do not have permission to view this page."), 403


@bp.app_errorhandler(500)
def server_error(error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Internal server error."}), 500
    return render_template("error.html", code=500,
                           message="Something went wrong on our end."), 500
