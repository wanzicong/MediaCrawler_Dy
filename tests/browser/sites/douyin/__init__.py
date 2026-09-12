"""抖音站点层测试包：登录流程、互动编排、页面协作类与入站端口契约。

本包直测 ``crawler.browser.interactions`` / ``crawler.browser.login`` 的内部实现，
因此允许 import ``crawler.browser.<子包>``（测试侧边界只约束 ``tests/business`` 与
``tests/api``）。互动所需的抖音读写能力全部以假 ``InteractionApi`` / ``LoginApi``
注入，browser 侧不 import ``crawler.douyin_client``。
"""
