"""Database models and initialization for the Home Automation Bot.

Uses SQLAlchemy ORM with SQLite. The database file is created automatically
at the path specified by ``Config.DATABASE_URL``.
"""

from datetime import date, datetime, timedelta

from sqlalchemy import Boolean, DateTime, Integer, String, create_engine, delete
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from config import Config
from utils.logger import get_logger

logger = get_logger(__name__)

_engine = None


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

class CommandLog(Base):
    """Audit log entry for every command received by the bot."""

    __tablename__ = "command_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    command: Mapped[str] = mapped_column(String(128), nullable=False)
    arguments: Mapped[str | None] = mapped_column(String(500), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return (
            f"CommandLog(id={self.id}, user_id={self.user_id}, "
            f"command='{self.command}', timestamp={self.timestamp})"
        )


# ---------------------------------------------------------------------------
# Shopping list
# ---------------------------------------------------------------------------

class ShoppingItem(Base):
    """A single item on the shared household shopping list."""

    __tablename__ = "shopping_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    added_by_id: Mapped[int] = mapped_column(Integer, nullable=False)
    added_by_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"ShoppingItem(id={self.id}, name='{self.name}', added_by_id={self.added_by_id})"


# ---------------------------------------------------------------------------
# Reminders (with optional recurrence)
# ---------------------------------------------------------------------------

class Reminder(Base):
    """A scheduled reminder for a user.

    Attributes:
        recurring: If True, a new reminder is created after firing.
        recurrence_type: One of 'daily', 'weekly', 'monthly', 'yearly'.
        action_type: Optional device action to execute when reminder fires
                     (e.g. 'hk_turn_on', 'hk_turn_off').
        action_payload: Device ID to act on (e.g. 'switcher').
    """

    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    text: Mapped[str] = mapped_column(String(500), nullable=False)
    remind_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    fired: Mapped[bool] = mapped_column(Boolean, default=False)
    recurring: Mapped[bool] = mapped_column(Boolean, default=False)
    recurrence_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    action_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    action_payload: Mapped[str | None] = mapped_column(String(200), nullable=True)

    def __repr__(self) -> str:
        return f"Reminder(id={self.id}, user_id={self.user_id}, text='{self.text[:30]}')"


# ---------------------------------------------------------------------------
# User memory
# ---------------------------------------------------------------------------

class UserMemory(Base):
    """A persistent fact stored about or by a user."""

    __tablename__ = "user_memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    fact: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"UserMemory(id={self.id}, user_id={self.user_id}, fact='{self.fact[:40]}')"


# ---------------------------------------------------------------------------
# Tasks / chore list
# ---------------------------------------------------------------------------

class Task(Base):
    """A household task or chore, optionally assigned to a family member.

    Attributes:
        title: Short description of the task.
        created_by_id: Telegram user ID of the person who created it.
        assigned_to_id: Telegram user ID of the person it is assigned to (optional).
        assigned_to_name: Display name of the assignee (for fast display without joins).
        due_date: Optional deadline.
        completed: True once the task is done.
    """

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    created_by_id: Mapped[int] = mapped_column(Integer, nullable=False)
    assigned_to_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    assigned_to_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    due_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"Task(id={self.id}, title='{self.title[:40]}', completed={self.completed})"


# ---------------------------------------------------------------------------
# Family notes (held messages delivered on next contact)
# ---------------------------------------------------------------------------

class FamilyNote(Base):
    """A message left by one family member for another.

    Delivered automatically the next time the recipient sends any message.

    Attributes:
        from_user_id: Telegram user ID of the sender.
        from_user_name: Display name of the sender.
        to_user_id: Telegram user ID of the recipient.
        message: The note content.
        delivered: True once the note has been shown to the recipient.
    """

    __tablename__ = "family_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    from_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    from_user_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    to_user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    message: Mapped[str] = mapped_column(String(1000), nullable=False)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"FamilyNote(id={self.id}, from={self.from_user_id}, to={self.to_user_id})"


# ---------------------------------------------------------------------------
# User profile (onboarding, iCloud credentials, briefing schedule)
# ---------------------------------------------------------------------------

class UserProfile(Base):
    """One-per-user record created on first contact.

    Attributes:
        user_id: Telegram user ID — primary key.
        display_name: The name the user chose. None = registration pending.
        role: Household role, e.g. 'אבא'. None = registration pending.
        onboarded_at: UTC datetime when registration was completed.
        briefing_hour: Local hour (0-23) for the daily morning briefing.
        briefing_minute: Local minute (0-59) for the daily morning briefing.
    """

    __tablename__ = "user_profiles"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    role: Mapped[str | None] = mapped_column(String(50), nullable=True)
    onboarded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    icloud_username: Mapped[str | None] = mapped_column(String(200), nullable=True)
    icloud_app_password: Mapped[str | None] = mapped_column(String(200), nullable=True)
    default_apple_calendar: Mapped[str | None] = mapped_column(String(200), nullable=True)
    briefing_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    briefing_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(10), nullable=True)  # 'male' | 'female'

    def __repr__(self) -> str:
        return (
            f"UserProfile(user_id={self.user_id}, "
            f"display_name='{self.display_name}', role='{self.role}')"
        )


