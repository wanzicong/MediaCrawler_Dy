# 冻结规格补充裁决（02）

> 本文是 `00-target-architecture.md` 的**补充与更正**，由主流程在开工前对规格逐条核实后作出。
> 与 00 冲突时**以本文为准**。已核实的事实附证据。

---

## R1｜S3 不得改 `pong` / `update_cookies` 的入参（修正 00 的自相矛盾）

**规格 00 的矛盾**：S3 文件集写「改 `client.py`：`pong`/`update_cookies` 去 `browser_context` 入参」，
但 S3 风险第 6 条又写「`accounts:1218` 的 `client.pong(context)` 本步不动」。

**为什么不能按字面执行**：`pong(browser_context)` / `update_cookies(browser_context)` 在 S3 之后、
S5 之前仍有 3 处活跃调用方：

| 调用方 | 位置 | 属于哪一步才消失 |
|---|---|---|
| `accounts/service.py` | `:1218` `client.pong(browser.context)` | S5 |
| `tasks/crawler.py` | `:183` `client.pong(browser.context, ...)`、`:194` `client.update_cookies(browser.context)` | S5 |
| `douyin_client/interactions/executor.py` | `:151` `client.pong(browser.context, ...)`、`:157` `client.update_cookies(browser.context)` | S5（该文件 S5 才删） |

**裁决**：S3 **保留这两个入参**，实现上改为优先走 `self.session`，但签名放宽为
`browser_context: BrowserContext | None = None` 且**忽略**该参数（仅为兼容而在，S5 连同调用方一起删除）。
`create()` 改为 `session=` 注入是本步唯一的签名翻转。

**S5 才做**：删除这两个参数 + 更新全部 5 处调用方，一步原子完成。

---

## R2｜S5 拆成 S5a / S5b 两步（降低「单点不可拆」风险）

规格 00 把 S5 定义为一次不可拆分的原子操作，同时含「5 个 business 文件迁移 + 新增子域 + 删除 5 类旧符号 +
删 shim + 删 `.page`/`.context` + pyproject」。这是全计划风险最集中处，失败无法分步定位。

**裁决**：拆为两步，均为 solo（不并行）：

- **S5a｜business 迁移到新 API（纯新增/改写，不删任何旧路径）**
  新增 `business/douyin/adapters/{__init__,models,service}.py` + 改 5 个 business 调用点 +
  `tests/architecture/test_module_layout.py` 的 `DOUYIN_SUBDOMAINS` 增 `adapters`。
  旧路径（`douyin_client/interactions/`、`douyin_client/login/`、`browser/runtime/` shim、
  `CDPBrowserSession.page`/`.context`）**全部保留**。结束时全仓应仍能跑通测试。
- **S5b｜切割删除（纯删除 + 改 `douyin_client/__init__.py` + pyproject）**
  删 `douyin_client/{interactions,login}/`、删 `browser/runtime/` 三个 shim、
  删 `CDPBrowserSession.page`/`.context`、删 `pong`/`update_cookies` 的 `browser_context` 入参、
  改 `modules/douyin-client/pyproject.toml`、改 `douyin_client/__init__.py`。
  结束前跑一次完整 import 冒烟 + `tests/architecture`。

这样 S5b 失败时，S5a 的成果可保留，回退面清晰。

---

## R3｜已核实的事实（可用于收窄实施假设）

