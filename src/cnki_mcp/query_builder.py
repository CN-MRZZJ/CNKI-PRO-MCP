"""Construct CNKI professional search expressions from structured parameters.

Based on CNKI professional search syntax documented in 检索说明.html section 1.1.3.

Format: <field_code><match_operator><search_value>
Logical: AND, OR, NOT (space-separated)
Compound within field: * (AND), + (OR), - (NOT)
Comparison: YE BETWEEN ('y1', 'y2'), CF > 0
"""

import re
from typing import Optional

# Field code mappings
FIELDS = {
    "SU": "主题",
    "TKA": "篇关摘",
    "KY": "关键词",
    "TI": "篇名",
    "FT": "全文",
    "AU": "作者",
    "FI": "第一作者",
    "RP": "通讯作者",
    "AF": "作者单位",
    "FU": "基金",
    "AB": "摘要",
    "CO": "小标题",
    "RF": "参考文献",
    "CLC": "分类号",
    "LY": "文献来源",
    "DOI": "DOI",
    "CF": "被引频次",
    "YE": "年份",
}

# Which match operator to use per field
# = : exact or contains-complete
# % : fuzzy / contains parts
# %= : relevance match (SU only)
MATCH_OPERATORS = {
    "SU": "%=",   # relevance match
    "TKA": "=",
    "KY": "=",    # exact
    "TI": "%",    # fuzzy (includes word segments)
    "FT": "%",
    "AU": "=",    # exact
    "FI": "=",
    "RP": "=",
    "AF": "%",    # fuzzy
    "FU": "%",
    "AB": "%",
    "CO": "=",
    "RF": "=",
    "CLC": "%=",
    "LY": "=",
    "DOI": "=",
    "CF": "=",
    "YE": "=",
}


def _escape_value(value: str) -> str:
    """Wrap value in single quotes, escaping internal single quotes."""
    escaped = value.replace("'", "\\'")
    return f"'{escaped}'"


def _build_field_expr(field_code: str, value: str, match_op: Optional[str] = None) -> str:
    """Build a single field expression like `SU %= '人工智能'`.

    If value contains * / + / - we treat them as compound operators and
    wrap each segment appropriately.
    """
    if match_op is None:
        match_op = MATCH_OPERATORS.get(field_code, "=")

    # Check for compound operators within the value
    if re.search(r'[*+\-]', value) and field_code != "YE":
        # Has compound operators - escape each segment
        segments = re.split(r'(\s*[*+\-]\s*)', value)
        parts = []
        for seg in segments:
            seg_stripped = seg.strip()
            if seg_stripped in ("*", "+", "-"):
                parts.append(f" {seg_stripped} ")
            elif seg_stripped:
                parts.append(_escape_value(seg_stripped))
        return f"{field_code} {match_op} {''.join(parts)}"
    else:
        return f"{field_code} {match_op} {_escape_value(value)}"


def build_expression(
    query: str = "",
    *,
    field: str = "SU",
    author: str = "",
    organization: str = "",
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    fund: str = "",
    source: str = "",
    keyword: str = "",
    title: str = "",
    abstract: str = "",
    fulltext: str = "",
    min_citations: Optional[int] = None,
) -> str:
    """Build a CNKI professional search expression.

    Args:
        query: Main search query (used with the field parameter, defaults to theme/SU)
        field: Which field to apply the main query to (SU=theme, TI=title, KY=keyword, etc.)
        author: Filter by author name
        organization: Filter by author affiliation
        year_from: Start year (inclusive)
        year_to: End year (inclusive)
        fund: Filter by funding source
        source: Filter by publication source name
        keyword: Additional keyword filter
        title: Additional title filter
        abstract: Additional abstract filter
        fulltext: Additional fulltext filter
        min_citations: Minimum citation count

    Returns:
        A CNKI professional search expression string.
    """
    parts = []

    # Main query
    if query:
        parts.append(_build_field_expr(field, query))

    # Structured filters
    if keyword:
        parts.append(_build_field_expr("KY", keyword))
    if title:
        parts.append(_build_field_expr("TI", title))
    if abstract:
        parts.append(_build_field_expr("AB", abstract))
    if fulltext:
        parts.append(_build_field_expr("FT", fulltext))
    if author:
        parts.append(_build_field_expr("AU", author))
    if organization:
        parts.append(_build_field_expr("AF", organization))
    if fund:
        parts.append(_build_field_expr("FU", fund))
    if source:
        parts.append(_build_field_expr("LY", source))

    # Year range
    if year_from and year_to:
        parts.append(f"YE BETWEEN ('{year_from}', '{year_to}')")
    elif year_from:
        parts.append(f"YE >= '{year_from}'")
    elif year_to:
        parts.append(f"YE <= '{year_to}'")

    # Citation count
    if min_citations is not None:
        parts.append(f"CF >= {min_citations}")

    if not parts:
        return ""

    return " AND ".join(parts)


