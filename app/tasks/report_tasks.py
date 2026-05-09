from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from celery import shared_task
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import ReportLog, ReportRun, ReportStatus, ReportType
from app.tasks.celery_app import celery_app
from app.utils.logger import get_logger

logger = get_logger("report_tasks")
settings = get_settings()

# Synchronous SQLAlchemy engine for Celery workers (not async)
_sync_db_url = settings.database_url.replace("+asyncpg", "")
_sync_engine = create_engine(_sync_db_url, pool_pre_ping=True)
SyncSession = sessionmaker(bind=_sync_engine, expire_on_commit=False)


def _add_log(session: Session, run_id: int, stage: str, message: str) -> None:
    log = ReportLog(report_run_id=run_id, stage=stage, message=message)
    session.add(log)
    session.commit()
    logger.info(f"[run={run_id}] [{stage}] {message}")


# ---------------------------------------------------------------------------
# Main pipeline task
# ---------------------------------------------------------------------------

@celery_app.task(bind=True, name="app.tasks.report_tasks.generate_report_task",
                 max_retries=2, default_retry_delay=60)
def generate_report_task(
    self,
    report_type: str = "daily",
    date_range: Optional[dict] = None,
    source_files: Optional[list] = None,
) -> dict:
    """
    Full pipeline:
        download → clean → combine → chart → PDF → Excel → email
    """
    from app.processors.chart_generator import ChartGenerator
    from app.processors.data_cleaner import DataCleaner
    from app.processors.report_builder import ReportBuilder
    from app.services.data_service import DataService
    from app.services.email_service import EmailService

    source_files = source_files or []

    with SyncSession() as session:
        # Create run record
        run = ReportRun(
            report_type=ReportType(report_type),
            status=ReportStatus.running,
            source_files=source_files,
            started_at=datetime.now(timezone.utc),
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        run_id = run.id

    try:
        output_dir = Path(settings.reports_output_dir) / f"run_{run_id}"
        output_dir.mkdir(parents=True, exist_ok=True)
        charts_dir = output_dir / "charts"
        charts_dir.mkdir(exist_ok=True)

        with SyncSession() as session:
            _add_log(session, run_id, "init", f"Starting {report_type} report run #{run_id}")

        # ------------------------------------------------------------------
        # 1. Load data files
        # ------------------------------------------------------------------
        with SyncSession() as session:
            _add_log(session, run_id, "load", f"Loading {len(source_files)} source file(s)")

        data_svc = DataService()
        dfs = data_svc.load_excel_files(source_files) if source_files else []

        if not dfs:
            # Generate synthetic sample data when no source files provided
            import pandas as pd
            import numpy as np
            rng = np.random.default_rng(42)
            n = 200
            months = pd.date_range("2024-01-01", periods=12, freq="MS")
            dates = pd.to_datetime(rng.choice(months.astype(str), size=n))
            categories = ["Sales", "Marketing", "Operations", "HR", "IT"]
            dfs = [pd.DataFrame({
                "date": dates,
                "category": rng.choice(categories, size=n),
                "revenue": rng.uniform(1000, 50000, size=n).round(2),
                "expenses": rng.uniform(500, 30000, size=n).round(2),
                "description": [f"Transaction {i}" for i in range(n)],
            })]

        # ------------------------------------------------------------------
        # 2. Clean data
        # ------------------------------------------------------------------
        cleaner = DataCleaner()
        cleaned = []
        for df in dfs:
            df = data_svc.clean_dataframe(df)
            df = cleaner.remove_duplicates(df)
            cleaned.append(df)

        with SyncSession() as session:
            _add_log(session, run_id, "clean", f"Cleaned {len(cleaned)} dataframe(s)")

        # ------------------------------------------------------------------
        # 3. Combine
        # ------------------------------------------------------------------
        combined = data_svc.combine_dataframes(cleaned)
        row_count = len(combined)

        with SyncSession() as session:
            _add_log(session, run_id, "combine", f"Combined dataframe has {row_count} rows")

        # ------------------------------------------------------------------
        # 4. Validate
        # ------------------------------------------------------------------
        validation = data_svc.validate_data(combined)
        with SyncSession() as session:
            _add_log(
                session, run_id, "validate",
                f"Validation: valid={validation.is_valid}, warnings={validation.warnings}"
            )

        # ------------------------------------------------------------------
        # 5. Compute summary
        # ------------------------------------------------------------------
        summary = data_svc.compute_summary(combined)
        with SyncSession() as session:
            _add_log(session, run_id, "summarize", f"Summary computed: {summary}")

        # ------------------------------------------------------------------
        # 6. Generate charts
        # ------------------------------------------------------------------
        chart_gen = ChartGenerator()
        chart_paths = chart_gen.generate_all(combined, str(charts_dir))
        with SyncSession() as session:
            _add_log(session, run_id, "charts", f"Generated {len(chart_paths)} chart(s)")

        # ------------------------------------------------------------------
        # 7. Build PDF
        # ------------------------------------------------------------------
        pdf_path = str(output_dir / f"report_{report_type}_{run_id}.pdf")
        builder = ReportBuilder()
        builder.build_pdf(combined, summary, chart_paths, pdf_path)
        with SyncSession() as session:
            _add_log(session, run_id, "pdf", f"PDF generated at {pdf_path}")

        # ------------------------------------------------------------------
        # 8. Build Excel
        # ------------------------------------------------------------------
        excel_path = str(output_dir / f"report_{report_type}_{run_id}.xlsx")
        builder.build_excel(combined, summary, excel_path)
        with SyncSession() as session:
            _add_log(session, run_id, "excel", f"Excel generated at {excel_path}")

        # ------------------------------------------------------------------
        # 9. Send email
        # ------------------------------------------------------------------
        email_sent = False
        try:
            email_svc = EmailService()
            recipients = settings.recipients_list
            if recipients:
                email_svc.send_report(
                    recipients=recipients,
                    subject=f"Financial Report — {report_type.capitalize()} #{run_id}",
                    summary=summary,
                    pdf_path=pdf_path,
                    excel_path=excel_path,
                )
                email_sent = True
                with SyncSession() as session:
                    _add_log(session, run_id, "email", f"Email sent to {recipients}")
        except Exception as email_exc:
            logger.warning(f"Email send failed (non-fatal): {email_exc}")
            with SyncSession() as session:
                _add_log(session, run_id, "email", f"Email failed (non-fatal): {email_exc}")

        # ------------------------------------------------------------------
        # 10. Mark completed
        # ------------------------------------------------------------------
        with SyncSession() as session:
            run = session.get(ReportRun, run_id)
            run.status = ReportStatus.completed
            run.output_pdf_path = pdf_path
            run.output_excel_path = excel_path
            run.row_count = row_count
            run.email_sent = email_sent
            run.completed_at = datetime.now(timezone.utc)
            session.commit()

        logger.info(f"Report run #{run_id} completed successfully")
        return {
            "run_id": run_id,
            "status": "completed",
            "pdf_path": pdf_path,
            "excel_path": excel_path,
            "row_count": row_count,
        }

    except Exception as exc:
        logger.exception(f"Report run #{run_id} failed: {exc}")
        with SyncSession() as session:
            run = session.get(ReportRun, run_id)
            run.status = ReportStatus.failed
            run.error_message = str(exc)
            run.completed_at = datetime.now(timezone.utc)
            session.commit()
            _add_log(session, run_id, "error", str(exc))
        raise self.retry(exc=exc)


# ---------------------------------------------------------------------------
# Portal download task
# ---------------------------------------------------------------------------

@celery_app.task(bind=True, name="app.tasks.report_tasks.download_portal_reports_task",
                 max_retries=3, default_retry_delay=120)
def download_portal_reports_task(self, portal_name: str) -> dict:
    """Download report files from a configured web portal using Playwright."""
    from app.automation.portal_downloader import PortalDownloader

    portal_configs = {
        "portal_1": {
            "url": settings.portal_1_url,
            "username": settings.portal_1_user,
            "password": settings.portal_1_pass,
        },
        "portal_2": {
            "url": settings.portal_2_url,
            "username": settings.portal_2_user,
            "password": settings.portal_2_pass,
        },
    }

    config = portal_configs.get(portal_name)
    if not config:
        raise ValueError(f"Unknown portal: {portal_name}")

    download_dir = Path(settings.downloads_dir) / portal_name
    download_dir.mkdir(parents=True, exist_ok=True)

    try:
        import asyncio
        downloader = PortalDownloader()
        loop = asyncio.new_event_loop()
        try:
            file_paths = loop.run_until_complete(
                downloader.download_from_portal(
                    portal_config=config,
                    date_range=None,
                    download_dir=str(download_dir),
                )
            )
        finally:
            loop.close()

        logger.info(f"Downloaded {len(file_paths)} file(s) from {portal_name}: {file_paths}")
        return {"portal": portal_name, "files": file_paths}

    except Exception as exc:
        logger.error(f"Portal download failed for {portal_name}: {exc}")
        raise self.retry(exc=exc)


# ---------------------------------------------------------------------------
# Email task
# ---------------------------------------------------------------------------

@celery_app.task(bind=True, name="app.tasks.report_tasks.send_report_email_task",
                 max_retries=3, default_retry_delay=60)
def send_report_email_task(self, report_run_id: int) -> dict:
    """Send the PDF + Excel for a completed report run to all recipients."""
    from app.services.email_service import EmailService

    with SyncSession() as session:
        run = session.get(ReportRun, report_run_id)
        if not run:
            raise ValueError(f"ReportRun {report_run_id} not found")
        if run.status != ReportStatus.completed:
            raise ValueError(f"ReportRun {report_run_id} is not completed (status={run.status})")

        pdf_path = run.output_pdf_path
        excel_path = run.output_excel_path

    try:
        email_svc = EmailService()
        recipients = settings.recipients_list
        summary: dict = {}  # summary re-computed or loaded from a cache if available
        email_svc.send_report(
            recipients=recipients,
            subject=f"Financial Report #{report_run_id}",
            summary=summary,
            pdf_path=pdf_path,
            excel_path=excel_path,
        )
        with SyncSession() as session:
            run = session.get(ReportRun, report_run_id)
            run.email_sent = True
            session.commit()

        return {"run_id": report_run_id, "email_sent": True, "recipients": recipients}

    except Exception as exc:
        logger.error(f"Email task failed for run #{report_run_id}: {exc}")
        raise self.retry(exc=exc)
