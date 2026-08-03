# Lectra — Project Defence Attendance

Lectra is a project defence attendance system for Lv400 students. An admin
uploads the full defence roster (two venues), lecturers browse the schedule and
"tick" the defences they plan to attend, and get reminded — in-app and by
browser push — before each selected defence starts, complete with the venue.
Built with Flask + Supabase (PostgreSQL).

## Features

- **Secure accounts** — registration, login/logout with `bcrypt` password
  hashing and signed Flask sessions (no Supabase Auth required).
- **Admin roles** — the first account to sign up becomes an admin. Additional
  admins can be promoted via the comma-separated `ADMIN_EMAILS` env var.
- **Roster upload** — admins type the venue the file covers (applied to every
  row) and upload the whole defence roster as CSV, TSV, XLSX or Word (`.docx`).
  Column names are flexible, so documents like
  `Name / Topics / Session/Date / Time Schedule` import directly
  (a start–end range such as "10:00 AM - 10:45 AM" in one cell is split
  automatically). Rows are validated, unreadable ones are reported, non-entry
  rows are ignored, and a preview is shown before the bulk import.
- **Defence management** — admins can also add, edit, cancel or delete
  individual defences, and mark them completed (done automatically once their
  end time passes). A **Danger zone** on the roster page clears the entire
  roster at once (undoes a mistaken upload, cancelling everyone's pending
  reminders).
- **Interest ticking** — lecturers browse the roster (filter by venue, date and
  "mine") and tick the defences they will attend. Each tick stores their chosen
  reminder lead time.
- **Smart reminders** — reminders fire at each lecturer's chosen lead time
  (at start, 10, 15, 30, 60 or 120 minutes before) in their own timezone, and
  include the venue so they know where to head.
- **Browser push** — scheduled via OneSignal's `send_after`, so pushes arrive
  on time even while this app is asleep (e.g. Render's free tier spinning down
  after 15 minutes of inactivity). Re-ticking or unticking a defence cancels
  and reschedules its pending push.
- **Notifications** — durable in-app notification feed with unread badges.
- **Profile & settings** — user profile, dark mode, push notification
  preference, default reminder lead time and timezone.
- **Activity logs** — audit trail of admin actions (imports, edits, deletions).
- **PWA-ready** — `manifest.json` and `service-worker.js` for an installable
  experience.
- **CSRF-protected** — all state-changing requests (forms and JSON API)
  require a session-bound token.

## Tech stack

| Layer      | Technology                          |
| ---------- | ----------------------------------- |
| Backend    | Python, Flask                       |
| Database   | Supabase (PostgreSQL)               |
| ORM/Client | `supabase` Python client            |
| Auth       | `bcrypt` + Flask sessions           |
| Config     | `python-dotenv`                     |
| Deployment | `gunicorn`                          |
| Frontend   | Server-rendered Jinja + vanilla JS  |

## Prerequisites

- Python 3.9+
- A Supabase project (or any PostgreSQL 14+ database reachable over the
  Supabase client)

## Getting started

### 1. Create a virtual environment and install dependencies

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Set up the database (Supabase)

