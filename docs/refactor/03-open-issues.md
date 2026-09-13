# 开放问题登记

> 重构与缺陷修复过程中发现、但按范围或所有权约束未一并处理的问题。
> 状态：`已修复` / `记为已知遗留` / `有意设计（已文档化并被测试钉住）`。

---

## OI-1｜`SubmitFlow` 的异常误标 —— ✅ 已修复（含同族与顺序两处扩展）

**原缺陷**：`submit_flow.py` 用 `assert submit is not None` 表达前置条件，`AssertionError`
落进兜底 `except Exception` → 被标成 `network_error`（`retryable=True`、
**`affects_account_health=True`**）。后果不只是错误码错，还会让
`business/.../interactions/service.py` 的 `account_healthy = not exc.affects_account_health`
判为 False，把一次「页面上没有发送按钮」升级成「账号不健康」。

**修复过程（三轮，每轮都经独立对抗式验证）**：

1. **改类型化抛出**：前置条件改为 try **之外**的
   `InteractionExecutionError("submit_not_available", retryable=True)`（不带 `affects_account_health`），
   删除 `assert`。验证判定「未被证伪」。
2. **修同族**（第 2 轮验证者实测证伪）：`dispatch_comment_submit` 在三种激活方式都失败后
   `raise last_error`，同样是确定性页面条件却被误标；且页面文案判定被**硬编码绑在单个 code 上**，
   距离 5 行的兄弟分支 `submit_not_triggered` 漏掉 → 页面明明显示风控文案时
   `affects_account_health=False` → `failure_streak` 被归零 → **连续被风控也攒不到 `unhealthy`**。
   修法：引入 `PAGE_VERDICT_CODES` 集合按**类**覆盖，并新增 **AST 穷尽性测试**
   （`test_fill_and_submit_error_codes_are_all_classified`）：`fill_and_submit` 内每个错误码
   必须落在「需查页面判定」集合或文档化的排除表里，**新增错误码会红灯**，解析不出一律拒绝放行。
3. **修顺序**（第 2 轮验证者点出的残留，主流程补做）：
   `reply_target_mismatch` 的判定原本在 `not response.ok` **之前**，导致 403/429 撞上
   「未绑定到预期评论」时风控信号丢失一次。已把 HTTP 状态判定前移（平台对本次请求的权威判定
   与绑定到哪条评论无关），并加回归用例 + 红/绿取证
   （旧顺序下 `assert 'reply_target_mismatch' == 'risk_controlled'`）。

**兜底 `except Exception` 的捕获范围刻意未动**：收窄它会让非 Playwright 异常
（DOM/JS 的 RuntimeError、解析的 ValueError 等）逃逸出业务分类层 —— 业务侧既不记失败状态、
也不发账号健康信号，等于用「结果不可见」换「结果被误标」，风险更大。
既有 `test_failure_before_submit_is_reported_as_network_error` 继续钉住「未知异常仍归 network_error」。

## OI-2｜规格 §4.7 措辞与实现不符 —— ✅ 已修复

`00-target-architecture.md` §4.7 原写 executor 的导航是 `await session.open(INDEX_URL)`，
实现走的是 `navigation.open_index(page)`（吞掉 commit 超时，与迁移前行为逐字一致）。
已在规格原文就地加订正说明，二者都满足「导航完成后才建 client」这条真正的不变量。

## OI-3｜README 引用已删除的测试路径 —— ✅ 已修复

`modules/douyin-client/README.md` 与 `modules/browser/README.md` 已随 S5b 一并订正
（依赖行、门面示例、目录树、门禁命令、旧路径引用）。

## OI-4｜`executor.execute` 的页面句柄获取在 `try` 之外 —— 记为已知遗留

`_interaction_page(browser)` 与 `bring_to_front()` 在 `try` 块之外，页面句柄不可用时
不会产生 `execution_failed` 步骤上报。该路径会抛 `browser_unavailable`（已有用例覆盖），
无页面可上报，疑似有意设计。**不改**。

---

## 新增登记（缺陷修复期间发现）

### OI-5｜`page_message_verdict` 自身抛异常时会从 `except` 处理器里裸冒泡 —— 记为已知遗留

