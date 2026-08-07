# Local Media to MinIO Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为已下载到本地的抖音视频提供任务级和单项异步迁移至 MinIO 的能力，并在远端完整回读校验、数据库切换和本地删除全部安全收敛后显示完成。

**Architecture:** 在 `DouyinMediaAsset` 上增加独立的持久化迁移状态，由新的 `MediaMigrationManager` 负责认领、上传、完整回读 SHA-256 校验、数据库切换、本地清理和启动恢复。存储层提供“不删除源文件”的验证上传原语，FastAPI、MCP 和 React UI 只调用迁移管理器并读取公共状态；既有预览、下载和字幕逻辑继续按资产当前 `storage_backend` 工作。

**Tech Stack:** Python 3.10+、FastAPI、SQLModel、PostgreSQL、Alembic、MinIO Python SDK、Pytest、React 19、TypeScript、TanStack Query、Vite、Playwright、Docker Compose。

## Global Constraints

- 以 `docs/superpowers/specs/2026-08-07-local-media-minio-migration-design.md` 为唯一产品设计依据。
- Cookie、Token、MinIO 凭据、本地绝对路径和原始账号 ID 不得写入日志或 API 响应。
- 本地文件只有在 MinIO 完整回读大小及 SHA-256 校验通过、数据库成功切换为 MinIO 后才能删除。
- 上传、校验或数据库切换失败时，资产必须继续指向可用的本地文件。
- 迁移完成后的 `storage_backend`、`storage_bucket`、`object_key` 和空 `local_path` 必须与直接下载到 MinIO 的资产一致。
- 删除目标必须是数据库记录指向且解析后位于 `MEDIA_OUTPUT_DIR` 内的具体文件，禁止递归删除。
- 模型变更必须提供可升降级的 Alembic 迁移。
- 现有 Playwright 浏览器抓取仍只允许 `connect_over_cdp`；本功能不得引入任何浏览器启动或回退路径。
- 后端质量门禁必须执行 `uv run ruff check app tests`、`uv run mypy app`、`uv run python -m compileall -q app` 和 `uv run pytest`。
- 涉及服务行为必须应用数据库迁移、关闭旧进程并启动新进程，然后验证健康检查、鉴权、迁移 API 和预览 Range 请求。

---

## File Structure

- `backend/app/models.py`：迁移状态枚举、请求/响应模型、资产公共字段和汇总字段。
- `backend/app/alembic/versions/f47a8c1d9e20_add_media_migration_state.py`：资产迁移状态字段及索引。
- `backend/app/core/config.py`：可配置的迁移并发量，默认 2。
- `backend/app/services/media_storage.py`：MinIO 可用性预检、保留源文件的上传、完整对象回读校验和远端清理。
- `backend/app/services/media_migration.py`：迁移队列、状态机、幂等认领、数据库切换、本地清理、启动恢复和关闭。
- `backend/app/services/douyin_tasks.py`：在应用生命周期启动和关闭迁移管理器。
- `backend/app/services/media_pipeline.py`：把迁移字段和汇总计数映射至公共响应，不承担迁移执行。
- `backend/app/api/routes/douyin.py`：任务所有权校验后的迁移 API。
- `backend/app/mcp_server/server.py`：与 FastAPI 等价的 MCP 迁移工具。
- `backend/tests/douyin/test_models.py`：模型默认值和请求校验。
- `backend/tests/douyin/test_media_storage.py`：MinIO 上传、完整回读和源文件保留测试。
- `backend/tests/douyin/test_media_migration.py`：状态机、安全顺序、幂等及恢复测试。
- `backend/tests/api/routes/test_douyin.py`：鉴权、任务范围和 202/409/503 API 测试。
- `backend/tests/douyin/test_mcp_server.py`：MCP 请求体和 API 转发测试。
- `frontend/openapi.json`、`frontend/src/client/`：从后端 OpenAPI 重新生成的客户端。
- `frontend/src/components/Douyin/MediaMigrationDialog.tsx`：任务级迁移确认及提交对话框。
- `frontend/src/components/Douyin/MediaPipelinePanel.tsx`：汇总、轮询、迁移列和单项重试。
- `frontend/tests/douyin.spec.ts`：批量迁移和失败重试浏览器测试。
- `README.md`：配置、操作方式和严格完整性语义。

