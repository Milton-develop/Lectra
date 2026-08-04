"""Application routes.

Server-rendered pages plus JSON API endpoints (CSRF-protected). The app is
project-defence focused: an administrator posts the defence roster and
lecturers tick the defences they want to attend.
"""

import json
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
import roster as roster_lib
from config import Config

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
    g.user_is_admin = bool(g.user and g.user.get("is_admin"))
    if g.user:
        _touch_last_seen(g.user["id"])
        _check_due_reminders()


def _touch_last_seen(user_id):
    """Write last_seen_at at most once every 5 minutes per user, so the admin
    Users page shows roughly who is active without a write per request."""
    now = datetime.now(timezone.utc)
    last = session.get("last_seen_written")
    if last:
        try:
            last_dt = datetime.fromisoformat(last)
        except (TypeError, ValueError):
            last_dt = None
        if last_dt and (now - last_dt).total_seconds() < 300:
            return
    try:
        models.touch_last_seen(user_id)
    except Exception:
        return
    session["last_seen_written"] = now.isoformat()


def _check_due_reminders():
    """Create notifications for due defence reminders, at most once every 2
    minutes. Lightweight in-app alternative to a background worker."""
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
        models.process_due_defence_interests(g.user["id"], now)
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


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("Please sign in to continue.", "warning")
            return redirect(url_for("main.login", next=request.path))
        if not g.user_is_admin:
            abort(403)
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


def _default_reminder():
    settings = g.get("settings") or {}
    default = settings.get("default_reminder")
    if default is None or default == "":
        return 30
    try:
        return int(default)
    except (TypeError, ValueError):
        return 30


def _defence_payload(form):
    return {
        "student_name": form.get("student_name", "").strip(),
        "project_title": form.get("project_title", "").strip(),
        "venue": form.get("venue", "").strip() or None,
        "supervisor": form.get("supervisor", "").strip() or None,
        "event_date": form.get("event_date") or None,
        "start_time": form.get("start_time") or None,
        "end_time": form.get("end_time") or None,
        "status": form.get("status", "scheduled"),
    }