# ---------------------------------------------------------------------------
# Database initialization
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Create all database tables and apply any pending column migrations.

    Uses the DATABASE_URL from Config. Safe to call multiple times.
    """
    global _engine
    _engine = create_engine(Config.DATABASE_URL, echo=False)
    Base.metadata.create_all(_engine)

    # ALTER TABLE migrations for columns added after the initial schema.
    # SQLite raises OperationalError if the column already exists — suppressed.
    _migrations = [
        "ALTER TABLE user_profiles ADD COLUMN role VARCHAR(50)",
        "ALTER TABLE user_profiles ADD COLUMN icloud_username VARCHAR(200)",
        "ALTER TABLE user_profiles ADD COLUMN icloud_app_password VARCHAR(200)",
        "ALTER TABLE user_profiles ADD COLUMN default_apple_calendar VARCHAR(200)",
        "ALTER TABLE user_profiles ADD COLUMN briefing_hour INTEGER",
        "ALTER TABLE user_profiles ADD COLUMN briefing_minute INTEGER",
        "ALTER TABLE user_profiles ADD COLUMN gender VARCHAR(10)",
        "ALTER TABLE reminders ADD COLUMN recurring BOOLEAN DEFAULT 0",
        "ALTER TABLE reminders ADD COLUMN recurrence_type VARCHAR(20)",
        "ALTER TABLE reminders ADD COLUMN action_type VARCHAR(50)",
        "ALTER TABLE reminders ADD COLUMN action_payload VARCHAR(200)",
        "DROP TABLE IF EXISTS calendar_events",
    ]
    with _engine.connect() as conn:
        for sql in _migrations:
            try:
                conn.execute(__import__("sqlalchemy").text(sql))
                conn.commit()
                logger.info(f"Migration applied: {sql}")
            except Exception:
                pass  # Column already exists — skip silently

    logger.info(f"Database initialized at: {Config.DATABASE_URL}")


def get_session() -> Session:
    """Return a new SQLAlchemy session.

    Raises:
        RuntimeError: If ``init_db()`` has not been called yet.
    """
    if _engine is None:
        raise RuntimeError("Database not initialized — call init_db() first")
    return Session(_engine)


# ---------------------------------------------------------------------------
# Audit log helpers
# ---------------------------------------------------------------------------

def log_command(
    user_id: int,
    command: str,
    username: str | None = None,
    arguments: str | None = None,
    success: bool = True,
) -> None:
    """Write a command audit entry to the database."""
    try:
        with get_session() as session:
            entry = CommandLog(
                user_id=user_id,
                username=username,
                command=command,
                arguments=arguments,
                success=success,
            )
            session.add(entry)
            session.commit()
    except Exception as exc:
        logger.error(f"Failed to log command to database: {exc}", exc_info=True)


# ---------------------------------------------------------------------------
# Shopping list helpers
# ---------------------------------------------------------------------------

def add_shopping_item(name: str, user_id: int, username: str | None = None) -> "ShoppingItem | None":
    """Add a single item to the shopping list."""
    try:
        with get_session() as session:
            item = ShoppingItem(name=name, added_by_id=user_id, added_by_name=username)
            session.add(item)
            session.commit()
            session.refresh(item)
            return item
    except Exception as exc:
        logger.error(f"Failed to add shopping item '{name}': {exc}", exc_info=True)
        return None


def get_shopping_items() -> list["ShoppingItem"]:
    """Return all shopping list items ordered by insertion order."""
    try:
        with get_session() as session:
            items = session.query(ShoppingItem).order_by(ShoppingItem.id.asc()).all()
            for item in items:
                session.expunge(item)
            return items
    except Exception as exc:
        logger.error(f"Failed to fetch shopping items: {exc}", exc_info=True)
        return []


def update_shopping_item(item_id: int, new_name: str) -> bool:
    """Rename a shopping item."""
    try:
        with get_session() as session:
            item = session.get(ShoppingItem, item_id)
            if item is None:
                return False
            item.name = new_name
            session.commit()
            return True
    except Exception as exc:
        logger.error(f"Failed to update shopping item {item_id}: {exc}", exc_info=True)
        return False


def remove_shopping_item(item_id: int) -> bool:
    """Remove a shopping item by its database ID."""
    try:
        with get_session() as session:
            item = session.get(ShoppingItem, item_id)
            if item is None:
                return False
            session.delete(item)
            session.commit()
            return True
    except Exception as exc:
        logger.error(f"Failed to remove shopping item {item_id}: {exc}", exc_info=True)
        return False


def clear_shopping_list() -> int:
    """Delete every item from the shopping list. Returns number of items deleted."""
    try:
        with get_session() as session:
            count = session.query(ShoppingItem).count()
            session.execute(delete(ShoppingItem))
            session.commit()
            logger.info(f"Shopping list cleared — {count} items removed")
            return count
    except Exception as exc:
        logger.error(f"Failed to clear shopping list: {exc}", exc_info=True)
        return 0


# ---------------------------------------------------------------------------
# Reminder helpers
# ---------------------------------------------------------------------------

def add_reminder(
    user_id: int,
    text: str,
    remind_at: datetime,
    recurring: bool = False,
    recurrence_type: str | None = None,
    action_type: str | None = None,
    action_payload: str | None = None,
) -> "Reminder | None":
    """Persist a new reminder."""
    try:
        with get_session() as session:
            r = Reminder(
                user_id=user_id,
                text=text,
                remind_at=remind_at,
                recurring=recurring,
                recurrence_type=recurrence_type,
                action_type=action_type,
                action_payload=action_payload,
            )
            session.add(r)
            session.commit()
            session.refresh(r)
            return r
    except Exception as exc:
        logger.error(f"Failed to add reminder: {exc}", exc_info=True)
        return None


def get_pending_reminders(user_id: int) -> list["Reminder"]:
    """Return all unfired reminders for a specific user, soonest first."""
    try:
        with get_session() as session:
            rows = (
                session.query(Reminder)
                .filter(Reminder.user_id == user_id, Reminder.fired.is_(False))
                .order_by(Reminder.remind_at.asc())
                .all()
            )
            for r in rows:
                session.expunge(r)
            return rows
    except Exception as exc:
        logger.error(f"Failed to fetch reminders for user {user_id}: {exc}", exc_info=True)
        return []


def get_all_pending_reminders() -> list["Reminder"]:
    """Return all unfired reminders across all users (for startup re-scheduling)."""
    try:
        with get_session() as session:
            rows = (
                session.query(Reminder)
                .filter(Reminder.fired.is_(False))
                .order_by(Reminder.remind_at.asc())
                .all()
            )
            for r in rows:
                session.expunge(r)
            return rows
    except Exception as exc:
        logger.error(f"Failed to fetch all pending reminders: {exc}", exc_info=True)
        return []


def mark_reminder_fired(reminder_id: int) -> None:
    """Mark a reminder as sent. If recurring, insert the next occurrence."""
    try:
        with get_session() as session:
            r = session.get(Reminder, reminder_id)
            if r is None:
                return
            if r.recurring and r.recurrence_type:
                next_dt = _next_occurrence(r.remind_at, r.recurrence_type)
                if next_dt:
                    session.add(Reminder(
                        user_id=r.user_id,
                        text=r.text,
                        remind_at=next_dt,
                        recurring=True,
                        recurrence_type=r.recurrence_type,
                        action_type=r.action_type,
                        action_payload=r.action_payload,
                    ))
            r.fired = True
            session.commit()
    except Exception as exc:
        logger.error(f"Failed to mark reminder {reminder_id} as fired: {exc}", exc_info=True)


def _next_occurrence(dt: datetime, recurrence_type: str) -> datetime | None:
    """Calculate the next fire time for a recurring reminder."""
    if recurrence_type == "daily":
        return dt + timedelta(days=1)
    if recurrence_type == "weekly":
        return dt + timedelta(weeks=1)
    if recurrence_type == "monthly":
        month = dt.month + 1
        year = dt.year + (month - 1) // 12
        month = ((month - 1) % 12) + 1
        return dt.replace(year=year, month=month)
    if recurrence_type == "yearly":
        return dt.replace(year=dt.year + 1)
    return None


def cancel_reminder(reminder_id: int) -> bool:
    """Delete a reminder by its database ID."""
    try:
        with get_session() as session:
            r = session.get(Reminder, reminder_id)
            if r is None:
                return False
            session.delete(r)
            session.commit()
            return True
    except Exception as exc:
        logger.error(f"Failed to cancel reminder {reminder_id}: {exc}", exc_info=True)
        return False


# ---------------------------------------------------------------------------
# User memory helpers
# ---------------------------------------------------------------------------

def add_memory(user_id: int, fact: str) -> "UserMemory | None":
    """Store a new memory fact for a user."""
    try:
        with get_session() as session:
            m = UserMemory(user_id=user_id, fact=fact)
            session.add(m)
            session.commit()
            session.refresh(m)
            return m
    except Exception as exc:
        logger.error(f"Failed to add memory for user {user_id}: {exc}", exc_info=True)
        return None


def get_memories(user_id: int) -> list["UserMemory"]:
    """Return all stored memories for a user, oldest first."""
    try:
        with get_session() as session:
            rows = (
                session.query(UserMemory)
                .filter(UserMemory.user_id == user_id)
                .order_by(UserMemory.id.asc())
                .all()
            )
            for m in rows:
                session.expunge(m)
            return rows
    except Exception as exc:
        logger.error(f"Failed to fetch memories for user {user_id}: {exc}", exc_info=True)
        return []


def delete_memory(memory_id: int) -> bool:
    """Delete a stored memory by its database ID."""
    try:
        with get_session() as session:
            m = session.get(UserMemory, memory_id)
            if m is None:
                return False
            session.delete(m)
            session.commit()
            return True
    except Exception as exc:
        logger.error(f"Failed to delete memory {memory_id}: {exc}", exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Task helpers
# ---------------------------------------------------------------------------

def add_task(
    title: str,
    created_by_id: int,
    assigned_to_id: int | None = None,
    assigned_to_name: str | None = None,
    due_date: datetime | None = None,
) -> "Task | None":
    """Create a new household task."""
    try:
        with get_session() as session:
            t = Task(
                title=title,
                created_by_id=created_by_id,
                assigned_to_id=assigned_to_id,
                assigned_to_name=assigned_to_name,
                due_date=due_date,
            )
            session.add(t)
            session.commit()
            session.refresh(t)
            return t
    except Exception as exc:
        logger.error(f"Failed to add task '{title}': {exc}", exc_info=True)
        return None


def get_open_tasks() -> list["Task"]:
    """Return all incomplete tasks, ordered by due date then creation time."""
    try:
        with get_session() as session:
            rows = (
                session.query(Task)
                .filter(Task.completed.is_(False))
                .order_by(Task.due_date.asc().nulls_last(), Task.created_at.asc())
                .all()
            )
            for t in rows:
                session.expunge(t)
            return rows
    except Exception as exc:
        logger.error(f"Failed to fetch open tasks: {exc}", exc_info=True)
        return []


def get_tasks_for_user(user_id: int) -> list["Task"]:
    """Return all incomplete tasks assigned to a specific user."""
    try:
        with get_session() as session:
            rows = (
                session.query(Task)
                .filter(Task.assigned_to_id == user_id, Task.completed.is_(False))
                .order_by(Task.due_date.asc().nulls_last(), Task.created_at.asc())
                .all()
            )
            for t in rows:
                session.expunge(t)
            return rows
    except Exception as exc:
        logger.error(f"Failed to fetch tasks for user {user_id}: {exc}", exc_info=True)
        return []


def complete_task(task_id: int) -> bool:
    """Mark a task as completed."""
    try:
        with get_session() as session:
            t = session.get(Task, task_id)
            if t is None:
                return False
            t.completed = True
            session.commit()
            return True
    except Exception as exc:
        logger.error(f"Failed to complete task {task_id}: {exc}", exc_info=True)
        return False


def delete_task(task_id: int) -> bool:
    """Delete a task by its database ID."""
    try:
        with get_session() as session:
            t = session.get(Task, task_id)
            if t is None:
                return False
            session.delete(t)
            session.commit()
            return True
    except Exception as exc:
        logger.error(f"Failed to delete task {task_id}: {exc}", exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Family note helpers
# ---------------------------------------------------------------------------

def add_note(
    from_user_id: int,
    from_user_name: str | None,
    to_user_id: int,
    message: str,
) -> "FamilyNote | None":
    """Leave a note for another family member."""
    try:
        with get_session() as session:
            n = FamilyNote(
                from_user_id=from_user_id,
                from_user_name=from_user_name,
                to_user_id=to_user_id,
                message=message,
            )
            session.add(n)
            session.commit()
            session.refresh(n)
            return n
    except Exception as exc:
        logger.error(f"Failed to add note from {from_user_id} to {to_user_id}: {exc}", exc_info=True)
        return None


def get_pending_notes(to_user_id: int) -> list["FamilyNote"]:
    """Return all undelivered notes for a user, oldest first."""
    try:
        with get_session() as session:
            rows = (
                session.query(FamilyNote)
                .filter(FamilyNote.to_user_id == to_user_id, FamilyNote.delivered.is_(False))
                .order_by(FamilyNote.created_at.asc())
                .all()
            )
            for n in rows:
                session.expunge(n)
            return rows
    except Exception as exc:
        logger.error(f"Failed to fetch notes for user {to_user_id}: {exc}", exc_info=True)
        return []


def mark_notes_delivered(to_user_id: int) -> None:
    """Mark all pending notes for a user as delivered."""
    try:
        with get_session() as session:
            rows = (
                session.query(FamilyNote)
                .filter(FamilyNote.to_user_id == to_user_id, FamilyNote.delivered.is_(False))
                .all()
            )
            for n in rows:
                n.delivered = True
            session.commit()
    except Exception as exc:
        logger.error(f"Failed to mark notes delivered for user {to_user_id}: {exc}", exc_info=True)


# ---------------------------------------------------------------------------
# User profile helpers
# ---------------------------------------------------------------------------

def get_all_user_profiles() -> list["UserProfile"]:
    """Return all fully onboarded user profiles (name and role both set)."""
    try:
        with get_session() as session:
            rows = (
                session.query(UserProfile)
                .filter(
                    UserProfile.display_name.isnot(None),
                    UserProfile.role.isnot(None),
                )
                .all()
            )
            for p in rows:
                session.expunge(p)
            return rows
    except Exception as exc:
        logger.error(f"Failed to fetch all user profiles: {exc}", exc_info=True)
        return []


def get_user_profile(user_id: int) -> "UserProfile | None":
    """Return the profile for a user, or None if they have never interacted."""
    try:
        with get_session() as session:
            profile = session.get(UserProfile, user_id)
            if profile:
                session.expunge(profile)
            return profile
    except Exception as exc:
        logger.error(f"Failed to fetch profile for user {user_id}: {exc}", exc_info=True)
        return None


def create_user_profile(user_id: int) -> "UserProfile | None":
    """Create a blank profile for a new user (registration pending)."""
    try:
        with get_session() as session:
            profile = UserProfile(user_id=user_id)
            session.add(profile)
            session.commit()
            session.refresh(profile)
            return profile
    except Exception as exc:
        logger.error(f"Failed to create profile for user {user_id}: {exc}", exc_info=True)
        return None


def set_user_name(user_id: int, name: str) -> bool:
    """Save the user's chosen display name."""
    try:
        with get_session() as session:
            profile = session.get(UserProfile, user_id)
            if profile is None:
                return False
            profile.display_name = name
            session.commit()
            return True
    except Exception as exc:
        logger.error(f"Failed to set name for user {user_id}: {exc}", exc_info=True)
        return False


