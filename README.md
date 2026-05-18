# cnki-search-mcp

CNKI 学术文献检索 MCP 服务，通过 Playwright 浏览器自动化实现文献检索与结果解析。

> **免责声明**：本工具仅供个人学术研究使用。使用本工具即表示您同意遵守 CNKI 的使用条款。本工具模拟正常浏览器访问行为，不会自动绕过任何安全验证机制，也不会下载付费内容全文。用户需自行完成滑块验证。

## 安装

```bash
pip install cnki-search-mcp
```

## MCP 配置

```json
{
  "mcpServers": {
    "cnki": {
      "command": "cnki-search-mcp"
    }
  }
}
```

首次使用需弹出浏览器完成滑块验证，之后 cookies 自动保存可静默运行：

```json
{
  "mcpServers": {
    "cnki": {
      "command": "cnki-search-mcp",
      "env": {
        "CNKI_HEADED": "true"
      }
    }
  }
}
```

## 工具

| 工具 | 说明 |
|------|------|
| `cnki_search` | 一框式检索，支持切换字段（主题/关键词/作者/篇名等），有过滤条件时自动切换专业检索 |
| `cnki_professional_search` | 直接输入 CNKI 专业检索表达式 |
| `cnki_syntax_guide` | 获取专业检索完整语法参考 |
| `cnki_get_article` | 获取文章详情 |

## 使用示例

```
一框式检索：搜索关于"人工智能在医疗中的应用"的文献
按作者搜索：查找作者名为张三的论文
按关键词搜索：关键词为深度学习的文献
专业检索：SU %= '人工智能' AND YE BETWEEN ('2020', '2024')
```

## 本地开发

```bash
git clone https://github.com/CN-MRZZJ/cnki-search-mcp.git
cd cnki-search-mcp
pip install -e .
```