| # | 事实 | 证据 | 对实施的影响 |
|---|---|---|---|
| 1 | 全仓**零处** `except DouyinError` | `grep -rn "except DouyinError" modules tests` 无命中 | `LoginError` / `InteractionExecutionError` 基类由 `DouyinError` 改为 `RuntimeError` **不会**打穿任何既有捕获点。规格 00 风险 #7 成立，可放心做 |
| 2 | `except InteractionExecutionError` 仅 2 处 | `interactions/submit_flow.py:291,363`（S4 随文件迁入 browser）、`business/douyin/interactions/service.py:1267`（S5a 改 import 来源） | 迁移时同步改这 2 处 import 来源即可 |
| 3 | `LoginError` 无 `except` 捕获点（只被 raise） | `tasks/crawler.py:187` 只有 `raise LoginError(...)` | 迁移只需改 import 来源，无捕获点需要改语义 |
| 4 | `ShortUrlApi` 确实调用私有方法 | `http/scenarios/resolver.py:62` `self._client._failure_detail_from_response(exc.response)` | 私有改公开 `failure_detail_from_response` 是**必要**的，且只有 1 处外部调用点 |
| 5 | `runtime/`、`base/`、`remote/` 的 `__init__.py` **只有 docstring**，无 re-export | `cat` 三个文件均为纯 docstring | `runtime/` shim 只需单层 `from ... import ...` 转发，无需处理再导出链 |
| 6 | `DOUYIN_SUBDOMAINS` 是**排序 tuple（10 项）**，且每个子域强制要求 `__init__.py` + `models.py` + `service.py`（`NO_SERVICE_SUBDOMAINS` 除外） | `tests/architecture/test_module_layout.py:29-44`、`:86-92` | `adapters` 按字典序插到 `accounts` 之后，且**三件套必须齐全**，否则 `test_each_member_owns_exactly_one_subpackage` 家族的红灯 |
| 7 | `test_accounts_works_exports.py` 存在 | `tests/business/douyin/test_accounts_works_exports.py` | 规格 S3/S5 列的验证命令有效 |
| 8 | `tests/browser/` 需自带 `__init__.py` | `tests/business/douyin/__init__.py` 存在，`tests/` 是含 `__init__.py` 的包 | S2 创建 `tests/browser/__init__.py` 与各级子包 `__init__.py` |

---

## R4｜P0a 的两阶段演进是有意的（不是返工）

Wave 0 先行在**旧布局上**修复 P0a：新增 `douyin_client/base/fingerprint.py` 的
`DouyinClientFingerprint.from_sources(user_agent, raw_readings)`，由 `create()` 读页面得到读数后传入。

S3 会把**推导实现搬去 browser**（`browser/session/environment.py` 的 `derive_browser_family` +
`BrowserEnvironment`），`douyin_client` 侧改为只消费 `session.fingerprint()` 返回的 `Mapping`，
并**删除** `douyin_client/base/fingerprint.py`。

两阶段的**不变量必须一致**（S3 验收时要核对）：
- 键集合 == `DouyinClient.FINGERPRINT_KEYS`（14 项）
- **缺键即不写入**，绝不回退伪造常量
- 源码中不得再出现 `MacIntel` / `Mac OS` / `2560` / `1440` / `Chrome 125` 字面量
- 值必须与 `User-Agent` 同源（同一个 UA 字符串推导）

---

## R5｜规格文字层面的小修（实施时直接按此）

1. **G13 描述里的 `/sites` 是遗留措辞**：本设计只有 `browser/<子包>/`，没有 `core`/`sites` 分层。
   G13 实施时按 G3 同形处理（`tests/business/**`、`tests/api/**` 只允许
   `crawler.browser` 与 `crawler.browser.facade` 两个精确模块名）。
2. **G19 的行数上限取 300 行**（规格 §5 与 §7 一致写 300；`interactions/executor.py` 当前 728 行）。
3. **`PageAcquisitionPolicy` / `BrowserSessionContext` 等内部符号不出门面**，但需要允许
   `tests/browser/**` 直测——测试侧边界规则 G13 只约束 `tests/business/**` 与 `tests/api/**`，
   不约束 `tests/browser/**`，规格已如此，实施时不要误扩。

---

## R7｜P0-b 的落点偏离与接受决定（S3 需执行搬迁）

**偏离**：Wave 0 的 P0-b 把脱敏真源建在
`modules/douyin-client/src/crawler/douyin_client/base/redaction.py`，
而规格 00 §1.2 要求落在 `http/redaction.py`。

**原因**：主流程下达 Wave 0 指令时按早期草稿写成了 `base/`，属主流程指令错误，非实施 agent 失误。

