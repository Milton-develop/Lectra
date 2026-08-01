-- ============================================================================
--  Lectra — Database Schema (PostgreSQL / Supabase)
-- ============================================================================
--  Run this file once against your Supabase project (SQL Editor) or any
--  PostgreSQL 14+ database. It is safe to run repeatedly.
--
--  Conventions:
--    * UUID primary keys generated automatically.
--    * TIMESTAMPTZ everywhere (UTC) with automatic defaults.
--    * updated_at maintained automatically by a trigger.
--    * CHECK constraints enforce allowed enum-style values.
--    * ON DELETE CASCADE keeps child rows in sync.
--    * Indexes tuned for the most common query patterns.
-- ============================================================================

-- pgcrypto provides gen_random_uuid() (built-in on PostgreSQL 13+).
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------------
-- USERS
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fullname      TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    department    TEXT,
    institution   TEXT,
    phone         TEXT,
    avatar_url    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_users_email_format CHECK (
        email ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$'
    )
);

-- ---------------------------------------------------------------------------
-- SCHEDULES
--   A user owns many schedules (lectures, meetings, exams, office hours...).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schedules (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    description TEXT,
    category    TEXT,
    location    TEXT,
    event_date  DATE NOT NULL,
    start_time  TIME NOT NULL,
    end_time    TIME,
    repeat_type TEXT NOT NULL DEFAULT 'none',
    priority    TEXT NOT NULL DEFAULT 'normal',
    color       TEXT NOT NULL DEFAULT '#4F46E5',
    status      TEXT NOT NULL DEFAULT 'upcoming',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT chk_schedules_repeat_type
        CHECK (repeat_type IN ('none', 'daily', 'weekly', 'monthly', 'yearly', 'custom')),
    CONSTRAINT chk_schedules_priority
        CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
    CONSTRAINT chk_schedules_status
        CHECK (status IN ('upcoming', 'completed', 'cancelled', 'rescheduled')),
    CONSTRAINT chk_schedules_time_order
        CHECK (end_time IS NULL OR start_time <= end_time)
);

-- ---------------------------------------------------------------------------
-- REMINDERS
--   A schedule can have multiple reminders (e.g. 15 and 60 minutes before).
--   reminder_minutes = 0 means "at the event start time".
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reminders (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    schedule_id      UUID NOT NULL REFERENCES schedules (id) ON DELETE CASCADE,
    reminder_minutes INTEGER NOT NULL,
    notification_sent BOOLEAN NOT NULL DEFAULT FALSE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT chk_reminders_positive CHECK (reminder_minutes >= 0),
    CONSTRAINT uq_reminders_schedule_minutes UNIQUE (schedule_id, reminder_minutes)
);

-- ---------------------------------------------------------------------------
-- NOTIFICATIONS
--   Belong to a user and, optionally, to a schedule.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notifications (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    schedule_id UUID REFERENCES schedules (id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    message     TEXT,
    is_read     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- PUSH_SUBSCRIPTIONS
--   One row per browser/device that opted in to browser push.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS push_subscriptions (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    endpoint   TEXT NOT NULL UNIQUE,
    p256dh     TEXT NOT NULL,
    auth       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- USER_SETTINGS
--   One-to-one with users (UNIQUE on user_id).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_settings (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            UUID NOT NULL UNIQUE REFERENCES users (id) ON DELETE CASCADE,
    push_notifications BOOLEAN NOT NULL DEFAULT TRUE,
    dark_mode          BOOLEAN NOT NULL DEFAULT FALSE,
    default_reminder   INTEGER NOT NULL DEFAULT 30,
    timezone           TEXT NOT NULL DEFAULT 'UTC',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT chk_settings_default_reminder CHECK (default_reminder > 0)
);

-- ---------------------------------------------------------------------------
-- ACTIVITY_LOGS
--   Audit trail of user actions (login, create, edit, delete, ...).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS activity_logs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    action      TEXT NOT NULL,
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- MIGRATIONS — apply after updating this file on an existing database
-- ---------------------------------------------------------------------------
-- Allow reminder_minutes = 0 ("at event start time" reminders).
ALTER TABLE reminders DROP CONSTRAINT IF EXISTS chk_reminders_positive;
ALTER TABLE reminders ADD CONSTRAINT chk_reminders_positive
    CHECK (reminder_minutes >= 0);

-- ---------------------------------------------------------------------------
-- TRIGGERS — automatic updated_at
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_users_updated_at ON users;
CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_schedules_updated_at ON schedules;
CREATE TRIGGER trg_schedules_updated_at
    BEFORE UPDATE ON schedules
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- INDEXES — common query patterns
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_users_email ON users (email);

CREATE INDEX IF NOT EXISTS idx_schedules_user_id   ON schedules (user_id);
CREATE INDEX IF NOT EXISTS idx_schedules_event_date ON schedules (event_date);
CREATE INDEX IF NOT EXISTS idx_schedules_user_date ON schedules (user_id, event_date);
CREATE INDEX IF NOT EXISTS idx_schedules_status    ON schedules (status);

CREATE INDEX IF NOT EXISTS idx_reminders_schedule_id ON reminders (schedule_id);

CREATE INDEX IF NOT EXISTS idx_notifications_user_id ON notifications (user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_user_read
    ON notifications (user_id, is_read);

CREATE INDEX IF NOT EXISTS idx_push_subscriptions_user_id
    ON push_subscriptions (user_id);

CREATE INDEX IF NOT EXISTS idx_activity_logs_user_id
    ON activity_logs (user_id, created_at DESC);

-- ---------------------------------------------------------------------------
-- ROW LEVEL SECURITY
--   Lectra is a trusted server-side application: the Flask backend is the only
--   client and performs its own authorization per logged-in user. Supabase
--   enables RLS by default, which would block the anon key from reading or
--   writing data, so we disable it here.
--   Alternative: keep RLS enabled and use the service_role key as SUPABASE_KEY.
-- ---------------------------------------------------------------------------
ALTER TABLE users          DISABLE ROW LEVEL SECURITY;
ALTER TABLE schedules      DISABLE ROW LEVEL SECURITY;
ALTER TABLE reminders      DISABLE ROW LEVEL SECURITY;
ALTER TABLE notifications  DISABLE ROW LEVEL SECURITY;
ALTER TABLE push_subscriptions DISABLE ROW LEVEL SECURITY;
ALTER TABLE user_settings  DISABLE ROW LEVEL SECURITY;
ALTER TABLE activity_logs  DISABLE ROW LEVEL SECURITY;