def set_user_gender(user_id: int, gender: str) -> bool:
    """Save the user's gender ('male' or 'female') and mark onboarding complete."""
    try:
        with get_session() as session:
            profile = session.get(UserProfile, user_id)
            if profile is None:
                return False
            profile.gender = gender
            profile.onboarded_at = datetime.utcnow()
            session.commit()
            return True
    except Exception as exc:
        logger.error(f"Failed to set gender for user {user_id}: {exc}", exc_info=True)
        return False


def set_user_role(user_id: int, role: str) -> bool:
    """Save the user's household role and mark onboarding as complete."""
    try:
        with get_session() as session:
            profile = session.get(UserProfile, user_id)
            if profile is None:
                return False
            profile.role = role
            profile.onboarded_at = datetime.utcnow()
            session.commit()
            return True
    except Exception as exc:
        logger.error(f"Failed to set role for user {user_id}: {exc}", exc_info=True)
        return False


def set_icloud_credentials(user_id: int, username: str, app_password: str) -> bool:
    """Save iCloud CalDAV credentials for a user."""
    try:
        with get_session() as session:
            profile = session.get(UserProfile, user_id)
            if profile is None:
                return False
            profile.icloud_username = username
            profile.icloud_app_password = app_password
            session.commit()
            return True
    except Exception as exc:
        logger.error(f"Failed to set iCloud credentials for user {user_id}: {exc}", exc_info=True)
        return False