---

### Task 1: Persistent Migration Model and Alembic Revision

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/core/config.py`
- Create: `backend/app/alembic/versions/f47a8c1d9e20_add_media_migration_state.py`
- Modify: `backend/tests/douyin/test_models.py`

**Interfaces:**
- Produces: `MediaMigrationStatus`, `DouyinMediaMigrationRequest`, `DouyinMediaMigrationAccepted`.
- Produces: `DouyinMediaAsset.migration_status`, `migration_progress`, `migration_attempt_count`, `migration_error`, `migration_started_at`, `migration_finished_at`.
- Produces: matching fields on `DouyinMediaAssetPublic` and migration counters on `DouyinMediaSummaryPublic`.
- Produces: `settings.MEDIA_MIGRATION_CONCURRENCY: int` with default `2` and minimum runtime clamping in the manager.

- [ ] **Step 1: Write failing model tests**

Add tests that instantiate an asset and validate the public request contract:

```python
def test_media_migration_models_are_persistent_and_private() -> None:
    asset = DouyinMediaAsset(task_id=uuid.uuid4(), aweme_id="migration-aweme")
    request = DouyinMediaMigrationRequest(asset_ids=[asset.id])

    assert asset.migration_status == MediaMigrationStatus.idle.value
    assert asset.migration_progress == 0
    assert asset.migration_attempt_count == 0
    assert asset.migration_error is None
    assert request.asset_ids == [asset.id]
    assert "local_path" not in DouyinMediaAssetPublic.model_fields
    assert "storage_bucket" not in DouyinMediaAssetPublic.model_fields
    assert "object_key" not in DouyinMediaAssetPublic.model_fields


def test_media_migration_request_limits_asset_ids() -> None:
    with pytest.raises(ValidationError):
        DouyinMediaMigrationRequest(asset_ids=[uuid.uuid4() for _ in range(1001)])
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `uv run pytest tests/douyin/test_models.py -k media_migration -v`

Expected: collection fails because the migration models and fields do not exist.

- [ ] **Step 3: Add enum, schemas and database fields**

Define the exact state values:

```python
class MediaMigrationStatus(str, Enum):
    idle = "idle"
    queued = "queued"
    uploading = "uploading"
    verifying = "verifying"
    switching = "switching"
    cleanup_pending = "cleanup_pending"
    completed = "completed"
    failed = "failed"


class DouyinMediaMigrationRequest(SQLModel):
    asset_ids: list[uuid.UUID] = Field(default_factory=list, max_length=1000)


class DouyinMediaMigrationAccepted(SQLModel):
    queued: int
    skipped: int
    message: str
```

Add all persistent and public fields named in the Interfaces block. Add summary integer fields named `local_downloaded`, `minio_downloaded`, `migration_queued`, `migration_running`, `migration_cleanup_pending`, `migration_completed`, and `migration_failed`. Add `MEDIA_MIGRATION_CONCURRENCY: int = 2` next to the media download concurrency setting.

- [ ] **Step 4: Add the Alembic revision**

Create revision `f47a8c1d9e20`, with `down_revision = "e18c7a4b92d1"`. The upgrade adds the six migration columns with safe server defaults for existing rows, creates `ix_douyin_media_asset_migration_status`, then removes mutable server defaults. The downgrade drops the index and all six columns in reverse order.

- [ ] **Step 5: Run model tests and migration syntax checks**

Run:

```bash
uv run pytest tests/douyin/test_models.py -k media_migration -v
uv run python -m compileall -q app
uv run ruff check app/models.py app/core/config.py tests/douyin/test_models.py
```

Expected: all commands pass.

