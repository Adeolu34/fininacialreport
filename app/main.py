from __future__ import annotations

import os
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import close_db, get_db, init_db
from app.models import DataSource, ReportLog, ReportRun, ReportStatus, ReportType, SourceType
from app.utils.logger import get_logger

logger = get_logger("main")
settings = get_settings()

app = FastAPI(
    title="Financial Reports API",
    description="Automated financial report generation with Celery + Playwright",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def on_startup() -> None:
    logger.info("Starting Financial Reports API")
    await init_db()
    logger.info("Database initialized")


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await close_db()
    logger.info("Financial Reports API shut down")


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class ReportGenerateRequest(BaseModel):
    report_type: ReportType = ReportType.daily
    date_start: Optional[date] = None
    date_end: Optional[date] = None


class DataSourceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    source_type: SourceType
    portal_url: Optional[str] = None
    is_active: bool = True


class ReportRunOut(BaseModel):
    id: int
    report_type: str
    status: str
    row_count: Optional[int]
    email_sent: bool
    output_pdf_path: Optional[str]
    output_excel_path: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    error_message: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class DataSourceOut(BaseModel):
    id: int
    name: str
    source_type: str
    portal_url: Optional[str]
    last_downloaded_at: Optional[datetime]
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ReportLogOut(BaseModel):
    id: int
    stage: str
    message: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Reports endpoints
# ---------------------------------------------------------------------------

@app.post("/reports/generate", status_code=status.HTTP_202_ACCEPTED)
async def generate_report(
    report_type: str = Form(default="daily"),
    date_start: Optional[str] = Form(default=None),
    date_end: Optional[str] = Form(default=None),
    files: List[UploadFile] = File(default=[]),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Manually trigger a report generation job.

    Accepts optional file uploads (Excel/CSV) as source data.
    If no files are uploaded, the task generates sample/portal data.
    """
    from app.tasks.report_tasks import generate_report_task

    # Save uploaded files
    upload_dir = Path(settings.downloads_dir) / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    saved_paths: List[str] = []

    for upload in files:
        if upload.filename:
            dest = upload_dir / upload.filename
            with open(dest, "wb") as fh:
                shutil.copyfileobj(upload.file, fh)
            saved_paths.append(str(dest))
            logger.info(f"Saved upload: {dest}")

    date_range = None
    if date_start and date_end:
        date_range = {"start": date_start, "end": date_end}

    task = generate_report_task.delay(
        report_type=report_type,
        date_range=date_range,
        source_files=saved_paths,
    )

    return {
        "message": "Report generation started",
        "task_id": task.id,
        "report_type": report_type,
        "uploaded_files": len(saved_paths),
    }


@app.get("/reports", response_model=List[ReportRunOut])
async def list_reports(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    report_type: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> List[ReportRun]:
    stmt = select(ReportRun).order_by(ReportRun.created_at.desc()).limit(limit).offset(offset)

    if status_filter:
        try:
            stmt = stmt.where(ReportRun.status == ReportStatus(status_filter))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status_filter}")

    if report_type:
        try:
            stmt = stmt.where(ReportRun.report_type == ReportType(report_type))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid report_type: {report_type}")

    result = await db.execute(stmt)
    return result.scalars().all()


@app.get("/reports/{report_id}", response_model=ReportRunOut)
async def get_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
) -> ReportRun:
    run = await db.get(ReportRun, report_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Report run {report_id} not found")
    return run


@app.get("/reports/{report_id}/logs", response_model=List[ReportLogOut])
async def get_report_logs(
    report_id: int,
    db: AsyncSession = Depends(get_db),
) -> List[ReportLog]:
    run = await db.get(ReportRun, report_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Report run {report_id} not found")
    stmt = select(ReportLog).where(ReportLog.report_run_id == report_id).order_by(ReportLog.created_at)
    result = await db.execute(stmt)
    return result.scalars().all()


@app.get("/reports/{report_id}/download/pdf")
async def download_pdf(
    report_id: int,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    run = await db.get(ReportRun, report_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Report run {report_id} not found")
    if not run.output_pdf_path or not Path(run.output_pdf_path).exists():
        raise HTTPException(status_code=404, detail="PDF file not available")
    return FileResponse(
        path=run.output_pdf_path,
        media_type="application/pdf",
        filename=Path(run.output_pdf_path).name,
    )


@app.get("/reports/{report_id}/download/excel")
async def download_excel(
    report_id: int,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    run = await db.get(ReportRun, report_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Report run {report_id} not found")
    if not run.output_excel_path or not Path(run.output_excel_path).exists():
        raise HTTPException(status_code=404, detail="Excel file not available")
    return FileResponse(
        path=run.output_excel_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=Path(run.output_excel_path).name,
    )


# ---------------------------------------------------------------------------
# Data sources endpoints
# ---------------------------------------------------------------------------

@app.get("/sources", response_model=List[DataSourceOut])
async def list_sources(
    db: AsyncSession = Depends(get_db),
) -> List[DataSource]:
    result = await db.execute(select(DataSource).order_by(DataSource.name))
    return result.scalars().all()


@app.post("/sources", response_model=DataSourceOut, status_code=status.HTTP_201_CREATED)
async def create_source(
    payload: DataSourceCreate,
    db: AsyncSession = Depends(get_db),
) -> DataSource:
    source = DataSource(**payload.model_dump())
    db.add(source)
    await db.flush()
    await db.refresh(source)
    return source


@app.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    source_id: int,
    db: AsyncSession = Depends(get_db),
) -> None:
    source = await db.get(DataSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail=f"DataSource {source_id} not found")
    await db.delete(source)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.get("/dashboard/stats")
async def dashboard_stats(
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Aggregate stats for the dashboard."""
    total_stmt = select(func.count(ReportRun.id))
    completed_stmt = select(func.count(ReportRun.id)).where(
        ReportRun.status == ReportStatus.completed
    )
    failed_stmt = select(func.count(ReportRun.id)).where(
        ReportRun.status == ReportStatus.failed
    )
    running_stmt = select(func.count(ReportRun.id)).where(
        ReportRun.status == ReportStatus.running
    )

    total = (await db.execute(total_stmt)).scalar() or 0
    completed = (await db.execute(completed_stmt)).scalar() or 0
    failed = (await db.execute(failed_stmt)).scalar() or 0
    running = (await db.execute(running_stmt)).scalar() or 0

    success_rate = round((completed / total * 100) if total > 0 else 0, 1)

    # Recent activity (last 5 runs)
    recent_stmt = (
        select(ReportRun)
        .order_by(ReportRun.created_at.desc())
        .limit(5)
    )
    recent_runs = (await db.execute(recent_stmt)).scalars().all()

    return {
        "total_runs": total,
        "completed_runs": completed,
        "failed_runs": failed,
        "running_runs": running,
        "success_rate_pct": success_rate,
        "recent_runs": [
            {
                "id": r.id,
                "report_type": r.report_type,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in recent_runs
        ],
    }


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "financial_reports", "timestamp": datetime.utcnow().isoformat()}
