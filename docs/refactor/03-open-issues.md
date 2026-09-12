# 重构过程中发现的开放问题（非本波次所有权，登记待处理）

> 由各波次 agent 在实施中报告、但按文件所有权约束未顺手修改的问题。
> 每条标注【处置】= 本轮修 / 记为已知遗留。

---

## OI-1｜`SubmitFlow.fill_and_submit` 的异常分类可能误标【记为已知遗留】

- **位置**：`modules/browser/src/crawler/browser/interactions/submit_flow.py:119`
  （`assert submit is not None`）
- **现象**：当 `require_comment_confirmation=True` 且 `require_explicit_submit=False`
  且找不到发送控件时，`AssertionError` 会落进兜底 `except Exception`，
  被报成 `network_error`（`retryable=True`、`affects_account_health=True`），
  而不是语义正确的 `submit_not_available`。
- **当前可达性**：executor 的三处调用点都用成对参数（或只传 `require_explicit_submit`），
  因此**生产路径不可达**，属潜伏误标。
- **为什么难发现**：断言的兜底捕获把「编程错误」伪装成「网络错误」，
  且会错误地把账号判为不健康。
- **建议处置**：把该 assert 换成显式的 `raise InteractionExecutionError("submit_not_available", ...)`，
  或把兜底 `except Exception` 收窄为具体异常类型。**本轮不改**（避免在重构收尾引入行为变化），
  记为独立缺陷。

## OI-2｜规格 §4.7 的措辞与实现有偏差（行为更宽松，已接受）

- **规格**：executor 的导航写作 `await session.open(INDEX_URL)`。
- **实现**：走 `navigation.open_index(page)` —— `page.goto(INDEX_URL, domcontentloaded, 30s)`
  且**吞掉** commit 超时。
- **差异**：`session.open()` 会把超时抛成 `BrowserAutomationTimeoutError`；
  `open_index()` 吞掉超时后继续。
- **裁决**：实现与**迁移前行为一致**（更宽松），且 `tasks/crawler.py` 保留的
  `except BrowserAutomationTimeoutError` 在本路径不会触发但也不算悬空
  （`session.open()` 在 S5a 的 business 路径上仍会抛它）。
  测试按实现钉住。**接受该偏差，规格文字在 S6 一并订正。**

## OI-3｜`modules/douyin-client/README.md` 引用了已删除的测试路径【S5b 处理】

- **位置**：`modules/douyin-client/README.md:104`
- **内容**：命令行列出的两个测试文件已在 S4 补完阶段删除：
  `tests/business/douyin/test_interaction_executor.py`、`tests/business/douyin/test_login.py`
  （新位置 `tests/browser/sites/douyin/`）。
- **处置**：S5b 随 `pyproject.toml` 一起改 README。同时检查 `modules/browser/README.md`
  是否也引用了旧的 `crawler.browser.runtime.*` 路径。

## OI-4｜`executor.execute` 的页面句柄获取在 `try` 之外【记为已知遗留】

- **现象**：`_interaction_page(browser)` 与 `bring_to_front()` 在 `try` 块之外，
  页面句柄不可用时**不会**产生 `execution_failed` 步骤上报。
- **判断**：无页面可上报，疑似有意设计；且该路径会抛 `browser_unavailable`（已有用例覆盖）。
- **处置**：记为已知遗留，不改。

---

## 取证记录：旧测试的假绿

旧 `tests/business/douyin/test_login.py` 里有形如
`instance.__aexit__ = ...` 的写法，试图在实例上覆盖异步上下文管理器协议。
**这在 Python 里不会生效**——特殊方法只在**类型**上查找，实例属性会被忽略。
因此那个「超时」用例实际上一直是靠**别的分支**变绿的，从未真正测到它声称覆盖的路径。

S4 补完阶段的新 `test_submit_flow.py` 改用 `_TimeoutResponse` / `_RaisingResponse`
类来真正注入 `expect_response` 的超时与非超时异常，覆盖才是真实的。

**教训（供 S6 写门禁参考）**：mock 相关的测试最容易"假绿"，
S6 新增门禁时应优先断言**行为可观测项**（事件序列、调用计数），而不是断言 mock 被调用。
