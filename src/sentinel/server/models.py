"""ORM models for Sentinel Studio.

Schema is designed for one local install with a small team. We use
strings for IDs (uuid4 hex) so they're URL-safe and stable across
sqlite-dump migrations.

Roles (global, not per-project in v1):
    admin   -- manage users, full read/write on all projects
    member  -- create projects, trigger runs, view all results
    viewer  -- read-only across all projects
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Users + Sessions
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="member")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    sessions: Mapped[list["UserSession"]] = relationship(
        "UserSession", back_populates="user", cascade="all, delete-orphan"
    )
    projects_created: Mapped[list["Project"]] = relationship(
        "Project", back_populates="created_by", foreign_keys="Project.created_by_user_id"
    )


class UserSession(Base):
    __tablename__ = "user_sessions"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    user_agent: Mapped[str] = mapped_column(String(255), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")

    user: Mapped[User] = relationship("User", back_populates="sessions")


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("slug", name="uq_projects_slug"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    base_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    config_yaml: Mapped[str] = mapped_column(Text, default="")  # sentinel.yaml content
    explore_links: Mapped[bool] = mapped_column(Boolean, default=True)
    llm_provider: Mapped[str] = mapped_column(String(32), default="")
    llm_model: Mapped[str] = mapped_column(String(64), default="")
    created_by_user_id: Mapped[Optional[str]] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    created_by: Mapped[Optional[User]] = relationship(
        "User", back_populates="projects_created", foreign_keys=[created_by_user_id]
    )
    runs: Mapped[list["Run"]] = relationship(
        "Run", back_populates="project", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


# Run.status lifecycle: queued -> running -> {passed, failed, errored, cancelled}
RUN_STATUSES = {"queued", "running", "passed", "failed", "errored", "cancelled"}


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    triggered_by_user_id: Mapped[Optional[str]] = mapped_column(
        String(32), ForeignKey("users.id", ondelete="SET NULL")
    )
    target_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", index=True)
    error_message: Mapped[str] = mapped_column(Text, default="")
    workspace_path: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    scenarios_total: Mapped[int] = mapped_column(Integer, default=0)
    scenarios_passed: Mapped[int] = mapped_column(Integer, default=0)
    visual_diffs_count: Mapped[int] = mapped_column(Integer, default=0)
    a11y_violations_count: Mapped[int] = mapped_column(Integer, default=0)

    project: Mapped[Project] = relationship("Project", back_populates="runs")
    triggered_by: Mapped[Optional[User]] = relationship("User", foreign_keys=[triggered_by_user_id])
    scenarios: Mapped[list["ScenarioRun"]] = relationship(
        "ScenarioRun", back_populates="run", cascade="all, delete-orphan"
    )
    visual_diffs: Mapped[list["VisualDiff"]] = relationship(
        "VisualDiff", back_populates="run", cascade="all, delete-orphan"
    )
    a11y_violations: Mapped[list["A11yViolation"]] = relationship(
        "A11yViolation", back_populates="run", cascade="all, delete-orphan"
    )


class ScenarioRun(Base):
    __tablename__ = "scenario_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    run: Mapped[Run] = relationship("Run", back_populates="scenarios")
    failures: Mapped[list["StepFailure"]] = relationship(
        "StepFailure", back_populates="scenario", cascade="all, delete-orphan"
    )


class StepFailure(Base):
    __tablename__ = "step_failures"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    scenario_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("scenario_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_index: Mapped[int] = mapped_column(Integer, default=0)
    step_description: Mapped[str] = mapped_column(Text, default="")
    message: Mapped[str] = mapped_column(Text, default="")
    screenshot_path: Mapped[str] = mapped_column(String(512), default="")

    scenario: Mapped[ScenarioRun] = relationship("ScenarioRun", back_populates="failures")


class VisualDiff(Base):
    __tablename__ = "visual_diffs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    baseline_path: Mapped[str] = mapped_column(String(512), default="")
    current_path: Mapped[str] = mapped_column(String(512), default="")
    diff_path: Mapped[str] = mapped_column(String(512), default="")
    percent_changed: Mapped[float] = mapped_column(Float, default=0.0)
    threshold: Mapped[float] = mapped_column(Float, default=0.0)

    run: Mapped[Run] = relationship("Run", back_populates="visual_diffs")


class A11yViolation(Base):
    __tablename__ = "a11y_violations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_url: Mapped[str] = mapped_column(String(1024), default="")
    rule_id: Mapped[str] = mapped_column(String(64), default="")
    impact: Mapped[str] = mapped_column(String(16), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    sample_selector: Mapped[str] = mapped_column(String(512), default="")
    nodes_affected: Mapped[int] = mapped_column(Integer, default=0)

    run: Mapped[Run] = relationship("Run", back_populates="a11y_violations")
