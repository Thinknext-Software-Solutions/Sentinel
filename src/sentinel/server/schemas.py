"""Pydantic schemas for API request/response bodies."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=200)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    name: str
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Users (admin endpoints)
# ---------------------------------------------------------------------------


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    name: str = Field(default="", max_length=255)
    password: str = Field(..., min_length=8, max_length=200)
    role: Literal["admin", "member", "viewer"] = "member"


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = Field(default=None, max_length=255)
    role: Optional[Literal["admin", "member", "viewer"]] = None
    is_active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=200)


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(..., min_length=1, max_length=120)
    base_url: str = Field(..., min_length=1, max_length=1024)
    description: str = Field(default="", max_length=2000)
    config_yaml: str = Field(default="")
    explore_links: bool = True
    llm_provider: str = Field(default="", max_length=32)
    llm_model: str = Field(default="", max_length=64)


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    base_url: Optional[str] = Field(default=None, min_length=1, max_length=1024)
    description: Optional[str] = Field(default=None, max_length=2000)
    config_yaml: Optional[str] = None
    explore_links: Optional[bool] = None
    llm_provider: Optional[str] = Field(default=None, max_length=32)
    llm_model: Optional[str] = Field(default=None, max_length=64)


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    slug: str
    name: str
    base_url: str
    description: str
    config_yaml: str
    explore_links: bool
    llm_provider: str
    llm_model: str
    created_by_user_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_url: Optional[str] = Field(
        default=None,
        max_length=1024,
        description="Override the project's base_url for this run. None = use project default.",
    )


class StepFailureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    step_index: int
    step_description: str
    message: str
    screenshot_path: str


class ScenarioRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: str
    passed: bool
    duration_seconds: float
    order_index: int
    failures: list[StepFailureOut] = []


class VisualDiffOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    baseline_path: str
    current_path: str
    diff_path: str
    percent_changed: float
    threshold: float


class A11yViolationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    page_url: str
    rule_id: str
    impact: str
    description: str
    sample_selector: str
    nodes_affected: int


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    triggered_by_user_id: Optional[str] = None
    target_url: str
    status: str
    error_message: str
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    cost_usd: float
    input_tokens: int
    output_tokens: int
    scenarios_total: int
    scenarios_passed: int
    visual_diffs_count: int
    a11y_violations_count: int


class RunDetailOut(RunOut):
    scenarios: list[ScenarioRunOut] = []
    visual_diffs: list[VisualDiffOut] = []
    a11y_violations: list[A11yViolationOut] = []