- [ ] **Step 6: Commit the model unit**

```bash
git add backend/app/models.py backend/app/core/config.py backend/app/alembic/versions/f47a8c1d9e20_add_media_migration_state.py backend/tests/douyin/test_models.py
git commit -m "feat: persist media migration state"
```

---

### Task 2: Verified MinIO Copy Primitive That Never Deletes the Source

**Files:**
- Modify: `backend/app/services/media_storage.py`
- Modify: `backend/tests/douyin/test_media_storage.py`

**Interfaces:**
- Consumes: `DouyinMediaAsset`, deterministic `MediaStorageService.object_key()` and `StoredMedia`.
- Produces: `MediaIntegrityError(MediaStorageUnavailableError)`.
- Produces: `async MediaStorageService.ensure_minio_ready() -> None`.
- Produces: `async MediaStorageService.ensure_verified_minio_copy(asset, source_path, *, file_size, sha256, mime_type) -> StoredMedia`.
- Produces: `async MediaStorageService.remove_minio_copy(stored: StoredMedia) -> None` for best-effort rollback.
- Guarantees: `source_path` is never unlinked or moved by these interfaces.

- [ ] **Step 1: Extend the fake MinIO and write failing safety tests**

Track upload and removal calls in `FakeMinio`, then add:

```python
def test_verified_minio_copy_reads_back_sha256_and_keeps_source(
    tmp_path: Path,
) -> None:
    content = b"verified-local-video"
    source = tmp_path / "source.mp4"
    source.write_bytes(content)
    fake = FakeMinio()
    service = MediaStorageService(client_factory=lambda: fake)  # type: ignore[arg-type]
    asset = make_asset(MediaStorageBackend.local)

    stored = asyncio.run(
        service.ensure_verified_minio_copy(
            asset,
            source,
            file_size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            mime_type="video/mp4",
        )
    )

    assert stored.backend == MediaStorageBackend.minio
    assert source.read_bytes() == content
    assert fake.get_object_calls == 1


def test_corrupt_minio_readback_raises_and_keeps_source(tmp_path: Path) -> None:
    content = b"local-source-is-authoritative"
    source = tmp_path / "source.mp4"
    source.write_bytes(content)
    fake = FakeMinio(readback_override=b"corrupt")
    service = MediaStorageService(client_factory=lambda: fake)  # type: ignore[arg-type]

    with pytest.raises(MediaIntegrityError):
        asyncio.run(
            service.ensure_verified_minio_copy(
                make_asset(MediaStorageBackend.local),
                source,
                file_size=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                mime_type="video/mp4",
            )
        )

    assert source.read_bytes() == content
    assert fake.remove_object_calls == 1
```

Also test that an existing object whose size, metadata digest and full readback digest all match is reused without calling `fput_object`.

- [ ] **Step 2: Run storage tests and confirm RED**

Run: `uv run pytest tests/douyin/test_media_storage.py -k "verified_minio or corrupt_minio or existing_verified" -v`

Expected: tests fail because the new exception and methods do not exist.

- [ ] **Step 3: Implement MinIO preflight, upload and complete readback**

Implement a synchronous helper invoked through `asyncio.to_thread`. It must:

```python
expected_key = self.object_key(asset.task_id, asset.aweme_id)
expected_bucket = settings.MINIO_BUCKET
```

It ensures the bucket exists, checks whether an existing object can be reused, uploads with `metadata={"sha256": sha256}`, verifies `stat.size == file_size`, streams the complete object through `get_object`, computes `hashlib.sha256`, closes and releases the response in `finally`, and compares with `hmac.compare_digest`. On mismatch it removes the target object best-effort and raises `MediaIntegrityError("MinIO object integrity verification failed")`. It returns `StoredMedia(backend=minio, local_path="", ...)` only after verification. It does not call `unlink`, `replace`, `move` or `rmtree` on `source_path`.

`ensure_minio_ready()` validates credentials/endpoint, creates the configured bucket if needed, and converts MinIO failures to `MediaStorageUnavailableError` without logging secrets.

