# Lectra — Lecture Scheduling Platform

Lectra helps lecturers plan, manage and remember their lectures, exams,
meetings and office hours. This is the Flask + Supabase (PostgreSQL) backend
and web app.

## Features

- **Secure accounts** — registration, login/logout with `bcrypt` password
  hashing and signed Flask sessions (no Supabase Auth required).
- **Schedule management** — create, edit, view and delete schedules with
  categories, priority, color, repeat type and status.
- **Calendar view** — interactive month calendar with a day-detail panel and
  inline delete.
- **Reminders** — multiple reminders per schedule (e.g. 10, 30, 60 minutes
  before), ready to drive email/push notifications later.
- **Notifications** — in-app notification feed with unread badges.
- **History & search** — filter past schedules by keyword and status.
- **Profile & settings** — user profile, dark mode, push notification
  preference, default reminder and timezone.
- **Activity logs** — audit trail of user actions.
- **PWA-ready** — `manifest.json` and `service-worker.js` for offline-first
  installable experience.
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
   If you created the database before enabling browser push, run `schema.sql`
   again so it also creates the `push_subscriptions` table.

### 3. Configure environment variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

```env
SUPABASE_URL=YOUR_SUPABASE_URL
SUPABASE_KEY=YOUR_SUPABASE_ANON_KEY
SECRET_KEY=YOUR_SECRET_KEY
```

Generate a strong secret key:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

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

Reminder pushes are scheduled against OneSignal with `send_after` when a
schedule is saved, so OneSignal's servers deliver them exactly on time even
while this app is asleep (e.g. Render's free tier spinning down after 15
minutes of inactivity). Editing or deleting a schedule cancels its pending
pushes automatically.

The service worker file at `/push/onesignal/OneSignalSDKWorker.js` is required
for the browser to display notifications; it is served by this app.

### 5. Run the app

```bash
flask run
```

Open <http://127.0.0.1:5000> and create an account.

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
├── schema.sql             # PostgreSQL schema (tables, constraints, indexes)
├── requirements.txt
├── .env / .env.example    # Environment configuration
├── manifest.json          # PWA manifest (served at /manifest.json)
├── service-worker.js      # PWA service worker (served at /service-worker.js)
├── push/onesignal/        # OneSignal service worker (served at /push/onesignal/)
├── static/
│   ├── css/style.css
│   ├── js/app.js
│   └── images/icon.svg
└── templates/
    ├── base.html
    ├── _flashes.html
    ├── login.html
    ├── signup.html
    ├── dashboard.html
    ├── calendar.html
    ├── create_schedule.html
    ├── history.html
    ├── profile.html
    └── error.html
```

## Database overview

Six tables (`users`, `schedules`, `reminders`, `notifications`,
`user_settings`, `activity_logs`) with:

- UUID primary keys generated automatically
- Foreign keys with `ON DELETE CASCADE`
- `NOT NULL`, `UNIQUE` and `CHECK` constraints
- Automatic `created_at` / `updated_at` timestamps (trigger-maintained)
- Indexes on the most common query paths
- One-to-one `user_settings` (unique on `user_id`)

## JSON API

All endpoints require a logged-in session. State-changing endpoints require
the `X-CSRF-Token` header.

| Method | Endpoint                                    | Description                  |
| ------ | ------------------------------------------- | ---------------------------- |
| GET    | `/api/schedules?start=&end=`                | List schedules in range      |
| GET    | `/api/schedules/<id>`                       | Get one schedule             |
| DELETE | `/api/schedules/<id>`                       | Delete schedule              |
| POST   | `/api/schedules/<id>/reminders`             | Add a reminder               |
| DELETE | `/api/reminders/<id>`                       | Delete a reminder            |
| GET    | `/api/notifications`                        | List notifications           |
| POST   | `/api/notifications/<id>/read`              | Mark notification read       |
| POST   | `/api/notifications/read-all`               | Mark all read                |
| GET    | `/api/notifications/unread-count`           | Unread count                 |
| PUT    | `/api/settings`                             | Update user settings         |

## Security notes

- Passwords are hashed with `bcrypt` (never stored in plain text).
- Sessions are HTTP-only, SameSite cookies with a configurable lifetime.
- Every POST/PUT/DELETE requires a CSRF token.
- Database access is scoped by the logged-in `user_id` at the query layer;
  the JSON API always filters by the session user.
- Secrets live only in `.env` (excluded from version control).

## Future roadmap

The architecture leaves clean extension points for:

- Email reminders and push notifications (reminders table already models
  per-schedule timing)
- Calendar synchronization (Google / Outlook)
- Department-wide scheduling and multi-university support
- Admin dashboard and analytics
- AI scheduling assistant
- File attachments and lecture notes
- Export to PDF
- Mobile application (JSON API is ready)

## License

Proprietary / to be determined by the project owner.
