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
    """Handle the cnki_search tool."""
    query = args.get("query", "")
    author = args.get("author", "")
    organization = args.get("organization", "")
    keyword = args.get("keyword", "")
    year_from = args.get("year_from")
    year_to = args.get("year_to")
    fund = args.get("fund", "")
    max_results = args.get("max_results", 20)

    # Try to parse structured data from the query string
    parsed = parse_natural_query(query)

    # Explicit params override parsed ones
    final_query = parsed.get("query", query) if not keyword else query
    final_author = author or parsed.get("author", "")
    final_org = organization or parsed.get("organization", "")
    final_keyword = keyword or parsed.get("keyword", "")
    final_fund = fund or parsed.get("fund", "")
    final_year_from = year_from or parsed.get("year_from")
    final_year_to = year_to or parsed.get("year_to")

    # Build the professional search expression
    expression = build_expression(
        query=final_query,
        author=final_author,
        organization=final_org,
        keyword=final_keyword,
        year_from=final_year_from,
        year_to=final_year_to,
        fund=final_fund,
    )

    # Execute the search
    browser = await get_browser()
    html = await browser.search_professional(expression, max_results)
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