- [ ] **Step 4: Run the full storage test file**

Run:

```bash
uv run pytest tests/douyin/test_media_storage.py -v
uv run ruff check app/services/media_storage.py tests/douyin/test_media_storage.py
uv run mypy app/services/media_storage.py
```

Expected: all commands pass and the pre-existing direct-download upload test still confirms staged-file deletion only in `store()`.

- [ ] **Step 5: Commit the storage primitive**

```bash
git add backend/app/services/media_storage.py backend/tests/douyin/test_media_storage.py
git commit -m "feat: verify MinIO media copies"
```

---

### Task 3: Persistent Migration Manager, Safe Switch and Restart Recovery

**Files:**
- Create: `backend/app/services/media_migration.py`
- Modify: `backend/app/services/media_pipeline.py`
- Modify: `backend/app/services/douyin_tasks.py`
- Create: `backend/tests/douyin/test_media_migration.py`
- Modify: `backend/tests/douyin/test_media_pipeline.py`

**Interfaces:**
- Consumes: `MediaStorageService.ensure_verified_minio_copy()`, `remove_minio_copy()`, migration model fields and `settings.MEDIA_MIGRATION_CONCURRENCY`.
- Produces: `MigrationEnqueueResult(queued: int, skipped: int)`.
- Produces: `MediaMigrationManager.startup()`, `shutdown()`, `enqueue_task(task_id, asset_ids)`, `wait_for_task(task_id)`.
- Produces singleton: `media_migration_manager`.
- Produces public projection and summary counts through existing `media_public()` and `media_summary_sync()`.

- [ ] **Step 1: Write failing happy-path and failure-order tests**

Create a local downloaded asset under a temporary `MEDIA_OUTPUT_DIR`, inject an async fake storage service, and assert the committed state:

```python
def test_migration_switches_only_after_verified_copy_and_deletes_local(
    db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task, asset, source = create_local_asset(db, tmp_path, b"complete-video")
    storage = RecordingMigrationStorage(source)
    manager = MediaMigrationManager(storage=storage)

    result = asyncio.run(manager.enqueue_task(task.id, [asset.id]))
    asyncio.run(manager.wait_for_task(task.id))
    db.expire_all()
    migrated = db.get(DouyinMediaAsset, asset.id)

    assert result == MigrationEnqueueResult(queued=1, skipped=0)
    assert storage.events == ["upload", "verify"]
    assert migrated is not None
    assert migrated.storage_backend == MediaStorageBackend.minio.value
    assert migrated.local_path == ""
    assert migrated.migration_status == MediaMigrationStatus.completed.value
    assert not source.exists()
```

Add a verification-failure test whose fake raises `MediaIntegrityError` and assert `storage_backend == local`, `local_path` unchanged, source still exists, migration status failed and the stored error contains no URL or credential text.

- [ ] **Step 2: Run manager tests and confirm RED**

Run: `uv run pytest tests/douyin/test_media_migration.py -k "switches_only or verification_failure" -v`

Expected: collection fails because `MediaMigrationManager` does not exist.

- [ ] **Step 3: Implement queueing, state transitions and safe deletion**

Implement `MediaMigrationManager` with one semaphore and a handle map keyed by asset ID. `enqueue_task()` selects all task assets when `asset_ids` is empty, or validates the provided IDs; it queues only downloaded local assets in `idle`/`failed` and MinIO assets in `cleanup_pending`.

For a local asset, `_run_asset()` performs these exact phases:

```text
claim queued -> uploading
validate source under MEDIA_OUTPUT_DIR
compute local size and SHA-256
ensure_verified_minio_copy
set verifying/switching progress
transactionally set MinIO bucket/key/backend and cleanup_pending while retaining local_path
unlink the one validated local file
transactionally clear local_path and set completed/100
```

