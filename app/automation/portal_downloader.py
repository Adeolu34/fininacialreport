from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from playwright.async_api import (
    BrowserContext,
    Download,
    Page,
    Playwright,
    async_playwright,
)

from app.config import get_settings
from app.utils.logger import get_logger
from app.utils.retry import async_retry

logger = get_logger("portal_downloader")
settings = get_settings()


class PortalDownloader:
    """
    Downloads financial report files from web portals using Playwright.

    Usage (async context manager)::

        async with PortalDownloader() as downloader:
            files = await downloader.download_from_portal(config, date_range, download_dir)

    Or call ``download_from_portal`` directly — it manages its own browser lifecycle.
    """

    def __init__(self) -> None:
        self._playwright: Optional[Playwright] = None
        self._context: Optional[BrowserContext] = None

    async def __aenter__(self) -> "PortalDownloader":
        self._playwright = await async_playwright().start()
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._context:
            await self._context.close()
        if self._playwright:
            await self._playwright.stop()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def download_from_portal(
        self,
        portal_config: Dict[str, str],
        date_range: Optional[Dict[str, str]],
        download_dir: str,
    ) -> List[str]:
        """
        Full download workflow:

        1. Launch browser
        2. Log in to the portal
        3. Navigate to the reports section
        4. Set the date range (if provided)
        5. Trigger the download
        6. Wait for the file to land in *download_dir*
        7. Return list of downloaded file paths

        Parameters
        ----------
        portal_config : dict
            Must contain ``url``, ``username``, ``password``.
        date_range : dict or None
            Optional ``{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}``.
        download_dir : str
            Directory where downloaded files will be saved.
        """
        Path(download_dir).mkdir(parents=True, exist_ok=True)
        url = portal_config.get("url", "")
        username = portal_config.get("username", "")
        password = portal_config.get("password", "")

        if not url:
            logger.error("portal_config is missing 'url'")
            return []

        logger.info(f"Starting portal download: {url}")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            context = await browser.new_context(
                accept_downloads=True,
                viewport={"width": 1280, "height": 900},
            )
            page = await context.new_page()
            downloaded_files: List[str] = []

            try:
                # Step 1: Navigate to login page
                await page.goto(url, wait_until="networkidle", timeout=30_000)
                logger.info(f"Loaded portal: {url}")

                # Step 2: Log in
                await self._login(page, username, password)

                # Step 3: Navigate to reports section
                await self._navigate_to_reports(page)

                # Step 4: Set date range if provided
                if date_range:
                    await self._set_date_range(page, date_range)

                # Step 5: Download file(s)
                file_path = await self._trigger_download(page, download_dir)
                if file_path:
                    downloaded_files.append(file_path)
                    logger.info(f"Downloaded: {file_path}")

            except Exception as exc:
                logger.error(f"Portal download failed: {exc}")
                await self._screenshot_on_failure(page, download_dir, "download_failure")
                raise
            finally:
                await context.close()
                await browser.close()

        return downloaded_files

    async def wait_for_download(self, page: Page, download_dir: str) -> str:
        """
        Wait for a download event triggered by a click or navigation,
        then save the file to *download_dir*.

        Returns the full path to the saved file.
        """
        async with page.expect_download(timeout=60_000) as download_info:
            # Caller should trigger the download click inside this context
            yield  # type: ignore[misc]

        download: Download = await download_info.value
        suggested = download.suggested_filename or f"download_{datetime.now():%Y%m%d_%H%M%S}"
        dest = str(Path(download_dir) / suggested)
        await download.save_as(dest)
        logger.info(f"Download saved to: {dest}")
        return dest

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @async_retry(exceptions=(Exception,), max_attempts=3, base_delay=2.0)
    async def _login(self, page: Page, username: str, password: str) -> None:
        """
        Generic login handler.

        Tries common selector patterns for username, password, and submit.
        Override this method for portal-specific login flows.
        """
        username_selectors = [
            'input[name="username"]',
            'input[name="email"]',
            'input[type="email"]',
            'input[id*="user"]',
            'input[placeholder*="username" i]',
            'input[placeholder*="email" i]',
        ]
        password_selectors = [
            'input[type="password"]',
            'input[name="password"]',
            'input[id*="pass"]',
        ]
        submit_selectors = [
            'button[type="submit"]',
            'input[type="submit"]',
            'button:has-text("Log in")',
            'button:has-text("Login")',
            'button:has-text("Sign in")',
            'button:has-text("Submit")',
        ]

        # Fill username
        for sel in username_selectors:
            try:
                await page.fill(sel, username, timeout=5_000)
                logger.debug(f"Filled username using selector: {sel}")
                break
            except Exception:
                continue

        # Fill password
        for sel in password_selectors:
            try:
                await page.fill(sel, password, timeout=5_000)
                logger.debug(f"Filled password using selector: {sel}")
                break
            except Exception:
                continue

        # Click submit
        for sel in submit_selectors:
            try:
                await page.click(sel, timeout=5_000)
                logger.debug(f"Clicked submit using selector: {sel}")
                break
            except Exception:
                continue

        # Wait for navigation after login
        await page.wait_for_load_state("networkidle", timeout=20_000)
        logger.info("Login completed")

    async def _navigate_to_reports(self, page: Page) -> None:
        """
        Navigate to the reports/download section.

        Tries common link texts; extend for portal-specific navigation.
        """
        report_link_texts = [
            "Reports", "Downloads", "Export", "Financial Reports",
            "Data Export", "Report Center", "Analytics",
        ]
        for text in report_link_texts:
            try:
                link = page.get_by_text(text, exact=False).first
                if await link.is_visible(timeout=3_000):
                    await link.click()
                    await page.wait_for_load_state("networkidle", timeout=15_000)
                    logger.info(f"Navigated to reports section via '{text}'")
                    return
            except Exception:
                continue

        logger.warning("Could not auto-navigate to reports; proceeding from current page")

    async def _set_date_range(
        self, page: Page, date_range: Dict[str, str]
    ) -> None:
        """Fill date-range pickers if present on the page."""
        start = date_range.get("start", "")
        end = date_range.get("end", "")

        start_selectors = [
            'input[name*="start"]',
            'input[id*="start"]',
            'input[placeholder*="start" i]',
            'input[placeholder*="from" i]',
        ]
        end_selectors = [
            'input[name*="end"]',
            'input[id*="end"]',
            'input[placeholder*="end" i]',
            'input[placeholder*="to" i]',
        ]

        if start:
            for sel in start_selectors:
                try:
                    await page.fill(sel, start, timeout=3_000)
                    logger.debug(f"Set start date '{start}' via {sel}")
                    break
                except Exception:
                    continue

        if end:
            for sel in end_selectors:
                try:
                    await page.fill(sel, end, timeout=3_000)
                    logger.debug(f"Set end date '{end}' via {sel}")
                    break
                except Exception:
                    continue

    async def _trigger_download(self, page: Page, download_dir: str) -> Optional[str]:
        """
        Find and click a download button, then capture the downloaded file.
        Returns the file path or None if download failed.
        """
        download_selectors = [
            'button:has-text("Download")',
            'button:has-text("Export")',
            'a:has-text("Download")',
            'a:has-text("Export")',
            'button[aria-label*="download" i]',
            '[data-action="download"]',
        ]

        for sel in download_selectors:
            try:
                element = page.locator(sel).first
                if await element.is_visible(timeout=3_000):
                    async with page.expect_download(timeout=60_000) as dl_info:
                        await element.click()
                    download: Download = await dl_info.value
                    suggested = (
                        download.suggested_filename
                        or f"portal_download_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
                    )
                    dest = str(Path(download_dir) / suggested)
                    await download.save_as(dest)
                    return dest
            except Exception:
                continue

        logger.warning("No download button found on page")
        return None

    async def _screenshot_on_failure(
        self, page: Page, base_dir: str, label: str
    ) -> None:
        """Capture a screenshot for debugging when an error occurs."""
        screenshots_dir = Path(settings.screenshots_dir)
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = str(screenshots_dir / f"{label}_{ts}.png")
        try:
            await page.screenshot(path=path, full_page=True)
            logger.info(f"Failure screenshot saved: {path}")
        except Exception as sc_exc:
            logger.warning(f"Could not save screenshot: {sc_exc}")