# Labels that introduce a new field in natural language queries
_FIELD_LABEL = r"作者|第一作者|通讯作者|单位|机构|关键词|篇名|标题|摘要|全文|基金|来源|期刊|分类号|DOI|AU|FI|RP|AF|KY|TI|AB|FT|FU|LY|CLC"


def _build_field_lookahead() -> str:
    """Pattern that matches up to the next field label or separator or end."""
    return rf"(?=\s*(?:{_FIELD_LABEL})[：:]|\s*[,，;；]|$)"


def parse_natural_query(text: str) -> dict:
    """Extract structured search parameters from a natural language query.

    Recognizes patterns like:
    - "作者:张三" or "作者：张三"
    - "单位:清华大学" or "机构:清华大学"
    - "关键词:人工智能" or "关键词：人工智能"
    - "2020-2024" or "2020年到2024年"
    - "被引>10" or "引用>10"
    - "基金:国家自然科学基金"
    - "期刊:计算机学报" or "来源:计算机学报"
    """
    params: dict = {"query": text.strip()}

    # Extract field:value patterns — use lookahead to stop at next field label
    lookahead = _build_field_lookahead()
    field_patterns = [
        (rf"(?:作者|AU)[：:]\s*(.+?){lookahead}", "author"),
        (rf"(?:第一作者|FI)[：:]\s*(.+?){lookahead}", "first_author"),
        (rf"(?:通讯作者|RP)[：:]\s*(.+?){lookahead}", "corresponding_author"),
        (rf"(?:单位|机构|AF)[：:]\s*(.+?){lookahead}", "organization"),
        (rf"(?:关键词|KY)[：:]\s*(.+?){lookahead}", "keyword"),
        (rf"(?:篇名|标题|TI)[：:]\s*(.+?){lookahead}", "title"),
        (rf"(?:摘要|AB)[：:]\s*(.+?){lookahead}", "abstract"),
        (rf"(?:全文|FT)[：:]\s*(.+?){lookahead}", "fulltext"),
        (rf"(?:基金|FU)[：:]\s*(.+?){lookahead}", "fund"),
        (rf"(?:来源|期刊|LY)[：:]\s*(.+?){lookahead}", "source"),
        (rf"(?:分类号|CLC)[：:]\s*(.+?){lookahead}", "classification"),
    ]

    remaining = text
    for pattern, key in field_patterns:
        match = re.search(pattern, remaining)
        if match:
            val = match.group(1).strip()
            if val:
                params[key] = val
            remaining = remaining[:match.start()] + remaining[match.end():]

    # Remove common connector words and clean up
    remaining = re.sub(r'\s*[,，;；]\s*', ' ', remaining)
    remaining = re.sub(r'\s+', ' ', remaining).strip(',，;； ')

    if remaining and remaining != text.strip():
        params["query"] = remaining
    elif not any(k in params for k in ["author", "first_author", "corresponding_author",
                                         "keyword", "title", "abstract", "fulltext",
                                         "organization", "fund", "source", "classification"]):
        params["query"] = text.strip()
    else:
        params["query"] = remaining if remaining else ""

    # Extract year range
    year_range = re.search(r'(\d{4})\s*[-~到至]\s*(\d{4})', text)
    if year_range:
        params["year_from"] = int(year_range.group(1))
        params["year_to"] = int(year_range.group(2))

    # Extract citation threshold
    cite_match = re.search(r'(?:被引|引用|CF)\s*[>≥]\s*(\d+)', text)
    if cite_match:
        params["min_citations"] = int(cite_match.group(1))

    return {k: v for k, v in params.items() if v}
