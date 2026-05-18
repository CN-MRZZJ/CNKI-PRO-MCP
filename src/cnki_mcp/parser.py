"""Parse CNKI search result HTML into structured data.

CNKI professional search results use a table with class 'result-table-list'.
Each row (tr) represents one article with the following td layout:
  td[0]: 序号 (sequence number)
  td[1]: 题名 (title) — includes link, may have badges like 网络首发/免费
  td[2]: 作者 (authors) — semicolon-separated
  td[3]: 来源 (source) — journal name
  td[4]: 发表时间 (publication date)
  td[5]: 数据库 (database) — 期刊/博士/硕士/会议 etc.
  td[6]: 被引 (citation count)
  td[7]: 下载 (download count)
  td[8]: 操作 (operations — export, collect, etc.)
"""

import re
from typing import Optional

from bs4 import BeautifulSoup, Tag


def _clean(text: str) -> str:
    """Collapse whitespace and strip."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def _extract_text(tag: Optional[Tag], default: str = "") -> str:
    """Safely extract cleaned text from a BeautifulSoup tag."""
    return _clean(tag.get_text()) if tag else default


def parse_search_results(html: str) -> list[dict]:
    """Parse CNKI search result HTML into a list of article dicts.

    Each article dict: title, url, authors, source, date, database,
                      citation_count, download_count.
    """
    soup = BeautifulSoup(html, "lxml")
    results = []

    # Main result table
    table = soup.select_one("table.result-table-list")
    if not table:
        return _fallback_parse(soup)

    rows = table.select("tr")
    for row in rows:
        cells = row.select("td")
        if len(cells) < 5:
            continue

        article = _extract_article(cells)
        if article:
            results.append(article)

    if not results:
        return _fallback_parse(soup)
    return results


def _extract_article(cells: list[Tag]) -> Optional[dict]:
    """Extract article info from a result table row."""
    # -- Title (td[1]) --
    title_cell = cells[1] if len(cells) > 1 else None
    if not title_cell:
        return None

    link = title_cell.select_one("a")
    if not link:
        return None

    title = _clean(link.get_text())
    if not title or len(title) < 2:
        return None

    href = link.get("href", "")
    if href and not href.startswith("http"):
        href = "https://kns.cnki.net" + href

    # -- Authors (td[2]) — semicolon-separated --
    authors_raw = _extract_text(cells[2]) if len(cells) > 2 else ""
    # Remove "网络首发" "免费" etc. badges that sometimes bleed into author field
    authors_raw = re.sub(r'网络首发|免费|增强出版|优先出版', '', authors_raw).strip()
    authors = [a.strip() for a in re.split(r'[;；]', authors_raw) if a.strip()]

    # -- Source (td[3]) --
    source = _extract_text(cells[3]) if len(cells) > 3 else ""

    # -- Date (td[4]) --
    date_str = _extract_text(cells[4]) if len(cells) > 4 else ""

    # -- Database (td[5]) --
    database = _extract_text(cells[5]) if len(cells) > 5 else ""

    # -- Citations (td[6]) --
    citations = _extract_text(cells[6]) if len(cells) > 6 else ""

    # -- Downloads (td[7]) --
    downloads = _extract_text(cells[7]) if len(cells) > 7 else ""

    # Clean title badges
    title_clean = re.sub(r'网络首发|免费|增强出版|优先出版', '', title).strip()

    return {
        "title": title_clean,
        "url": href,
        "authors": authors,
        "source": source,
        "date": date_str,
        "database": database,
        "citation_count": citations,
        "download_count": downloads,
    }


def _fallback_parse(soup: BeautifulSoup) -> list[dict]:
    """Fallback: extract linked titles from any page structure."""
    results = []
    seen_titles = set()

    for link in soup.select("a[href]"):
        title = _clean(link.get_text())
        href = link.get("href", "")

        if not title or len(title) < 5:
            continue
        if title in seen_titles:
            continue

        is_article_link = any(
            kw in href for kw in ("/kcms2/", "/detail/", "Article", "dbcode", "filename")
        )
        if is_article_link:
            seen_titles.add(title)
            if not href.startswith("http"):
                href = "https://kns.cnki.net" + href
            results.append({
                "title": re.sub(r'网络首发|免费|增强出版|优先出版', '', title).strip(),
                "url": href,
                "authors": [],
                "source": "",
                "date": "",
                "database": "",
                "citation_count": "",
                "download_count": "",
            })

    return results


def parse_article_detail(html: str) -> dict:
    """Parse CNKI article detail page into structured data."""
    soup = BeautifulSoup(html, "lxml")
    result = {}

    # Title
    for sel in ["h1", ".title", "[class*='title']"]:
        tag = soup.select_one(sel)
        if tag:
            result["title"] = _clean(tag.get_text())
            break

    # Authors
    author_tags = soup.select("[class*='author'] a, .author a, a[href*='author']")
    if author_tags:
        result["authors"] = [_clean(a.get_text()) for a in author_tags]

    # Abstract
    for sel in ["[class*='abstract']", "#abstract", ".abstract"]:
        tag = soup.select_one(sel)
        if tag:
            result["abstract"] = _clean(tag.get_text())
            break

    # Keywords
    kw_tags = soup.select("[class*='keyword'] a, .keywords a")
    if kw_tags:
        result["keywords"] = [_clean(k.get_text()) for k in kw_tags]

    # DOI
    doi_tag = soup.select_one("a[href*='doi.org'], [class*='doi']")
    if doi_tag:
        result["doi"] = _clean(doi_tag.get_text())

    # Source info
    for sel in ["[class*='source']", "[class*='journal']"]:
        tag = soup.select_one(sel)
        if tag:
            result["source"] = _clean(tag.get_text())
            break

    return result