**裁决**：
1. **接受实现，修正落点**。S3 在重组 `base/` 时，把 `base/redaction.py` **移动到 `http/redaction.py`**
   （`base/` 本就要在 S3 被解散为 `errors/`+`privacy/`+`signing/`+`parsing/`，该文件不属于其中任何一类）。
   同步改 3 处 import：`http/request_log.py`、`business/douyin/request_logs/service.py`、
   `tests/business/douyin/test_request_logs.py`。
2. **接受实现细节优于规格**：规格 §8 P0b 原定用 6 项 `SENSITIVE_HEADER_NAMES` 精确匹配头名；
   实施 agent 改为复用 business 既有的 16 项归一化标记集（`is_sensitive_key`，子串匹配），
   覆盖面更广，且与 business 侧落库脱敏**逐字符同规则**，因此构造时脱敏与下游脱敏天然幂等。
   **保留实施版本**，S6 的门禁测试按「Cookie/Authorization 被替换、User-Agent 原样保留」断言，
   与两种实现都兼容。
3. **真源导出名**：实施版导出 `REDACTED` / `SENSITIVE_KEY_MARKERS` / `normalize_key` /
   `is_sensitive_key` / `redact_headers`。规格 §3 的 `crawler.douyin_client.__all__` 第 21–23 项写的是
   `REDACTED` / `redact_headers` / `redact_mapping`——S3 落 `__init__.py` 时以**实际存在的符号**为准
   （`redact_mapping` 不存在则不加，改为导出 `is_sensitive_key`；不要为凑清单造函数）。
4. **已知遗留（不在本轮范围）**：`business/douyin/request_logs/service.py` 里还有第二份
   独立维护的**自由文本**敏感词正则 `_SENSITIVE_TEXT_PATTERN`（必须保留字面拼写，无法由归一化标记集生成），
   与标记集不完全一致（`csrf`/`odin`/`passport`/`session`/`accountid` 在标记集里但不在正则里）。
   本轮按范围克制不动；S6 可在真源模块里以并列声明的方式合并两种拼写，作为改进项。

---

## R10｜S3 ∥ S4 并行期的两条边界（所有权与临时重名异常）

S3（douyin_client 纯化）与 S4（interactions/login 迁入 browser）并行执行，存在两处必须钉死的边界。

### R10.1｜S4 完全不碰 `modules/douyin-client/**`

`InteractionExecutionError` / `LoginError` 在 S4 时会在 browser 侧**新建一份**，
而 `douyin_client/errors/family.py` 里那份**保持不动**（S5b 才删）。

**后果（有意接受）**：S4 完成到 S5a 完成之间，全仓存在两个同名不同类。
- `browser/interactions/*` 内部只捕获 **browser 自己那份**（`crawler.browser.errors`）；
- `douyin_client/interactions/*`（S5b 才删）仍用 douyin_client 那份；
- business 的 `except InteractionExecutionError`（`interactions/service.py:1267`）此时仍 import douyin_client 那份 —— **S5a 必须把它改成从 `crawler.browser` 导入**，这是 S5a 的验收项之一，漏改会导致捕获静默失配。

**因此**：S4 的新文件不得 import 任何 `crawler.douyin_client.*`。
`verification.py` 调 `api.verify_target_comment(...)` 是走 Protocol，不是 import，合规。

### R10.2｜S3 解散 `base/` 时，必须同步改仍在用它的 douyin_client 内部文件

`douyin_client/interactions/*.py`、`login/login.py`、`http/scenarios/*.py` 目前 import
`crawler.douyin_client.base.{errors,types,privacy,signer}`。这些文件 **S5b 才删**，S3 必须让它们继续可导入。

**裁决**：S3 用「先 sed 机械替换、再编译校验」的方式，把 douyin_client 内部对这 4 个旧路径的引用
一并改到新路径（`errors/family.py`、`parsing/{types,links}.py`、`privacy/{masking,mapping}.py`、`signing/{a_bogus,web_id}.py`）。
**不建 `base/` 兼容 shim**——`base/` 在 S3 就要消失，建 shim 等于把旧路径留到 S5b，与 G11「旧路径消失」冲突。