The database switch method must re-read the row and require local backend, downloaded status, matching `local_path` and a running migration state before updating it. If that commit raises, do not unlink the source and invoke `remove_minio_copy()` best-effort. Local deletion must revalidate the path against `MEDIA_OUTPUT_DIR` immediately before `Path.unlink()`.

- [ ] **Step 4: Add cleanup-pending, idempotency and recovery tests**

Add tests for:

```python
assert failed_cleanup.storage_backend == "minio"
assert failed_cleanup.migration_status == "cleanup_pending"
assert Path(failed_cleanup.local_path).exists()
```

Then retry the same asset after allowing unlink and assert it does not call upload again, clears `local_path`, deletes the file and completes. Add a duplicate enqueue test expecting one queued and one skipped. Seed `queued`, `uploading`, `verifying`, `switching` and `cleanup_pending` records, call `startup()`, wait, and assert they converge through the appropriate upload or cleanup path.

- [ ] **Step 5: Project migration fields and counts**

Update `media_public()` to include every public migration field. Update `media_summary_sync()` so:

```python
local_downloaded = sum(
    status == MediaDownloadStatus.downloaded.value
    and backend == MediaStorageBackend.local.value
    for status, backend in asset_rows
)
migration_running = sum(
    value in {"uploading", "verifying", "switching"}
    for value in migration_statuses
)
```

Count the remaining migration states exactly as declared in Task 1. Extend existing pipeline response tests to assert local/MinIO and migration counts.

- [ ] **Step 6: Wire application startup and shutdown**

In `DouyinTaskManager.startup()`, call `await media_migration_manager.startup()` after media pipeline startup. In shutdown, cancel crawler/media tasks first and then `await media_migration_manager.shutdown()`. Add an isolated manager lifecycle test proving startup is invoked once and shutdown waits for handles.

- [ ] **Step 7: Run manager and pipeline tests**

Run:

```bash
uv run pytest tests/douyin/test_media_migration.py tests/douyin/test_media_pipeline.py -v
uv run ruff check app/services/media_migration.py app/services/media_pipeline.py app/services/douyin_tasks.py tests/douyin/test_media_migration.py tests/douyin/test_media_pipeline.py
uv run mypy app/services/media_migration.py app/services/media_pipeline.py app/services/douyin_tasks.py
```

Expected: all commands pass.

- [ ] **Step 8: Commit the persistent manager**

```bash
git add backend/app/services/media_migration.py backend/app/services/media_pipeline.py backend/app/services/douyin_tasks.py backend/tests/douyin/test_media_migration.py backend/tests/douyin/test_media_pipeline.py
git commit -m "feat: migrate local media to MinIO"
```

---

### Task 4: Owner-Scoped FastAPI Migration Endpoint

**Files:**
- Modify: `backend/app/api/routes/douyin.py`
- Modify: `backend/tests/api/routes/test_douyin.py`

**Interfaces:**
- Consumes: `DouyinMediaMigrationRequest`, `DouyinMediaMigrationAccepted`, `media_storage.ensure_minio_ready()` and `media_migration_manager.enqueue_task()`.
- Produces: `POST /api/v1/douyin/tasks/{task_id}/media/migrate-to-minio` with operation ID `douyin-migrate-media-to-minio` and HTTP 202.

- [ ] **Step 1: Write failing API tests**

Add an authorized test that monkeypatches readiness and queueing, posts `{"asset_ids": [asset_id]}`, then asserts 202 and:

```python
assert response.json() == {
    "queued": 1,
    "skipped": 0,
    "message": "Queued 1 media migrations",
}
queue.assert_awaited_once_with(task.id, [asset.id])
```

Add tests for another user's task returning 403 without invoking readiness, unknown requested asset returning 404, MinIO preflight failure returning 503 with generic detail, and a specified list with zero queued items returning 409. Add an empty-list task-wide request returning 202 with the manager's queued/skipped counts.

- [ ] **Step 2: Run API tests and confirm RED**

Run: `uv run pytest tests/api/routes/test_douyin.py -k migrate_media_to_minio -v`

Expected: requests return 404 because the route does not exist.