def _validate_defence(payload):
    errors = []
    if not payload.get("student_name"):
        errors.append("Student name is required.")
    if not payload.get("project_title"):
        errors.append("Project title is required.")
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
        "onesignal_app_id": Config.ONESIGNAL_APP_ID,
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

        # The very first account becomes admin; so do emails on the
        # ADMIN_EMAILS allow-list.
        is_admin = models.count_users() == 0 or email in Config.ADMIN_EMAILS
        user = models.create_user(
            fullname=fullname,
            email=email,
            password=password,
            department=request.form.get("department", "").strip(),
            institution=request.form.get("institution", "").strip(),
            phone=request.form.get("phone", "").strip(),
            is_admin=is_admin,
        )
        models.create_settings(user["id"])
        models.create_notification(
            user_id=user["id"],
            title="Welcome to Lectra",
            message=(
                "The project defence roster is here. Tick the defences you "
                "want to attend to get reminded before they start."
            ),
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
            models.ensure_admin_flag(email)
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
    today = date.today().isoformat()
    week_end = (date.today() + timedelta(days=7)).isoformat()

    today_defences = models.list_defences(
        user_id, date_from=today, date_to=today
    )
    my_upcoming = models.list_defences(
        user_id, date_from=today, date_to=week_end, show="mine"
    )
    upcoming = models.list_defences(user_id, date_from=today, show="upcoming")

    stats = {
        "today": len(today_defences),
        "mine": models.count_interests(user_id),
        "upcoming": len(upcoming),
    }

    return render_template(
        "dashboard.html",
        stats=stats,
        today_defences=today_defences,
        my_upcoming=my_upcoming,
        today=today,
    )


@bp.route("/defences")
@login_required
def defences():
    q = request.args.get("q", "").strip()
    venue = request.args.get("venue", "").strip()
    show = request.args.get("show", "all").strip() or "all"
    if show not in ("all", "mine", "upcoming"):
        show = "all"

    rows = models.list_defences(
        g.user["id"],
        q=q or None,
        venue=venue or None,
        show=show,
    )
    return render_template(
        "defences.html",
        defences=rows,
        venues=models.distinct_venues(),
        q=q,
        venue=venue,
        show=show,
    )


@bp.route("/help")
@login_required
def help_page():
    return render_template("help.html")


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
            models.resync_push_for_user(g.user["id"])
            models.log_activity(g.user["id"], "update_settings", "Updated settings")
            flash("Settings updated.", "success")

        return redirect(url_for("main.profile"))

    settings = models.get_settings_or_default(g.user["id"])
    return render_template("profile.html", settings=settings)


@bp.route("/notifications")
@login_required
def notifications_page():
    notifications = models.list_notifications(g.user["id"], limit=100)
    return render_template("notifications.html", notifications=notifications)


# ---------------------------------------------------------------------------
# Admin — defence roster
# ---------------------------------------------------------------------------

def _preview_rows():
    """Parsed roster rows persisted for the confirm step, or None."""
    raw = request.form.get("roster_json")
    if not raw:
        return None
    try:
        rows = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return rows if isinstance(rows, list) else None


@bp.route("/admin/roster", methods=["GET", "POST"])
@admin_required
def admin_roster():
    q = request.args.get("q", "").strip()
    venue = request.args.get("venue", "").strip()

    preview = None
    errors = []
    warnings = []
    summary = None

    if request.method == "POST":
        validate_csrf()
        default_venue = request.form.get("default_venue", "").strip() or None
        file = request.files.get("roster")
        if not file or not file.filename:
            errors.append("Choose a CSV, TSV, XLSX or Word (.docx) file to upload.")
        else:
            content = file.read()
            try:
                parsed = roster_lib.parse_roster(
                    file.filename, content, default_venue=default_venue
                )
            except ImportError:
                errors.append(
                    "Reading .xlsx files needs the 'openpyxl' package. "
                    "Install it (pip install openpyxl) or upload CSV instead."
                )
                parsed = None
            if parsed is not None:
                rows = parsed["rows"]
                errors = parsed["errors"]
                warnings = parsed["warnings"]
                summary = parsed["summary"]
                if rows and not errors:
                    preview = rows

    all_defences = models.list_all_defences(limit=1000)
    if q or venue:
        all_defences = models.list_defences(q=q or None, venue=venue or None)

    return render_template(
        "admin_roster.html",
        defences=all_defences,
        venues=models.distinct_venues(),
        preview=preview,
        errors=errors,
        warnings=warnings,
        summary=summary,
        q=q,
        venue=venue,
        default_venue=request.form.get("default_venue", "").strip() if request.method == "POST" else "",
    )


@bp.route("/admin/roster/confirm", methods=["POST"])
@admin_required
@csrf_required
def admin_roster_confirm():
    rows = _preview_rows()
    if not rows:
        flash("Nothing to import — upload the roster again.", "error")
        return redirect(url_for("main.admin_roster"))

    cleaned = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        defence = {
            "student_name": str(row.get("student_name") or "").strip(),
            "project_title": str(row.get("project_title") or "").strip(),
            "venue": str(row.get("venue") or "").strip() or None,
            "supervisor": str(row.get("supervisor") or "").strip() or None,
            "event_date": row.get("event_date"),
            "start_time": row.get("start_time"),
            "end_time": row.get("end_time") or None,
            "status": "scheduled",
        }
        if defence["student_name"] and defence["project_title"] and \
                defence["event_date"] and defence["start_time"]:
            cleaned.append(defence)

    if not cleaned:
        flash("The roster contained no importable rows.", "error")
        return redirect(url_for("main.admin_roster"))

    inserted, _ = models.bulk_create_defences(cleaned, g.user["id"])
    models.log_activity(
        g.user["id"], "import_roster", f"Imported {inserted} defence(s) from a roster"
    )
    flash(f"{inserted} defence(s) imported.", "success")
    return redirect(url_for("main.admin_roster"))


@bp.route("/admin/defences/new", methods=["GET", "POST"])
@admin_required
def defence_new():
    if request.method == "POST":
        validate_csrf()
        payload = _defence_payload(request.form)
        errors = _validate_defence(payload)
        if errors:
            for error in errors:
                flash(error, "error")
            return render_template(
                "defence_form.html", form=request.form, defence=None,
                venues=models.distinct_venues(), status_code=400,
            )
        models.create_defence(payload, g.user["id"])
        models.log_activity(
            g.user["id"], "create_defence",
            f"Added defence '{payload['project_title']}'"
        )
        flash("Defence added.", "success")
        return redirect(url_for("main.admin_roster"))

    return render_template(
        "defence_form.html", defence=None, venues=models.distinct_venues()
    )


@bp.route("/admin/defences/<defence_id>/edit", methods=["GET", "POST"])
@admin_required
def defence_edit(defence_id):
    defence = models.get_defence(defence_id)
    if not defence:
        abort(404)

    if request.method == "POST":
        validate_csrf()
        payload = _defence_payload(request.form)
        errors = _validate_defence(payload)
        if errors:
            for error in errors:
                flash(error, "error")
            return render_template(
                "defence_form.html", form=request.form, defence=defence,
                venues=models.distinct_venues(), status_code=400,
            )
        models.update_defence(defence_id, payload)
        models.log_activity(
            g.user["id"], "update_defence",
            f"Updated defence '{defence['project_title']}'"
        )
        flash("Defence updated.", "success")
        return redirect(url_for("main.admin_roster"))

    return render_template(
        "defence_form.html", defence=defence, venues=models.distinct_venues()
    )


@bp.route("/admin/defences/<defence_id>/delete", methods=["POST"])
@admin_required
@csrf_required
def defence_delete(defence_id):
    defence = models.get_defence(defence_id)
    if not defence:
        abort(404)
    models.delete_defence(defence_id)
    models.log_activity(
        g.user["id"], "delete_defence",
        f"Deleted defence '{defence['project_title']}'"
    )
    flash("Defence deleted.", "success")
    return redirect(url_for("main.admin_roster"))


@bp.route("/admin/defences/<defence_id>/cancel", methods=["POST"])
@admin_required
@csrf_required
def defence_cancel(defence_id):
    defence = models.get_defence(defence_id)
    if not defence:
        abort(404)
    new_status = "scheduled" if defence.get("status") == "cancelled" else "cancelled"
    models.update_defence(defence_id, {"status": new_status})
    models.log_activity(
        g.user["id"], "cancel_defence",
        f"Marked defence '{defence['project_title']}' as {new_status}"
    )
    flash(f"Defence marked as {new_status}.", "success")
    return redirect(url_for("main.admin_roster"))


@bp.route("/admin/defences/clear", methods=["POST"])
@admin_required
@csrf_required
def admin_defences_clear():
    count = models.delete_all_defences()
    models.log_activity(
        g.user["id"], "clear_roster",
        f"Cleared the entire defence roster ({count} defence(s))"
    )
    flash(f"Roster cleared — {count} defence(s) removed.", "success")
    return redirect(url_for("main.admin_roster"))


# ---------------------------------------------------------------------------
# Admin — users
# ---------------------------------------------------------------------------

def _last_seen_dt(user):
    """Parse a user's last_seen_at timestamp, or None."""
    raw = user.get("last_seen_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _relative_time(dt):
    """Short human-readable 'time ago' for a datetime, or 'Never'."""
    if not dt:
        return "Never"
    delta = datetime.now(timezone.utc) - dt
    if delta.total_seconds() < 60:
        return "Just now"
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return f"{minutes} min ago"
    hours = int(minutes // 60)
    if hours < 24:
        return f"{hours} hr ago"
    days = int(hours // 24)
    if days == 1:
        return "Yesterday"
    return f"{days} days ago"


@bp.route("/admin/users")
@admin_required
def admin_users():
    q = request.args.get("q", "").strip()
    users = models.list_users()
    interest_counts = models.interest_counts()

    active_since = datetime.now(timezone.utc) - timedelta(days=7)
    for user in users:
        seen = _last_seen_dt(user)
        user["last_seen_dt"] = seen
        user["last_seen_label"] = _relative_time(seen)
        user["is_active"] = bool(seen and seen >= active_since)
        user["interest_count"] = interest_counts.get(user["id"], 0)

    if q:
        term = q.lower()
        users = [
            u for u in users
            if term in u["fullname"].lower()
            or term in u["email"].lower()
            or term in (u.get("department") or "").lower()
            or term in (u.get("institution") or "").lower()
        ]

    admins = [u for u in users if u.get("is_admin")]
    stats = {
        "total": len(users) if q else models.count_users(),
        "admins": len(admins),
        "active": sum(1 for u in users if u.get("is_active")),
        "interests": sum(u["interest_count"] for u in users),
    }
    return render_template(
        "admin_users.html",
        users=users,
        stats=stats,
        q=q,
        current_user_id=g.user["id"],
    )


@bp.route("/admin/users/<user_id>/delete", methods=["POST"])
@admin_required
@csrf_required
def admin_user_delete(user_id):
    if user_id == g.user["id"]:
        flash("You cannot delete your own account.", "error")
        return redirect(url_for("main.admin_users"))
    user = models.get_user_by_id(user_id)
    if not user:
        abort(404)
    if user.get("is_admin") and models.count_admins() <= 1:
        flash("You cannot delete the last admin account.", "error")
        return redirect(url_for("main.admin_users"))
    models.delete_user(user_id)
    models.log_activity(
        g.user["id"], "delete_user",
        f"Deleted account for {user['fullname']} ({user['email']})"
    )
    flash(f"Deleted {user['fullname']}'s account.", "success")
    return redirect(url_for("main.admin_users"))


@bp.route("/admin/users/<user_id>/admin", methods=["POST"])
@admin_required
@csrf_required
def admin_user_toggle(user_id):
    if user_id == g.user["id"]:
        flash("Use 'Transfer admin' to give your admin title away.", "error")
        return redirect(url_for("main.admin_users"))
    user = models.get_user_by_id(user_id)
    if not user:
        abort(404)
    if user.get("is_admin"):
        if models.count_admins() <= 1:
            flash("You cannot remove the last admin.", "error")
            return redirect(url_for("main.admin_users"))
        models.set_admin(user_id, False)
        models.log_activity(
            g.user["id"], "revoke_admin",
            f"Removed admin title from {user['fullname']} ({user['email']})"
        )
        flash(f"Removed admin from {user['fullname']}.", "success")
    else:
        models.set_admin(user_id, True)
        models.log_activity(
            g.user["id"], "grant_admin",
            f"Granted admin title to {user['fullname']} ({user['email']})"
        )
        flash(f"{user['fullname']} is now an admin.", "success")
    return redirect(url_for("main.admin_users"))


@bp.route("/admin/users/<user_id>/transfer-admin", methods=["POST"])
@admin_required
@csrf_required
def admin_user_transfer(user_id):
    if user_id == g.user["id"]:
        flash("You already hold the admin title.", "error")
        return redirect(url_for("main.admin_users"))
    user = models.get_user_by_id(user_id)
    if not user:
        abort(404)
    models.set_admin(user_id, True)
    models.set_admin(g.user["id"], False)
    models.log_activity(
        g.user["id"], "transfer_admin",
        f"Transferred the admin title to {user['fullname']} ({user['email']})"
    )
    flash(
        f"Admin title transferred to {user['fullname']}. "
        "You are now a regular user.",
        "success",
    )
    return redirect(url_for("main.dashboard"))


# ---------------------------------------------------------------------------
# JSON API — Defences
# ---------------------------------------------------------------------------

@bp.route("/api/defences", methods=["GET"])
@login_required
def api_list_defences():
    q = request.args.get("q", "").strip()
    venue = request.args.get("venue", "").strip()
    show = request.args.get("show", "all").strip()
    if show not in ("all", "mine", "upcoming"):
        show = "all"
    rows = models.list_defences(
        g.user["id"],
        q=q or None,
        venue=venue or None,
        show=show,
    )
    return jsonify({"data": rows})


@bp.route("/api/defences/<defence_id>/interest", methods=["PUT"])
@login_required
@csrf_required
def api_set_interest(defence_id):
    if not models.get_defence(defence_id):
        return jsonify({"error": "Defence not found."}), 404
    payload = request.get_json(silent=True) or {}
    minutes = payload.get("reminder_minutes")
    if minutes is None or minutes == "":
        minutes = _default_reminder()
    else:
        try:
            minutes = int(minutes)
        except (TypeError, ValueError):
            minutes = _default_reminder()
    if minutes < 0:
        minutes = 0
    interest = models.set_interest(g.user["id"], defence_id, minutes)
    if not interest:
        return jsonify({"error": "Could not save your interest."}), 400
    return jsonify({"ok": True, "data": interest})


@bp.route("/api/defences/<defence_id>/interest", methods=["DELETE"])
@login_required
@csrf_required
def api_delete_interest(defence_id):
    ok = models.delete_interest(g.user["id"], defence_id)
    if not ok:
        return jsonify({"error": "Interest not found."}), 404
    return jsonify({"ok": True})


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
    if "push_notifications" in fields or "timezone" in fields:
        models.resync_push_for_user(g.user["id"])
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
