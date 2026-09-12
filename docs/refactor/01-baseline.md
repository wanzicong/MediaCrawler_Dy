# 重构前基线（refactor/browser-capability-platform 分支起点）

采集时间：2026-09-12，分支从 `feat/frontend-hardening`(728a6a6) 切出。
命令：`uv run pytest -q -p no:randomly`

## 结果：10 failed, 468 passed（58.94s）

**仓库在本次重构开始前就不是绿的。** 下列 10 个失败为既有失败，与本轮改造无关；每个波次验收时只比对这些条目，不把既有失败算作回归。

### 1. MCP 工具契约哈希漂移（1 个）

- `tests/architecture/test_behavior_contracts.py::test_mcp_tool_contract_is_unchanged`

```
assert 'dc3d502ae51a...b96c472d5653b' == '31149ed5865d...98beef7bb2e8a'
```

MCP 工具数量仍是 32（数量断言通过），但规范化 SHA256 与冻结值不符。

### 2. test_crawler.py 测试替身脱节（9 个）

全部同一根因：
`AttributeError: 'CreatorDiscoveryClient' object has no attribute 'aweme_api'`
抛出点：[modules/business/src/crawler/douyin/tasks/crawler.py:503](modules/business/src/crawler/douyin/tasks/crawler.py#L503)

- `test_search_honours_global_aweme_limit`
- `test_search_verify_check_is_not_marked_as_successful_empty_result`
- `test_search_resume_starts_from_persisted_page_checkpoint`
- `test_search_resume_retries_interrupted_page_comments`
- `test_comment_resume_uses_remaining_persisted_limit`
- `test_comment_recrawl_reuses_existing_aweme_without_fetching_or_inserting_detail`
- `test_creator_crawl_persists_post_list_without_per_work_detail_requests`
- `test_creator_crawl_tolerates_single_work_comment_failure`
- `test_creator_from_aweme_uses_raw_creator_id_in_memory_only`

**根因结论：9 个失败同源，纯测试漂移，无生产 bug。**

逐条 `--tb=line` 输出：

| 失败替身 / 位置 | 缺失能力 | 数量 |
|---|---|---|
| `FakeSearchClient` / `VerifyCheckClient` / `CheckpointSearchClient` / `CommentCheckpointClient` @ crawler.py:342 | `search_api` | 4 |
| `CreatorPostsClient` @ crawler.py:538 | `user_api` | 2 |
| `CreatorDiscoveryClient` @ crawler.py:503 | `aweme_api` | 1 |
| crawler.py:701（`当前页面仍有 2 个作品评论未完成`） | 下游症状 | 1 |
| crawler.py:468（`指定作品仍有 1 项未完成`） | 下游症状 | 1 |

- 前 7 个：测试替身类没有实现 `DouyinClient` 被拆成 `http/scenarios/` 后新增的组合属性
  （`search_api`/`aweme_api`/`comments_api`/`user_api`/`resolver_api`），直接 `AttributeError`。
- 后 2 个是**下游症状而非独立缺陷**：替身抛出的 `AttributeError` 被
  `asyncio.gather(..., return_exceptions=True)` 收集后，代码转而抛出
  `DataFetchError("当前页面仍有 N 个作品评论未完成…")`，测试断言的是另一条成功路径。

即：`DouyinClient` 场景化拆分时，测试替身未同步更新。不是环境问题，也不是产品缺陷。
（收集期 478 个测试全部成功，不需要 DB。）

**对本轮重构的影响**：这 9 个用例所在文件 `tests/business/douyin/test_crawler.py` 中的替身，
在 interactions 迁出 douyin-client 后仍需再次调整（替身要跟上新的门面形状）。验收时
**不比对这些用例的通过状态**，只确保数量不增加到 9 个以上、且失败原因仍为同源的替身缺失。

## 其它门禁的基线状态（补测：初次建档时只跑了 pytest，漏了这几项）

### `uv run ruff format modules tests --check` —— **基线即失败**，6 个文件需重排

```
modules\business\src\crawler\business\douyin\tasks\crawler.py
modules\douyin-client\src\crawler\douyin_client\http\scenarios\resolver.py
modules\douyin-client\src\crawler\douyin_client\interactions\comment_locator.py
modules\douyin-client\src\crawler\douyin_client\interactions\executor.py
modules\douyin-client\src\crawler\douyin_client\interactions\submit_flow.py
tests\business\douyin\test_interaction_executor.py
```

**确认为基线失败**：这 6 个文件在 `refactor/browser-capability-platform` 分支起点时全部处于
git 未修改状态（`git status` 的已修改清单里没有它们），因此其格式问题是 HEAD 自带的。
6 个文件**全部**将在 S4（interactions 迁入 browser）与 S5a（tasks/crawler.py 改造）中被重写或删除，
届时顺带 `ruff format` 修复，**不单独提交格式修复**，以免污染重构 diff。

### `uv run ruff check modules tests` —— 基线通过

### `uv run mypy -p ...`（6 个模块，strict）—— 基线通过

重构后复测：`Success: no issues found in 178 source files`。

## 隐性基线：测试库残留会让用例"假性失败"（重构中踩到过，务必知悉）

`tests/conftest.py` 的 `db` fixture 只快照并还原 `CrawlTask` / `Item` 两类实体，
**不清理账号**（`DouyinAccount`）。而 `tests/business/douyin/test_accounts_works_exports.py`
的用例会在**测试库**（`postgresql+psycopg://…@localhost:55432/app_test`）里真实创建账号行，
只在用例**末尾**删除。

**后果**：任何一次在该用例中途失败（无论是真的断言失败，还是被别的问题打断），
都会残留一条同名账号行；此后每次重跑都会在 `create_account` 的
`session.commit()` 上撞唯一约束 → `AccountConfigurationError("账号名称或 Browser Profile 已存在")`
→ API 返回 **422**。

**这个 422 是个假象**：它会**掩盖真正的失败原因**（第一次踩到时，它掩盖了
`'FakeBrowser' object has no attribute 'session_context'` 这个真问题）。
排查时不要只看 422 的 detail，先看库里有没有同名残留行。

**清理方式**（已验证有效）：
```python
# 临时探针，跑完即删
from sqlmodel import Session, select
from crawler.business.douyin.accounts.models import DouyinAccount
from crawler.bootstrap.database import engine
with Session(engine) as s:
    for r in s.exec(select(DouyinAccount).where(DouyinAccount.name == "<用例里的名字>")).all():
        s.delete(r)
    s.commit()
```

**给 S5a/S6 的提醒**：`test_accounts_works_exports.py` 里的账号名
（`已持久化登录账号`、`页面导航异常账号`、`测试本机账号` 等 6 个）如果在测试库里存在同名列，
先清理再判定失败原因。

## 其它环境事实

- `uv --version` → 0.12.7；`python --version` → 3.13.15
- `uv run pytest --collect-only -q` → 478 tests collected in 6.95s（不依赖 DB）
- `uv run pytest tests/architecture -q` → 1 failed, 41 passed in 2.48s
- settings 会打 3 条 `changethis` 安全告警（SECRET_KEY / POSTGRES_PASSWORD / FIRST_SUPERUSER_PASSWORD），与测试无关
