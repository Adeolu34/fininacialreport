from __future__ import annotations

import mimetypes
import os
import smtplib
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Environment, BaseLoader

from app.config import get_settings
from app.utils.logger import get_logger
from app.utils.retry import sync_retry

logger = get_logger("email_service")
settings = get_settings()


# ---------------------------------------------------------------------------
# Jinja2 HTML email template
# ---------------------------------------------------------------------------

_EMAIL_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Financial Report</title>
  <style>
    body { font-family: 'Segoe UI', Arial, sans-serif; background: #f4f6f9; margin: 0; padding: 0; }
    .wrapper { max-width: 680px; margin: 30px auto; background: #ffffff;
               border-radius: 8px; overflow: hidden;
               box-shadow: 0 2px 12px rgba(0,0,0,0.08); }
    .header { background: linear-gradient(135deg, #1e3a5f 0%, #2563eb 100%);
              padding: 32px 40px; text-align: center; }
    .header h1 { color: #ffffff; margin: 0; font-size: 24px; font-weight: 700; }
    .header p { color: rgba(255,255,255,0.8); margin: 8px 0 0; font-size: 14px; }
    .body { padding: 32px 40px; }
    .body h2 { color: #1e3a5f; font-size: 18px; border-bottom: 2px solid #e5e7eb;
               padding-bottom: 8px; margin-top: 0; }
    .kpi-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 20px 0; }
    .kpi-card { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px;
                padding: 18px 20px; text-align: center; }
    .kpi-card .label { font-size: 12px; color: #64748b; text-transform: uppercase;
                       letter-spacing: 0.5px; margin-bottom: 6px; }
    .kpi-card .value { font-size: 22px; font-weight: 700; color: #1e3a5f; }
    .kpi-card.profit .value { color: {% if summary.net_profit >= 0 %}#16a34a{% else %}#dc2626{% endif %}; }
    .categories { width: 100%; border-collapse: collapse; margin-top: 16px; }
    .categories th { background: #1e3a5f; color: white; padding: 10px 14px;
                     text-align: left; font-size: 13px; }
    .categories td { padding: 9px 14px; border-bottom: 1px solid #f1f5f9;
                     font-size: 13px; color: #374151; }
    .categories tr:nth-child(even) td { background: #f8fafc; }
    .attachments { background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 6px;
                   padding: 14px 18px; margin-top: 24px; }
    .attachments h3 { margin: 0 0 8px; color: #1d4ed8; font-size: 14px; }
    .attachments p { margin: 4px 0; font-size: 13px; color: #374151; }
    .footer { background: #f8fafc; border-top: 1px solid #e5e7eb;
              padding: 18px 40px; text-align: center; }
    .footer p { color: #9ca3af; font-size: 12px; margin: 4px 0; }
  </style>
</head>
<body>
  <div class="wrapper">
    <div class="header">
      <h1>Financial Report</h1>
      <p>Generated {{ generated_at }}</p>
    </div>
    <div class="body">
      <h2>Executive Summary</h2>
      <div class="kpi-grid">
        <div class="kpi-card">
          <div class="label">Total Revenue</div>
          <div class="value">${{ "{:,.2f}".format(summary.total_revenue) }}</div>
        </div>
        <div class="kpi-card">
          <div class="label">Total Expenses</div>
          <div class="value">${{ "{:,.2f}".format(summary.total_expenses) }}</div>
        </div>
        <div class="kpi-card profit">
          <div class="label">Net Profit</div>
          <div class="value">${{ "{:,.2f}".format(summary.net_profit) }}</div>
        </div>
        <div class="kpi-card">
          <div class="label">Profit Margin</div>
          <div class="value">{{ "{:.1f}".format(summary.profit_margin_pct) }}%</div>
        </div>
      </div>

      {% if summary.top_categories %}
      <h2>Top Categories by Revenue</h2>
      <table class="categories">
        <thead>
          <tr><th>Category</th><th>Revenue</th></tr>
        </thead>
        <tbody>
          {% for cat, val in summary.top_categories.items() %}
          <tr>
            <td>{{ cat }}</td>
            <td>${{ "{:,.2f}".format(val) }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      {% endif %}

      <div class="attachments">
        <h3>📎 Attachments</h3>
        <p>• <strong>PDF Report</strong> — Full financial report with charts and data tables</p>
        <p>• <strong>Excel Workbook</strong> — Interactive data with Summary, Data, and Charts sheets</p>
      </div>
    </div>
    <div class="footer">
      <p>Financial Reporting System &mdash; Automated Analytics</p>
      <p>This is an automated message. Please do not reply directly to this email.</p>
    </div>
  </div>
</body>
</html>
"""


class _SummaryProxy:
    """Wrap a dict so Jinja2 attribute access works (``summary.key``)."""

    def __init__(self, data: dict) -> None:
        self._data = data

    def __getattr__(self, item: str) -> Any:
        return self._data.get(item, 0)


class EmailService:
    """Send financial report emails with PDF and Excel attachments."""

    def __init__(self) -> None:
        self._env = Environment(loader=BaseLoader())
        self._template = self._env.from_string(_EMAIL_TEMPLATE)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @sync_retry(exceptions=(smtplib.SMTPException, OSError), max_attempts=3, base_delay=5.0)
    def send_report(
        self,
        recipients: List[str],
        subject: str,
        summary: Dict[str, Any],
        pdf_path: Optional[str] = None,
        excel_path: Optional[str] = None,
    ) -> None:
        """
        Compose and send an HTML email with PDF + Excel attachments.

        Parameters
        ----------
        recipients : list of email addresses
        subject : email subject line
        summary : dict from DataService.compute_summary()
        pdf_path : path to the PDF report file (optional)
        excel_path : path to the Excel workbook (optional)
        """
        if not recipients:
            logger.warning("send_report called with empty recipients list — skipping")
            return

        msg = MIMEMultipart("mixed")
        msg["From"] = settings.smtp_user
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject

        # Attach HTML body
        html_body = self.build_html_body(summary)
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        # Attach PDF
        if pdf_path and Path(pdf_path).exists():
            self._attach_file(msg, pdf_path, "application/pdf")

        # Attach Excel
        if excel_path and Path(excel_path).exists():
            self._attach_file(
                msg,
                excel_path,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        # Send
        self._send_smtp(msg, recipients)
        logger.info(f"Report email sent to {recipients} — subject: '{subject}'")

    def build_html_body(self, summary: Dict[str, Any]) -> str:
        """Render the Jinja2 HTML template with the provided summary data."""
        return self._template.render(
            summary=_SummaryProxy(summary),
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M UTC"),
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _send_smtp(self, msg: MIMEMultipart, recipients: List[str]) -> None:
        host = settings.smtp_host
        port = settings.smtp_port
        user = settings.smtp_user
        password = settings.smtp_pass

        logger.debug(f"Connecting to SMTP {host}:{port}")

        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=30) as server:
                if user and password:
                    server.login(user, password)
                server.sendmail(user, recipients, msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                if user and password:
                    server.login(user, password)
                server.sendmail(user, recipients, msg.as_string())

    @staticmethod
    def _attach_file(msg: MIMEMultipart, file_path: str, mime_type: str) -> None:
        """Attach a file to the MIME message."""
        main_type, sub_type = mime_type.split("/", 1)
        with open(file_path, "rb") as fh:
            payload = MIMEBase(main_type, sub_type)
            payload.set_payload(fh.read())
        encoders.encode_base64(payload)
        payload.add_header(
            "Content-Disposition",
            "attachment",
            filename=Path(file_path).name,
        )
        msg.attach(payload)
