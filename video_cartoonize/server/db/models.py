"""ORM models — 与 PRD §8 表结构一一对应。"""
from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from video_cartoonize.server.db.engine import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    work_dir: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    source_name: Mapped[str | None] = mapped_column(Text)
    style_id: Mapped[str] = mapped_column(Text, default="anime")
    state_version: Mapped[int] = mapped_column(Integer, default=5)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)
    archived: Mapped[int] = mapped_column(Integer, default=0)

    jobs: Mapped[list["PipelineJob"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    seedance_tasks: Mapped[list["SeedanceTask"]] = relationship(back_populates="project")

    __table_args__ = (
        Index("idx_projects_created", "created_at"),
    )


class PipelineJob(Base):
    __tablename__ = "pipeline_jobs"

    job_id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    step: Mapped[str] = mapped_column(Text, nullable=False)
    clip_id: Mapped[int | None] = mapped_column(Integer)
    scope: Mapped[str | None] = mapped_column(Text)       # regen: frame | whole-clip
    frame_idx: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(Text)
    log_path: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[int | None] = mapped_column(Integer)
    finished_at: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)

    project: Mapped["Project"] = relationship(back_populates="jobs")

    __table_args__ = (
        Index("idx_jobs_project", "project_id", "created_at"),
    )


class SeedanceTask(Base):
    """Seedance 历史任务记录（按 api_key_hash 可查询）。"""
    __tablename__ = "seedance_tasks"

    task_id: Mapped[str] = mapped_column(Text, primary_key=True)  # cgt-…
    project_id: Mapped[str | None] = mapped_column(Text, ForeignKey("projects.id", ondelete="SET NULL"))
    clip_id: Mapped[int] = mapped_column(Integer, nullable=False)
    job_id: Mapped[str | None] = mapped_column(Text, ForeignKey("pipeline_jobs.job_id", ondelete="SET NULL"))
    # SHA-256(api_key).hexdigest() — 不存明文
    api_key_hash: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    resolution: Mapped[str] = mapped_column(Text, default="720p")
    status: Mapped[str] = mapped_column(Text, nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    output_url: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[int] = mapped_column(Integer, nullable=False)
    finished_at: Mapped[int | None] = mapped_column(Integer)
    is_regen: Mapped[int] = mapped_column(Integer, default=0)

    project: Mapped["Project | None"] = relationship(back_populates="seedance_tasks")

    __table_args__ = (
        Index("idx_st_key_hash", "api_key_hash", "submitted_at"),
        Index("idx_st_project", "project_id", "clip_id"),
    )


class RegenHistory(Base):
    __tablename__ = "regen_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    clip_id: Mapped[int] = mapped_column(Integer, nullable=False)
    frame_idx: Mapped[int | None] = mapped_column(Integer)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    prompt: Mapped[str | None] = mapped_column(Text)
    style_strength: Mapped[float] = mapped_column(Float, default=0.75)
    seed: Mapped[int | None] = mapped_column(Integer)
    job_id: Mapped[str | None] = mapped_column(Text, ForeignKey("pipeline_jobs.job_id", ondelete="SET NULL"))
    new_task_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        Index("idx_regen_project", "project_id", "clip_id", "created_at"),
    )
