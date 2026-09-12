"""站点无关内核测试包：会话、连接、页面端口/句柄与通用基元。

内部实现（``crawler.browser.<子包>``）只允许在本包内被直测：上层测试
（``tests/business`` / ``tests/api``）只能经 ``crawler.browser`` 门面取符号。
"""