- [ ] **Step 3: Implement the route**

The route must call `_get_task()` first, verify every supplied asset belongs to the same task without exposing another task's asset, run MinIO preflight through `asyncio.to_thread` only if the storage method is synchronous or await the async interface from Task 2, then call:

```python
result = await media_migration_manager.enqueue_task(task_id, request.asset_ids)
```

Map `MediaStorageUnavailableError` to HTTP 503 detail `"Media storage is unavailable"`. Return `DouyinMediaMigrationAccepted`; for an explicit non-empty list with `queued == 0`, return HTTP 409 detail `"Selected media cannot be migrated"`.

- [ ] **Step 4: Run route tests and focused lint/type checks**

Run:

```bash
uv run pytest tests/api/routes/test_douyin.py -k "migrate_media_to_minio or media_summary or preview" -v
uv run ruff check app/api/routes/douyin.py tests/api/routes/test_douyin.py
uv run mypy app/api/routes/douyin.py
```

Expected: all commands pass.

- [ ] **Step 5: Commit the API unit**

```bash
git add backend/app/api/routes/douyin.py backend/tests/api/routes/test_douyin.py
git commit -m "feat: expose MinIO media migration API"
```

---

### Task 5: MCP Migration Tool

**Files:**
- Modify: `backend/app/mcp_server/server.py`
- Create: `backend/tests/douyin/test_mcp_server.py`

**Interfaces:**
- Consumes: FastAPI endpoint from Task 4 through the existing authenticated `api.request()` gateway.
- Produces: `_request_douyin_media_migration(task_id: str, asset_ids: list[str]) -> dict[str, Any]`.
- Produces MCP tool: `migrate_douyin_media_to_minio(task_id: str, asset_ids: list[str] | None = None)`.

- [ ] **Step 1: Write a failing gateway helper test**

```python
def test_mcp_media_migration_forwards_only_task_and_asset_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = AsyncMock(return_value={"queued": 2, "skipped": 1, "message": "ok"})
    monkeypatch.setattr(server.api, "request", request)

    result = asyncio.run(
        server._request_douyin_media_migration("task-1", ["asset-1", "asset-2"])
    )

    request.assert_awaited_once_with(
        "POST",
        "/douyin/tasks/task-1/media/migrate-to-minio",
        json_body={"asset_ids": ["asset-1", "asset-2"]},
    )
    assert result["queued"] == 2
```

Add a test for `asset_ids=None` producing `{"asset_ids": []}`. Assert no MinIO credential, Cookie, Token or local path key appears in the body.

- [ ] **Step 2: Run the MCP test and confirm RED**

Run: `uv run pytest tests/douyin/test_mcp_server.py -v`

Expected: fails because `_request_douyin_media_migration` is missing.

- [ ] **Step 3: Implement helper and decorated tool**

Implement the exact gateway helper and a thin `@mcp.tool()` wrapper. The wrapper docstring must explain that an empty list migrates all eligible local videos and that local deletion occurs only after full remote verification. Do not accept MinIO endpoint or credential parameters.

- [ ] **Step 4: Run MCP tests and static checks**

Run:

```bash
uv run pytest tests/douyin/test_mcp_server.py -v
uv run ruff check app/mcp_server/server.py tests/douyin/test_mcp_server.py
uv run mypy app/mcp_server/server.py
```

Expected: all commands pass.

- [ ] **Step 5: Commit the MCP unit**

```bash
git add backend/app/mcp_server/server.py backend/tests/douyin/test_mcp_server.py
git commit -m "feat: expose media migration through MCP"
```

---

### Task 6: Generated Client and React Migration Experience

**Files:**
- Modify: `frontend/openapi.json`
- Modify: generated files under `frontend/src/client/`
- Create: `frontend/src/components/Douyin/MediaMigrationDialog.tsx`
- Modify: `frontend/src/components/Douyin/MediaPipelinePanel.tsx`
- Modify: `frontend/tests/douyin.spec.ts`

