from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ReportType(str, enum.Enum):
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"
    custom = "custom"


class ReportStatus(str, enum.Enum):
    running = "running"
    completed = "completed"
    failed = "failed"


class SourceType(str, enum.Enum):
    portal = "portal"
    file_upload = "file_upload"
    api = "api"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ReportRun(Base):
    __tablename__ = "report_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    report_type: Mapped[ReportType] = mapped_column(
        Enum(ReportType, name="report_type_enum"), nullable=False
    )
    status: Mapped[ReportStatus] = mapped_column(
        Enum(ReportStatus, name="report_status_enum"),
        nullable=False,
        default=ReportStatus.running,
    )
    source_files: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    output_pdf_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    output_excel_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    email_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    row_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    logs: Mapped[list[ReportLog]] = relationship(
        "ReportLog", back_populates="report_run", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<ReportRun id={self.id} type={self.report_type} status={self.status}>"


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType, name="source_type_enum"), nullable=False
    )
    portal_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    last_downloaded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_file_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<DataSource id={self.id} name={self.name} type={self.source_type}>"


class ReportLog(Base):
    __tablename__ = "report_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    report_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("report_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage: Mapped[str] = mapped_column(String(128), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    report_run: Mapped[ReportRun] = relationship("ReportRun", back_populates="logs")

    def __repr__(self) -> str:
        return f"<ReportLog id={self.id} run={self.report_run_id} stage={self.stage}>"
