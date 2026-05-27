"""Project CRUD endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user, require_member_or_admin
from ..db import get_db
from ..models import Project, User
from ..schemas import ProjectCreate, ProjectOut, ProjectUpdate


router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=list[ProjectOut])
def list_projects(
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    rows = db.execute(select(Project).order_by(Project.created_at.desc())).scalars().all()
    return list(rows)


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(
    body: ProjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_member_or_admin),
):
    existing = db.execute(
        select(Project).where(Project.slug == body.slug)
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"Slug '{body.slug}' already exists")
    project = Project(
        slug=body.slug,
        name=body.name,
        base_url=body.base_url,
        description=body.description,
        config_yaml=body.config_yaml,
        explore_links=body.explore_links,
        llm_provider=body.llm_provider,
        llm_model=body.llm_model,
        created_by_user_id=user.id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: str,
    body: ProjectUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_member_or_admin),
):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_member_or_admin),
):
    project = db.get(Project, project_id)
    if project is None:
        return
    db.delete(project)
    db.commit()