**Interfaces:**
- Consumes: generated `DouyinService.migrateMediaToMinio()`, migration fields on `DouyinMediaAssetPublic`, migration counters on `DouyinMediaSummaryPublic`.
- Produces: task-level confirmation dialog, per-row migration state/progress, task-wide and single-item retry controls.

- [ ] **Step 1: Add a failing Playwright migration scenario**

Mock one downloaded local asset and summary `local_downloaded: 1`. Intercept the migration endpoint and assert:

```typescript
expect(request.postDataJSON()).toEqual({ asset_ids: [] })
```

The test opens the task page, clicks `上传本地视频到 MinIO（1）`, verifies the warning text `完整回读校验通过后才会删除本地文件`, confirms, waits for one POST, and expects the success toast `已提交 1 个视频迁移任务`. Add a second row fixture with `migration_status: "failed"` and assert the row button `重试迁移到 MinIO` posts that one asset ID.

- [ ] **Step 2: Run the browser test and confirm RED**

Run: `bunx playwright test tests/douyin.spec.ts -g "uploads local media to MinIO"`

Working directory: `frontend`

Expected: fails because the migration button and dialog do not exist.

- [ ] **Step 3: Regenerate the OpenAPI client**

From the repository root run `bash ./scripts/generate-client.sh` in an environment with backend dependencies and Bun available. Confirm generated types contain all Task 1 fields and the generated service method targets `/media/migrate-to-minio`. Do not hand-edit generated client files.

- [ ] **Step 4: Implement the dialog**

`MediaMigrationDialog` receives `taskId: string`, `eligibleCount: number`, optional `assetIds: string[]`, and `onQueued: () => Promise<void>`. It uses a TanStack mutation calling:

```typescript
DouyinService.migrateMediaToMinio({
  taskId,
  requestBody: { asset_ids: assetIds ?? [] },
})
```

The dialog describes upload, full readback size/SHA-256 verification, database switch and final local deletion in that order. On success it closes, shows `已提交 ${result.queued} 个视频迁移任务`, and invalidates media and summary queries.

- [ ] **Step 5: Add migration status and polling to the panel**

Treat `queued`, `uploading`, `verifying`, `switching` and `cleanup_pending` as processing states for 2-second polling. Add a “存储迁移” column using exact Chinese labels:

```typescript
const migrationLabels = {
  idle: "未迁移",
  queued: "等待上传",
  uploading: "上传中",
  verifying: "完整性校验中",
  switching: "切换存储中",
  cleanup_pending: "MinIO 已生效，等待清理本地文件",
  completed: "迁移完成",
  failed: "迁移失败",
}
```

Show the top-level dialog when `summary.local_downloaded > 0` or failed local assets exist. For a failed local asset render a single-item dialog/button with `assetIds={[asset.id]}`. Continue rendering preview/download actions from `download_available`; a `cleanup_pending` MinIO asset remains playable.

- [ ] **Step 6: Update all test response fixtures**

Every mocked media summary receives all seven migration counters. Every mocked media asset receives `migration_status`, `migration_progress`, `migration_attempt_count`, `migration_error`, `migration_started_at`, and `migration_finished_at`. Use neutral defaults (`idle`, 0, 0, null, null, null) unless the test exercises migration.

- [ ] **Step 7: Run frontend tests, lint and build**

Run from `frontend`:

```bash
bunx playwright test tests/douyin.spec.ts
bun run lint
bun run build
```

Expected: all commands pass. Review formatter changes and keep only feature-related output.

- [ ] **Step 8: Commit the frontend unit**

```bash
git add frontend/openapi.json frontend/src/client frontend/src/components/Douyin/MediaMigrationDialog.tsx frontend/src/components/Douyin/MediaPipelinePanel.tsx frontend/tests/douyin.spec.ts
git commit -m "feat: manage MinIO media migrations in UI"
```

---

### Task 7: Documentation, Full Review, Real MinIO Smoke and Delivery

