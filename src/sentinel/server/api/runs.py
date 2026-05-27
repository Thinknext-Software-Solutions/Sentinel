"""Run trigger + history endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..auth import current_user, require_member_or_admin
from ..db import get_db
from ..models import Project, Run, User
from ..runner import enqueue_run
from ..schemas import RunCreate, RunDetailOut, RunOut


router = APIRouter(prefix="/api", tags=["runs"])


@router.post(
    "/projects/{project_id}/runs",
    response_model=RunOut,
    status_code=status.HTTP_201_CREATED,
)
def trigger_run(
    project_id: str,
    body: RunCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_member_or_admin),
):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    target_url = body.target_url or project.base_url
    run = Run(
        project_id=project.id,
        triggered_by_user_id=user.id,
        target_url=target_url,
        status="queued",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    enqueue_run(run.id)
    return run


@router.get("/projects/{project_id}/runs", response_model=list[RunOut])
def list_project_runs(
    project_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    rows = (
        db.execute(
            select(Run)
            .where(Run.project_id == project_id)
            .order_by(Run.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return list(rows)


@router.get("/runs", response_model=list[RunOut])
def list_recent_runs(
    limit: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    rows = (
        db.execute(select(Run).order_by(Run.created_at.desc()).limit(limit))
        .scalars()
        .all()
    )
    return list(rows)


@router.get("/runs/{run_id}", response_model=RunDetailOut)
def get_run(
    run_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    run = (
        db.execute(
            select(Run)
            .where(Run.id == run_id)
            .options(
                selectinload(Run.scenarios),
                selectinload(Run.visual_diffs),
                selectinload(Run.a11y_violations),
            )
        )
        .scalar_one_or_none()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run
