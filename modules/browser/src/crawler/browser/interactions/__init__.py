"""抖音互动写操作编排：经 CDP 浏览器执行评论 / 回复 / 私信。

包内采用一个文件一个职责的协作结构：``models`` 承载数据模型与回调契约，
``selectors`` 承载 DOM 常量，``reporting`` 是唯一步骤上报出口，``navigation`` /
``panel`` 承载页面导航与评论区展开，``verification`` 承载目标评论的实时核验，
``comment_locator`` / ``page_controller`` / ``submit_flow`` / ``response_inspector``
承载页面级协作，``executor`` 只做三条流程的编排。

本包不得 import ``crawler.douyin_client``（裁决 R10.1）：互动所需的读写能力一律
经 ``crawler.browser.facade.protocols.InteractionApi`` 注入。
"""