**Files:**
- Modify: `README.md`
- Review: every file committed in Tasks 1–6

**Interfaces:**
- Consumes: completed backend, MCP and frontend behavior.
- Produces: documented configuration and evidence that the feature works after migration and service restart.

- [ ] **Step 1: Document configuration and operator workflow**

Document `MEDIA_MIGRATION_CONCURRENCY=2`, the task-page action, strict full-object SHA-256 readback, `cleanup_pending`, retry/restart behavior, and the MCP tool. State explicitly that MinIO upload acknowledgement or ETag alone does not trigger local deletion.

- [ ] **Step 2: Review the complete diff for safety and encoding**

Run:

```bash
git diff 234f417..HEAD --check
git diff 234f417..HEAD --stat
rg -n "local_path|MINIO_SECRET_KEY|cookies|token" backend/app/services/media_migration.py backend/app/api/routes/douyin.py backend/app/mcp_server/server.py
```

Inspect every match. Confirm paths and secrets are not returned or logged, and confirm all Chinese source files decode as UTF-8 without mojibake.

- [ ] **Step 3: Run the complete backend quality gate**

From `backend` run:

```bash
uv run ruff check app tests
uv run mypy app
uv run python -m compileall -q app
uv run pytest
```

Expected: all commands pass with no skipped migration safety test.

- [ ] **Step 4: Validate Alembic upgrade and downgrade**

Against the test/local PostgreSQL database, record the current revision, run `uv run alembic upgrade head`, confirm revision `f47a8c1d9e20`, downgrade one revision, verify the six columns and migration-status index are removed, then upgrade to head again. Do not downgrade a production database or a database with irreplaceable user data.

- [ ] **Step 5: Build Docker images**

Run from the repository root:

```bash
docker compose -f compose.yml -f compose.storage.yml build backend frontend
```

Expected: both images build successfully from the current commit.

- [ ] **Step 6: Restart services under the active deployment method**

First inspect listeners and Compose services. Stop only the existing backend and frontend instances, leaving PostgreSQL, MinIO and the CDP browser container intact. Apply `alembic upgrade head`, start new backend and frontend processes/containers, then wait for backend health and frontend HTTP 200. Record the new process IDs or container IDs and verify the old backend/frontend instances are gone.

- [ ] **Step 7: Run authenticated real-MinIO business smoke**

Use an authenticated test/admin user and a disposable task/asset under `MEDIA_OUTPUT_DIR`:

1. Write deterministic video bytes locally and persist their size and SHA-256 as a downloaded local asset.
2. Confirm the existing preview session and `Range: bytes=0-1023` stream return 201 then 206 from local storage.
3. POST the migration endpoint with that asset ID and expect 202/queued 1.
4. Poll media details until `migration_status=completed`.
5. Assert `storage_backend=minio`, `local_path` is empty in the database, and the original local file no longer exists.
6. Read the MinIO object completely, assert size and SHA-256 equal the original deterministic bytes.
7. Create a new preview session and assert the same Range request returns 206 and the expected bytes through MinIO.
8. Verify the media download and subtitle metadata remain available.

Delete only the disposable smoke-test database rows and MinIO object after recording results; do not touch user task assets.

- [ ] **Step 8: Run frontend business regression against restarted services**

Run the complete `frontend/tests/douyin.spec.ts` suite against the restarted frontend. Log in through the real API, open a task with local media if one is safely available, and confirm the confirmation dialog and counts load without browser console or network errors. Do not trigger migration on a user-owned asset during smoke testing.

- [ ] **Step 9: Commit documentation and any verified test-only fixture**

```bash
git add README.md
git commit -m "docs: explain verified MinIO media migration"
```

- [ ] **Step 10: Final verification and handoff**

Run `git status --short` and require a clean worktree. Report commit IDs, migration revision, backend and frontend test totals, Docker build results, new service IDs, real MinIO size/SHA-256 evidence, local deletion evidence and post-migration preview 206 evidence. Do not claim completion if any required check is missing or failing.
