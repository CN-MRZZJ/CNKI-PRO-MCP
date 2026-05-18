"""CNKI MCP Server.

Provides tools for searching CNKI (China National Knowledge Infrastructure):
- cnki_search: Search with natural language, auto-builds professional expression
- cnki_professional_search: Search with raw CNKI professional syntax
- cnki_get_article: Get article detail by URL
"""

import json
import os
import logging
from typing import Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .browser import CNKIBrowser, SearchConfig
from .parser import parse_search_results, parse_article_detail
from .query_builder import build_expression, parse_natural_query

logger = logging.getLogger(__name__)

app = Server("cnki-mcp")

_browser: Optional[CNKIBrowser] = None


async def get_browser() -> CNKIBrowser:
    global _browser
    if _browser is None:
        headed = os.environ.get("CNKI_HEADED", "").lower() in ("1", "true", "yes")
        _browser = CNKIBrowser(SearchConfig(headless=not headed))
        await _browser.start(headed=headed)
    return _browser


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="cnki_search",
            description=(
                "搜索知网CNKI学术文献。支持自然语言描述搜索需求，自动构造专业检索表达式。"
                "适用于：主题搜索、关键词搜索、作者搜索、机构搜索、年份筛选等。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "搜索内容描述。可以是简单的关键词（如'人工智能'），"
                            "也可以是带修饰的描述（如'作者:张三 关键词:机器学习 2020-2024'）。"
                            "支持的修饰字段：作者:、关键词:、单位:、基金:、来源:、篇名:、摘要:"
                        ),
                    },
                    "author": {
                        "type": "string",
                        "description": "按作者筛选",
                    },
                    "organization": {
                        "type": "string",
                        "description": "按作者单位筛选",
                    },
                    "keyword": {
                        "type": "string",
                        "description": "按关键词筛选",
                    },
                    "year_from": {
                        "type": "integer",
                        "description": "起始年份（含）",
                    },
                    "year_to": {
                        "type": "integer",
                        "description": "结束年份（含）",
                    },
                    "fund": {
                        "type": "string",
                        "description": "按基金筛选",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "最大返回结果数，默认20",
                        "default": 20,
                    },
                    "field": {
                        "type": "string",
                        "description": (
                            "一框式检索的搜索字段。可选：SU(主题,默认)、TI(篇名)、"
                            "KY(关键词)、AB(摘要)、FT(全文)、AU(作者)、"
                            "AF(作者单位)、FU(基金)、LY(文献来源)、TKA(篇关摘)"
                        ),
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="cnki_professional_search",
            description=(
                "使用CNKI专业检索语法直接搜索。适用于了解CNKI专业检索表达式的用户。"
                "格式：<字段代码><匹配运算符><检索值>，用AND/OR/NOT连接。"
                "例如：SU %= '人工智能' AND YE BETWEEN ('2020', '2024')"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "CNKI专业检索表达式",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "最大返回结果数，默认20",
                        "default": 20,
                    },
                },
                "required": ["expression"],
            },
        ),
        Tool(
            name="cnki_syntax_guide",
            description=(
                "获取CNKI专业检索表达式的完整语法参考。"
                "在构造复杂检索表达式之前，先调用此工具获取字段代码、匹配运算符、"
                "逻辑运算符、比较运算符、位置描述符等完整说明。"
            ),
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="cnki_get_article",
            description="获取知网文章详细信息。输入文章URL，返回标题、作者、摘要、关键词等。",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "知网文章详情页URL",
                    },
                },
                "required": ["url"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "cnki_search":
            result = await handle_cnki_search(arguments)
        elif name == "cnki_professional_search":
            result = await handle_professional_search(arguments)
        elif name == "cnki_syntax_guide":
            result = handle_syntax_guide()
        elif name == "cnki_get_article":
            result = await handle_get_article(arguments)
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
    except Exception as e:
        logger.exception(f"Error in tool {name}")
        return [TextContent(type="text", text=json.dumps({
            "error": str(e),
            "tool": name,
        }, ensure_ascii=False, indent=2))]


async def handle_cnki_search(args: dict) -> dict:
    """Handle the cnki_search tool — uses one-box search for simple queries,
    falls back to professional search when structured filters are provided."""
    query = args.get("query", "")
    author = args.get("author", "")
    organization = args.get("organization", "")
    keyword = args.get("keyword", "")
    year_from = args.get("year_from")
    year_to = args.get("year_to")
    fund = args.get("fund", "")
    max_results = args.get("max_results", 20)
    field = args.get("field", "SU")

    # Parse natural language hints from the query string
    parsed = parse_natural_query(query)

    final_author = author or parsed.get("author", "")
    final_org = organization or parsed.get("organization", "")
    final_keyword = keyword or parsed.get("keyword", "")
    final_fund = fund or parsed.get("fund", "")
    final_year_from = year_from or parsed.get("year_from")
    final_year_to = year_to or parsed.get("year_to")
    final_query = parsed.get("query", query)

    has_filters = any([final_author, final_org, final_keyword, final_fund,
                       final_year_from, final_year_to])

    browser = await get_browser()

    if has_filters:
        # Build professional expression for structured queries
        expression = build_expression(
            query=final_query,
            author=final_author,
            organization=final_org,
            keyword=final_keyword,
            year_from=final_year_from,
            year_to=final_year_to,
            fund=final_fund,
        )
        html = await browser.search_professional(expression, max_results)
    else:
        # Use one-box search for simple keyword queries
        html = await browser.search_simple(final_query, field, max_results)
        expression = f"一框式检索 [{field}]: {final_query}"

    results = parse_search_results(html)

    # Limit results
    if len(results) > max_results:
        results = results[:max_results]

    return {
        "expression": expression,
        "total_results": len(results),
        "results": results,
    }


async def handle_professional_search(args: dict) -> dict:
    """Handle the cnki_professional_search tool."""
    expression = args.get("expression", "")
    max_results = args.get("max_results", 20)

    if not expression.strip():
        return {"error": "expression is required", "results": []}

    browser = await get_browser()
    html = await browser.search_professional(expression, max_results)
    results = parse_search_results(html)

    if len(results) > max_results:
        results = results[:max_results]

    return {
        "expression": expression,
        "total_results": len(results),
        "results": results,
    }


def handle_syntax_guide() -> dict:
    """Return the full CNKI professional search syntax reference."""
    return {
        "format": "<字段代码><匹配运算符><检索值> [<逻辑运算符> <字段代码><匹配运算符><检索值> ...]",
        "field_codes": {
            "SU": {"name": "主题", "recommended_op": "%="},
            "TKA": {"name": "篇关摘", "recommended_op": "="},
            "KY": {"name": "关键词", "recommended_op": "="},
            "TI": {"name": "篇名", "recommended_op": "%"},
            "FT": {"name": "全文", "recommended_op": "%"},
            "AU": {"name": "作者", "recommended_op": "="},
            "FI": {"name": "第一作者", "recommended_op": "="},
            "RP": {"name": "通讯作者", "recommended_op": "="},
            "AF": {"name": "作者单位", "recommended_op": "%"},
            "FU": {"name": "基金", "recommended_op": "%"},
            "AB": {"name": "摘要", "recommended_op": "%"},
            "CO": {"name": "小标题", "recommended_op": "="},
            "RF": {"name": "参考文献", "recommended_op": "="},
            "CLC": {"name": "分类号", "recommended_op": "%="},
            "LY": {"name": "文献来源", "recommended_op": "="},
            "DOI": {"name": "DOI", "recommended_op": "="},
            "CF": {"name": "被引频次", "recommended_op": "="},
            "YE": {"name": "年份", "recommended_op": "="},
        },
        "match_operators": {
            "=": "精确匹配：KY/AU/FI/RP/AF/FU/CLC 中表示等于检索值；TI/AB/FT/RF 中表示包含完整检索值",
            "%": "模糊匹配：包含检索值及其分词（不计顺序和间隔）；CLC 中表示前缀匹配",
            "%=": "相关匹配：用于 SU（主题）字段，表示与检索值相关的文献",
        },
        "comparison_operators": {
            "BETWEEN": "YE BETWEEN ('2020', '2024') — 年份在2020到2024之间",
            ">": "大于，用于 YE 和 CF",
            "<": "小于，用于 YE 和 CF",
            ">=": "大于等于，用于 YE 和 CF",
            "<=": "小于等于，用于 YE 和 CF",
        },
        "logical_operators": {
            "AND": "逻辑与（前后留空格）",
            "OR": "逻辑或（前后留空格）",
            "NOT": "逻辑非（前后留空格）",
        },
        "compound_operators": {
            "*": "同字段内 AND，如 KY = '铝合金' * '钛合金'",
            "+": "同字段内 OR，如 KY = '大数据' + '数据挖掘'",
            "-": "同字段内 NOT，如 KY = '大数据' - '人工智能'",
        },
        "position_descriptors": {
            "#": "同一句中包含两个词，如 FT = '人工智能 # 推荐算法'",
            "%": "同一句中，前词在后词之前，如 FT = '人工智能 % 推荐算法'",
            "/NEAR N": "同一句中间隔不超过N个字词，如 FT = '人工智能 /NEAR 10 推荐算法'",
            "/PREV N": "同一句中前词在前不超过N字，如 FT = '人工智能 /PREV 10 推荐算法'",
            "/AFT N": "同一句中前词在后且超过N字，如 FT = '人工智能 /AFT 10 推荐算法'",
            "/SEN N": "同一段中句子序号差≤N，如 FT = '人工智能 /SEN 1 推荐算法'",
            "/PRG N": "间隔不超过N段，如 FT = '出版 /PRG 5 法规'",
            "$ N": "检索词至少出现N次，如 FT = '大数据 $5'",
        },
        "notes": [
            "检索值用英文半角单引号括起，如 '人工智能'",
            "逻辑运算符 AND/OR/NOT 前后需各空一个字节",
            "运算符优先级用英文半角圆括号 () 确定",
            "检索值含特殊符号（* + - / % = 空格等）时必须用引号括起",
            "位置描述符仅限两个检索值，不支持连接多值",
            "位置描述符整体需用单引号括起：FT = '人工智能 /NEAR 10 推荐算法'",
        ],
        "examples": [
            "SU %= '人工智能' AND YE BETWEEN ('2020', '2024')",
            "AU = '钱伟长' AND (AF = '清华大学' OR AF = '上海大学')",
            "KY = '知识管理' AND AU = '邱均平'",
            "TI = '大数据' NOT TI = '大数据集'",
            "FT = '催化剂' * '反应率'",
            "KY = '铝合金' + '钛合金'",
            "CF >= 1 AND SU %= '机器学习'",
        ],
    }


async def handle_get_article(args: dict) -> dict:
    """Handle the cnki_get_article tool."""
    url = args.get("url", "")
    if not url.strip():
        return {"error": "url is required"}

    browser = await get_browser()
    html = await browser.get_page_html(url)
    detail = parse_article_detail(html)

    return detail


async def main():
    """Entry point for the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def run():
    """Sync wrapper for the async main."""
    import asyncio
    asyncio.run(main())


if __name__ == "__main__":
    run()