def set_default_apple_calendar(user_id: int, calendar_name: str) -> bool:
    """Set the default iCloud calendar name for a user."""
    try:
        with get_session() as session:
            profile = session.get(UserProfile, user_id)
            if profile is None:
                return False
            profile.default_apple_calendar = calendar_name
            session.commit()
            return True
    except Exception as exc:
        logger.error(f"Failed to set default calendar for {user_id}: {exc}", exc_info=True)
        return False


def set_briefing_time(user_id: int, hour: int, minute: int) -> bool:
    """Set the daily morning briefing time for a user."""
    try:
        with get_session() as session:
            profile = session.get(UserProfile, user_id)
            if profile is None:
                return False
            profile.briefing_hour = hour
            profile.briefing_minute = minute
            session.commit()
            return True
    except Exception as exc:
        logger.error(f"Failed to set briefing time for user {user_id}: {exc}", exc_info=True)
        return False


def clear_briefing_time(user_id: int) -> bool:
    """Remove the daily morning briefing for a user."""
    try:
        with get_session() as session:
            profile = session.get(UserProfile, user_id)
            if profile is None:
                return False
            profile.briefing_hour = None
            profile.briefing_minute = None
            session.commit()
            return True
    except Exception as exc:
        logger.error(f"Failed to clear briefing time for user {user_id}: {exc}", exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Admin helpers
# ---------------------------------------------------------------------------

def clear_all_data() -> dict[str, int]:
    """Delete all content rows except user_profiles. Returns counts per table."""
    tables = {
        "shopping_items": ShoppingItem,
        "reminders": Reminder,
        "user_memories": UserMemory,
        "tasks": Task,
        "family_notes": FamilyNote,
        "command_log": CommandLog,
    }
    counts: dict[str, int] = {}
    try:
        with get_session() as session:
            for name, model in tables.items():
                count = session.query(model).count()
                session.execute(delete(model))
                counts[name] = count
            session.commit()
            logger.info(f"clear_all_data: removed {counts}")
    except Exception as exc:
        logger.error(f"Failed to clear all data: {exc}", exc_info=True)
    return counts