**S3 的文件所有权因此扩展**：`douyin_client/**` 全部（含 `interactions/`、`login/` 的 import 行）。
S4 不得改这些文件（见 R10.1）。

---

## R9｜P0-a 尚有 3 个键未同源，S3 必须补齐（否则 P0-a 只修了一半）

**现状**：Wave 0 的 P0-a 删掉了 11 个硬编码指纹键，改为「同一 UA 正则推导 + 真实浏览器读数」。
但 `browser_language` / `effective_type` / `round_trip_time` 这 3 个键**仍是硬编码常量**
（`"zh-CN"` / `"4g"` / `"50"`）——这是主流程下达 Wave 0 指令时把它们划为「稳定参数」所致。

**问题**：这 3 个值与 `MacIntel`/`2560` 是**同一类缺陷**。
`browser_language` 硬编码 `zh-CN` 而真实浏览器可能是 `en-US`，正是 P0-a 要消除的「指纹与真实 UA/浏览器不一致」风控信号。
规格 §8 P0a 也明确把它们列为应从浏览器读取的读数
（`navigator.language`、`navigator.connection.effectiveType`、`navigator.connection.rtt`）。

**裁决**：S3 把 `FINGERPRINT_KEYS` 定为规格 §4.5 的 **14 项**，并把上述 3 键改为经 `session.fingerprint()` 注入：

| 键 | 来源 |
|---|---|
| `browser_language` | `navigator.language` |
| `effective_type` | `navigator.connection?.effectiveType` |
| `round_trip_time` | `navigator.connection?.rtt` |

`BrowserEnvironment` 的采集脚本必须包含这三项（S2 的 agent 已按规格实施，S3 只需接线）。
沿用「缺键即不写入」：`navigator.connection` 不存在时不写入 `effective_type`/`round_trip_time`。

**`engine_version` 保持「按可得性写入」**：UA 里 Blink/Gecko 只有冻结兼容标记（`537.36` / `20100101`），
没有诚实来源，因此 Chrome/Firefox 下该键**省略**、Safari 下从 `AppleWebKit/x.y.z` 取真实内核版本
（Wave 0 实施已如此）。这不违反「缺键不写入」，也不得为凑键而写回 `109.0`。
**注意**：`engine_version` 仍留在 `FINGERPRINT_KEYS` 里（键表是能力声明，不是必填承诺）。

**S3 验收必须包含**：源码文本断言 `browser_language` / `effective_type` / `round_trip_time` 的**硬编码字面量**
（`"zh-CN"` / `"4g"` / `"50"`）在 `http/client.py` 中不再出现，且这 3 键的取值随注入指纹变化。

---

## R8｜`uv.lock` 是本机 uv 镜像配置的副作用（收尾时还原）

本机 `uv run` 会把 `uv.lock` 的 `pypi.org/simple` 全部改写为 `pypi.tuna.tsinghua.edu.cn/simple`
（1824 行纯 URL 替换，**无版本变化**）。

**裁决**：全部波次停工后执行 `git checkout uv.lock`，不把镜像地址混入本次改动。
（若用户本机确实使用该镜像，属其本地配置问题，不在本次重构范围。）

---

## R6｜执行纪律（所有波次 agent 必须遵守）

1. **任何一步结束时 `uv run python -c "import crawler.api.main"` 必须成功。**
   `tests/conftest.py:10` 顶层 `from crawler.api.main import app`，断链会导致 pytest
   **整体 collection error**（不是个别用例失败）。
2. **不要在别的 agent 正在写的文件上动手**。每步的【文件集】是所有权边界。
3. **不要跑全量 `uv run pytest`**（会与并行 agent 抢写窗口）。只跑本步【验证方式】列出的定向命令。
4. 基线已知失败（**不要试图修**）：
   - `tests/architecture/test_behavior_contracts.py::test_mcp_tool_contract_is_unchanged`
   - `tests/business/douyin/test_crawler.py` 全部 9 个用例（测试替身缺 `search_api`/`aweme_api`/`user_api`）
   详见 `01-baseline.md`。
