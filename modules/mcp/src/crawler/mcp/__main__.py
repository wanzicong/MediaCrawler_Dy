"""``python -m crawler.mcp`` 入口模块，直接转发到 MCP 网关的 main 函数。"""

from crawler.mcp.server import main

if __name__ == "__main__":
    main()
