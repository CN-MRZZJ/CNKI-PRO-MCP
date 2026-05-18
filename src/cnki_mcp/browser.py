"""Browser automation for CNKI professional search using Playwright.

CNKI anti-bot strategy (semi-automatic):
1. First run: launch visible browser → user solves CAPTCHA slider manually
2. After verification, cookies are saved to disk
3. Subsequent runs: reuse cookies in headless mode
4. When cookies expire, prompt user to re-verify
"""

import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page


# 一框式检索
CNKI_SIMPLE_SEARCH_URL = "https://kns.cnki.net/kns8s/search"
# 专业检索（保留给 cnki_professional_search 使用）
CNKI_PRO_SEARCH_URL = "https://kns.cnki.net/kns8s/AdvSearch?type=expert"

COOKIE_FILE = Path(__file__).parent.parent.parent / ".cnki_cookies.json"
CAPTCHA_TIMEOUT = 120_000


@dataclass
class SearchConfig:
    headless: bool = True
    timeout: int = 60_000
    wait_after_search: int = 3_000
    browser_channel: str = "msedge"
    cookie_file: Path = COOKIE_FILE


class CNKIBrowser:
    """Playwright browser manager for CNKI professional search."""

    def __init__(self, config: SearchConfig | None = None):
        self.config = config or SearchConfig()
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._headed = False

    async def start(self, headed: bool = False):
        """Launch browser. headed=True opens a visible window for CAPTCHA solving."""
        self._headed = headed
        self._playwright = await async_playwright().start()

        self._browser = await self._playwright.chromium.launch(
            headless=not headed,
            channel=self.config.browser_channel,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )

        self._context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="zh-CN",
        )

        # Hide automation markers
        await self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
            delete window.__playwright;
        """)

        await self._load_cookies()

    async def stop(self):
        """Save cookies and cleanup."""
        await self._save_cookies()
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def search_simple(self, query: str, field: str = "SU",
                            max_results: int = 20) -> str:
        """Execute a one-box search (一框式检索) with pagination.

        Args:
            query: Search keyword.
            field: Field code to search in (SU/TI/KY/AB/AU/FT etc.), default SU (主题).
            max_results: Max results to return.
        """
        page = await self._context.new_page()
        try:
            await self._navigate_and_pass_captcha(page, CNKI_SIMPLE_SEARCH_URL)

            # Select the search field from the dropdown
            await self._select_search_field(page, field)

            # Find the search input and fill
            await self._fill_simple_search(page, query)

            # Click search
            await self._click_search_button(page)

            # Wait for results
            await self._wait_for_results(page)

            html_parts = [await page.content()]
            pages_fetched = 1

            while pages_fetched * 20 < max_results:
                next_btn = page.locator("a:has-text('下一页')").first
                if not await next_btn.is_visible(timeout=2000):
                    break
                parent_li = next_btn.locator("..")
                parent_class = await parent_li.get_attribute("class") or ""
                if "disabled" in parent_class:
                    break
                await next_btn.click()
                try:
                    await page.wait_for_timeout(self.config.wait_after_search)
                    await self._wait_for_results(page)
                except Exception:
                    break
                html_parts.append(await page.content())
                pages_fetched += 1

            return self._merge_result_html(html_parts)
        finally:
            await page.close()

    async def search_professional(self, expression: str, max_results: int = 20) -> str:
        """Execute a professional search (专业检索) with pagination."""
        page = await self._context.new_page()
        try:
            await self._navigate_and_pass_captcha(page, CNKI_PRO_SEARCH_URL)
            await self._fill_expression(page, expression)
            await self._click_search_button(page)
            await self._wait_for_results(page)

            html_parts = [await page.content()]
            pages_fetched = 1

            # Pagination: click "下一页" until we have enough or run out
            while pages_fetched * 20 < max_results:
                next_btn = page.locator("a:has-text('下一页')").first
                if not await next_btn.is_visible(timeout=2000):
                    break

                # Check if next page is disabled (grayed out)
                parent_li = next_btn.locator("..")
                parent_class = await parent_li.get_attribute("class") or ""
                if "disabled" in parent_class:
                    break

                await next_btn.click()
                try:
                    await page.wait_for_timeout(self.config.wait_after_search)
                    await self._wait_for_results(page)
                except Exception:
                    break

                html_parts.append(await page.content())
                pages_fetched += 1

            # Combine result rows from all pages into a single HTML document
            return self._merge_result_html(html_parts)
        finally:
            await page.close()

    def _merge_result_html(self, html_parts: list[str]) -> str:
        """Extract result rows from each page's HTML and merge into one table.

        Returns the first page's HTML with all result rows combined in the
        result table, so the parser sees them as a single page of results.
        """
        from bs4 import BeautifulSoup

        if len(html_parts) == 1:
            return html_parts[0]

        base_soup = BeautifulSoup(html_parts[0], "lxml")
        base_table = base_soup.select_one("table.result-table-list")
        if not base_table:
            return html_parts[0]

        for html in html_parts[1:]:
            soup = BeautifulSoup(html, "lxml")
            t = soup.select_one("table.result-table-list")
            if t:
                for row in t.select("tr"):
                    cells = row.select("td")
                    if len(cells) >= 5 and cells[1].select_one("a"):
                        base_table.append(row)

        return str(base_soup)

    async def get_page_html(self, url: str) -> str:
        """Fetch HTML from a CNKI article detail page."""
        page = await self._context.new_page()
        try:
            await self._navigate_and_pass_captcha(page, url)
            return await page.content()
        finally:
            await page.close()

    # ── internal helpers ──────────────────────────────────────────

    async def _navigate_and_pass_captcha(self, page: Page, url: str):
        """Navigate to URL. If CAPTCHA appears and browser is headed, wait for user."""
        await page.goto(url, timeout=self.config.timeout, wait_until="domcontentloaded")
        await page.wait_for_timeout(1000)

        # Handle CAPTCHA redirect
        if "verify" in page.url or "captcha" in page.url:
            if not self._headed:
                raise RuntimeError(
                    "CNKI 需要安全验证，请先运行 headed 模式完成验证："
                    "将 headless 设为 False 重新启动"
                )
            self._notify("CNKI 需要滑块验证，请在浏览器窗口中完成验证...")
            try:
                # Wait until we're redirected back from CAPTCHA
                await page.wait_for_url(
                    lambda u: "verify" not in u and "captcha" not in u.lower(),
                    timeout=CAPTCHA_TIMEOUT,
                )
                self._notify("验证通过！继续搜索...")
            except Exception:
                raise RuntimeError(
                    f"验证超时（{CAPTCHA_TIMEOUT // 1000}秒），请重试"
                )
            # Give the page a moment to fully render after redirect
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(1000)

    async def _click_tab(self, page: Page, tab_name: str):
        """Click the professional search tab. On CNKI AdvSearch, the tab is a
        <li> containing an <a> with the tab name text."""
        # The specific structure: <li><a>专业检索</a></li> inside the search tabs
        selectors = [
            f"li a:has-text('{tab_name}')",
            f"a:has-text('{tab_name}')",
            f"li:has-text('{tab_name}')",
        ]
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=3000):
                    await el.click()
                    await page.wait_for_timeout(800)
                    return
            except Exception:
                continue
        self._notify(f"警告：未找到'{tab_name}'标签，尝试继续...")

    async def _select_search_field(self, page: Page, field_code: str):
        """Select the search field from the dropdown next to the search box.

        Visible trigger: div.sort-default > span (shows current field name)
        Hidden dropdown: div.sort-list > ul > li[data-val] (field options)
        """
        if field_code == "SU":
            return  # Default, no need to change

        # Open the dropdown by clicking the visible trigger
        trigger = page.locator(".sort-default").first
        if await trigger.is_visible(timeout=2000):
            await trigger.click()
            await page.wait_for_timeout(400)

        # Click the target option in the dropdown
        target = page.locator(f".sort-list li[data-val='{field_code}']").first
        try:
            await target.click(force=True, timeout=3000)
            await page.wait_for_timeout(300)
        except Exception:
            self._notify(f"警告：未找到字段 '{field_code}'，使用默认字段")

    async def _fill_simple_search(self, page: Page, query: str):
        """Find the one-box search input and fill the query."""
        selectors = [
            "textarea#txt_SearchText",
            "input#txt_SearchText",
            "textarea.search-input",
            "input.search-input",
            "input[name='txt_SearchText']",
        ]
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=3000):
                    await el.click()
                    await el.fill("")
                    await el.type(query, delay=30)
                    return
            except Exception:
                continue

        # Fallback: any visible textarea or text input
        for tag in ["textarea:visible", "input[type='text']:visible"]:
            els = page.locator(tag)
            count = await els.count()
            for i in range(count):
                el = els.nth(i)
                try:
                    if await el.is_visible():
                        await el.click()
                        await el.fill("")
                        await el.fill(query)
                        return
                except Exception:
                    continue
        raise RuntimeError("找不到一框式检索输入框")

    async def _fill_expression(self, page: Page, expression: str):
        """Find the professional search textarea. It has class 'textarea-major'
        and becomes visible only after clicking the 专业检索 tab."""
        selectors = [
            "textarea.textarea-major",
            "textarea.majorSearch",
            "textarea[id*='Search']",
            "textarea[class*='major']",
            "textarea:visible",
        ]
        for sel in selectors:
            try:
                ta = page.locator(sel).first
                if await ta.is_visible(timeout=5000):
                    await ta.click()
                    await ta.fill("")
                    # Type with slight delay to trigger any autocomplete listeners
                    await ta.type(expression, delay=30)
                    return
            except Exception:
                continue
        raise RuntimeError("找不到专业检索表达式输入框，页面结构可能已变更")

    async def _click_search_button(self, page: Page):
        """Click the search button. CNKI has input.btn-search and input.search-btn."""
        selectors = [
            "input.btn-search",
            "input.search-btn",
            "input[value='检索']",
            "button:has-text('检索')",
        ]
        for sel in selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=2000):
                    await btn.click()
                    return
            except Exception:
                continue
        await page.keyboard.press("Enter")

    async def _wait_for_results(self, page: Page):
        """Wait for search results to appear."""
        await page.wait_for_timeout(self.config.wait_after_search)

        selectors = [
            ".result-table-list",
            "table.result-table",
            ".search-result-list",
            "tr[class*='result']",
            "td.essayTitle",
            "a[href*='detail']",
        ]
        for sel in selectors:
            try:
                await page.wait_for_selector(sel, timeout=15_000)
                return
            except Exception:
                continue

        await page.wait_for_timeout(5_000)

    def _notify(self, msg: str):
        """Print a notification that the user can see even in MCP context."""
        print(msg, file=sys.stderr, flush=True)

    async def _save_cookies(self):
        """Persist cookies to disk."""
        if self._context:
            try:
                cookies = await self._context.cookies()
                self.config.cookie_file.parent.mkdir(parents=True, exist_ok=True)
                self.config.cookie_file.write_text(
                    json.dumps(cookies, ensure_ascii=False, indent=2)
                )
            except Exception:
                pass

    async def _load_cookies(self):
        """Load saved cookies from disk."""
        if self.config.cookie_file.exists():
            try:
                cookies = json.loads(self.config.cookie_file.read_text())
                await self._context.add_cookies(cookies)
            except Exception:
                pass
