# CNKI-PRO-MCP

知网（CNKI）专业检索 MCP 服务，通过 Playwright 浏览器自动化实现学术文献检索。

## 安装

```bash
pip install -e .
# 使用系统自带的 Edge 浏览器，无需额外安装 Chromium
```

## MCP 配置

```json
{
  "mcpServers": {
    "cnki": {
      "command": "python",
      "args": ["-m", "cnki_mcp.server"],
      "cwd": "path/to/CNKI-PRO-MCP/src"
    }
  }
}
```

首次使用需弹出浏览器完成滑块验证：

```json
{
  "mcpServers": {
    "cnki": {
      "command": "python",
      "args": ["-m", "cnki_mcp.server"],
      "cwd": "path/to/CNKI-PRO-MCP/src",
      "env": {
        "CNKI_HEADED": "true"
      }
    }
  }
}
```

验证通过后 cookies 自动保存为 `.cnki_cookies.json`，后续可 headless 运行，无需再次验证。

## 工具

| 工具 | 说明 |
|------|------|
| `cnki_search` | 自然语言搜索，自动构造专业检索表达式 |
| `cnki_professional_search` | 直接输入 CNKI 专业检索语法 |
| `cnki_get_article` | 获取文章详情 |

## 使用示例

**自然语言搜索**：
```
搜索知网关于"人工智能在医疗中的应用"的文献，限定2020-2024年
```

**结构化搜索**：
```
作者:王大中 单位:清华大学 关键词:核能
```

**专业检索表达式**：
```
SU %= '人工智能' AND YE BETWEEN ('2020', '2024') AND AF % '清华大学'
```

## 项目结构

```
CNKI-PRO-MCP/
├── pyproject.toml
├── README.md
└── src/cnki_mcp/
    ├── server.py          # MCP 服务入口
    ├── query_builder.py   # 专业检索表达式构造
    ├── browser.py         # Playwright 浏览器自动化 + 翻页
    └── parser.py          # 检索结果解析
```