1. Create a project on [supabase.com](https://supabase.com).
2. Open **SQL Editor** and run the contents of [`schema.sql`](schema.sql).
   It creates all tables, constraints, indexes and triggers, and disables
   Row Level Security because Lectra is a trusted server-side app (the Flask
   backend is the single client and enforces per-user access itself).
   If you prefer to keep RLS enabled, use your project's **service_role key**
   as `SUPABASE_KEY` instead.

### 3. Configure environment variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

```env
SUPABASE_URL=YOUR_SUPABASE_URL
SUPABASE_KEY=YOUR_SUPABASE_ANON_KEY
SECRET_KEY=YOUR_SECRET_KEY
ADMIN_EMAILS=admin@uni.edu,hod@uni.edu
```

Generate a strong secret key:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

`ADMIN_EMAILS` is an optional comma-separated list of email addresses that are
promoted to admin on their next sign-in. The very first account created is
admin automatically.

`.env` is ignored by git — never commit real secrets.

### 4. Enable browser push notifications (optional)

Browser push is opt-in: a signed-in user enables it in **Profile & settings**
and grants the browser permission prompt. Notifications are delivered through
[OneSignal](https://onesignal.com):

1. Create a **Website** app in the OneSignal dashboard and complete the Web SDK
   setup (your site must be HTTPS).
2. From **Settings > Keys & IDs**, copy the **App ID** and **REST API Key**.
3. Add them to `.env`:

```env
ONESIGNAL_APP_ID=YOUR_ONESIGNAL_APP_ID
ONESIGNAL_REST_API_KEY=YOUR_ONESIGNAL_REST_API_KEY
```

When a lecturer ticks a defence, a push is scheduled against OneSignal with
`send_after` for their chosen lead time, so OneSignal's servers deliver it on
time even while this app is asleep. Changing the lead time or unticking the
defence cancels the pending push automatically.

The service worker endpoints (`/OneSignalSDKWorker.js`,
`/OneSignalSDKUpdaterWorker.js`) are served by this app for the browser to
display notifications.

### 5. Run the app

```bash
flask run
```

Open <http://127.0.0.1:5000>, create the first account (this becomes admin),
then upload the defence roster from **Roster** in the top nav.

### Production

```bash
gunicorn --workers 4 --bind 0.0.0.0:8000 app:app
```

Set `FLASK_ENV=production` so sessions require HTTPS cookies. Run behind a
reverse proxy (Nginx/Caddy) that terminates TLS.

## Project structure

```
Lectra/
├── app.py                 # App factory + gunicorn entry point
├── config.py              # Env-based configuration
├── routes.py              # Blueprint: pages, auth, JSON API
├── models.py              # Data access layer (reusable Supabase client)
├── roster.py              # CSV/TSV/XLSX/DOCX roster parsing + validation
├── schema.sql             # PostgreSQL schema (tables, constraints, indexes)
├── requirements.txt
├── .env / .env.example    # Environment configuration
├── manifest.json          # PWA manifest (served at /manifest.json)
├── service-worker.js      # PWA + OneSignal SDK service worker
├── push/onesignal/        # OneSignal SDK assets
├── static/
│   ├── css/style.css
│   ├── js/app.js
│   ├── js/mobile.js
│   └── images/icon.svg
└── templates/
    ├── base.html
    ├── _flashes.html
    ├── login.html
    ├── signup.html
    ├── dashboard.html
    ├── defences.html
    ├── admin_roster.html
    ├── defence_form.html
    ├── notifications.html
    ├── profile.html
    ├── help.html
    └── error.html
```

## Database overview

Tables: `users`, `schedules` (legacy), `reminders` (legacy), `defences`,
`defence_interests`, `notifications`, `push_subscriptions`, `user_settings`,
`activity_logs`.

Key defence tables:

- `defences` — one row per defence slot: `student_name`, `project_title`,
  `venue`, `event_date`, `start_time`, `end_time`, `supervisor`, `status`
  (`scheduled` / `completed` / `cancelled`), `created_by`. An `ON DELETE
  CASCADE` cleans up interests when a defence is removed.
- `defence_interests` — a lecturer's tick on a defence:
  `reminder_minutes` (their chosen lead time; `0` = at start),
  `notified` (whether the reminder already fired), `onesignal_id` (the pending
  scheduled push, so it can be cancelled later). Unique on
  `(defence_id, user_id)`.

Common infrastructure: UUID primary keys, `ON DELETE CASCADE` foreign keys,
`NOT NULL` / `UNIQUE` / `CHECK` constraints, trigger-maintained
`created_at` / `updated_at`, indexes on common query paths, and a one-to-one
`user_settings` (unique on `user_id`).

## JSON API

All endpoints require a logged-in session. State-changing endpoints require
the `X-CSRF-Token` header.

| Method | Endpoint                                    | Description                  |
| ------ | ------------------------------------------- | ---------------------------- |
| GET    | `/api/defences`                             | List defences               |
| PUT    | `/api/defences/<id>/interest`               | Tick a defence (set lead time) |
| DELETE | `/api/defences/<id>/interest`               | Untick a defence            |
| GET    | `/api/notifications`                        | List notifications          |
| POST   | `/api/notifications/<id>/read`              | Mark notification read      |
| DELETE | `/api/notifications/<id>`                   | Delete notification         |
| POST   | `/api/notifications/read-all`               | Mark all read               |
| GET    | `/api/notifications/unread-count`           | Unread count                |
| PUT    | `/api/settings`                             | Update user settings        |

## Security notes

- Passwords are hashed with `bcrypt` (never stored in plain text).
- Sessions are HTTP-only, SameSite cookies with a configurable lifetime.
- Every POST/PUT/DELETE requires a CSRF token.
- Admin-only pages are guarded by an `admin_required` decorator.
- Database access is scoped by the logged-in `user_id` at the query layer;
  the JSON API always filters by the session user.
- Secrets live only in `.env` (excluded from version control).

## Future roadmap

- Email reminders alongside push
- Multi-venue maps / directions in reminders
- Defence-level attendance marking by admins
- Analytics (attendance rates per supervisor, per day)

## License

Proprietary / to be determined by the project owner.