`page_message_verdict` 在 `except` 处理器内部被调用；若页面已关闭，`page.get_by_text`
的 locator 构造可能同步抛 Playwright 错误（`visible_page_message` 的内层 try 在构造之后），
该异常会顶替原本的类型化异常逃逸出去，被业务侧归为 `internal_error` + 账号不健康。
**本轮把判定面从 1 个 code 扩到 2 个，触发面略增，但这是既有模式。**
建议处置：在 `page_message_verdict` 外层再包一层「判定失败即放弃判定」的 try。

### OI-6｜AST 穷尽性守卫是**词法级**的 —— 记为已知遗留

`test_fill_and_submit_error_codes_are_all_classified` 只审计 `fill_and_submit` 函数体内
构造的错误码。若将来某个新 code **只**在被调用方（如 `PageController`）构造、
且不在 `fill_and_submit` 内同名出现，守卫看不到它。
当前的 `submit_not_activated` 因两处同名而被覆盖。
建议处置：把守卫扩展到「被 `fill_and_submit` 直接调用的协作类」的构造点。

### OI-7｜私信/显式提交路径不做页面判定（有意设计）

`PAGE_VERDICT_CODES` 的查询被 `require_comment_confirmation` 守卫。该模式下页面文案
与本次发送不是一一对应，查询反而可能误升格，故刻意不查。
代价：私信发送撞上风控蒙层（`submit_not_activated`）仍不影响账号健康。**有意设计，已文档化。**

### OI-8｜`Retry-After` 顶到上限时分散退化为 0（有意设计，已文档化并被测试钉住）

`_retry_wait` 的分散性**仅在 `floor < cap` 时成立**：`floor >= cap`（服务端要求的等待
达到我们的安全上限 10s）时等待恒为 `cap`，并发任务对齐。
这是刻意取舍——上限优先于分散，此时再向上分散就超出我们愿意等的最长时间。
取舍已写进 docstring 并在测试里显式断言（`test_waits_degenerate_to_cap_once_floor_reaches_cap`、
`test_clamped_fraction_rises_as_floor_approaches_cap`），实测压顶比例：
`Retry-After=3 → 0%`、`=8 → 50.2%`、`=10 → 100%`。

### OI-9｜`Retry-After` 的 HTTP-date 形式不支持 —— 记为已知缺口

`_parse_retry_after` 只认数值秒。RFC 9110 允许该字段为 HTTP-date，Cloudflare/Fastly/
部分 nginx 配置实践中会发送。当前行为是**忽略并记 WARNING**（此前是静默忽略），
且用例的 docstring 已明确它钉的是「已知缺口」而非「HTTP-date 是非法输入」。

### OI-10｜兜底分支的 `affects_account_health=True` 是恒定值 —— 记为已知遗留

`fill_and_submit` 兜底分支对提交后的未知异常恒定置 `affects_account_health=True`，
与同一流程超时分支的 `affects_account_health=not submitted` 语义不一致
（同属「提交后结果不明」却记了两种账号健康语义）。
改它等于改**所有**未知异常的账号健康策略，超出缺陷修复范围。**不改。**

### OI-11｜`comment_locator.py:82` 的 `assert` —— 记为已知遗留（当前不可达）

`assert request.target_comment_content is not None` 不在 `fill_and_submit` 的调用栈内
（其唯一调用点是 executor 的回复流程），且上游 executor 已有
`if not request.target_comment_content: raise ...` 拦截，条件不可能为假。
它同时承担 mypy 的 `str | None` 收窄，删除需改该文件。**保留**。

---

## 取证记录：旧测试的假绿

旧 `tests/business/douyin/test_login.py` 里有形如 `instance.__aexit__ = ...` 的写法，
试图在实例上覆盖异步上下文管理器协议。**这在 Python 里不会生效**——特殊方法只在
**类型**上查找，实例属性会被忽略。因此那个「超时」用例实际上一直是靠**别的分支**变绿的，
从未真正测到它声称覆盖的路径。S4 补完阶段的新测试改用 `_TimeoutResponse` /
`_RaisingResponse` 类真正注入超时与非超时异常。

**教训**：mock 相关测试最容易"假绿"。新增门禁应优先断言**行为可观测项**
（事件序列、调用计数），而不是断言 mock 被调用。
