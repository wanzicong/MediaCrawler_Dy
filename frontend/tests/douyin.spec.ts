import { expect, test } from "@playwright/test"

const emptyMigrationSummary = {
  local_downloaded: 0,
  minio_downloaded: 0,
  migration_queued: 0,
  migration_running: 0,
  migration_cleanup_pending: 0,
  migration_completed: 0,
  migration_failed: 0,
}

const idleMediaMigration = {
  migration_status: "idle",
  migration_progress: 0,
  migration_attempt_count: 0,
  migration_error: null,
  migration_started_at: null,
  migration_finished_at: null,
}

test("opens the Douyin task page and validates the create form", async ({
  page,
}) => {
  await page.goto("/douyin")

  await expect(
    page.getByRole("heading", { name: "抖音爬取任务" }),
  ).toBeVisible()
  await page.getByRole("button", { name: "创建任务" }).click()
  await expect(
    page.getByRole("heading", { name: "创建抖音爬取任务" }),
  ).toBeVisible()
  await expect(page.getByLabel("搜索关键词")).toBeVisible()
  await expect(page.getByText("视频下载与字幕")).toBeVisible()
  await page.getByRole("checkbox").nth(3).click()
  await expect(
    page.getByText("逐条异步处理", { exact: true }).first(),
  ).toBeVisible()
  await expect(page.getByLabel("视频语言")).toBeVisible()

  await page.getByRole("button", { name: "创建并运行" }).click()
  await expect(page.getByText("请填写搜索关键词")).toBeVisible()
})

test("clears a stale session when its user no longer exists", async ({
  page,
}) => {
  await page.route("**/api/v1/users/me", async (route) => {
    await route.fulfill({
      status: 404,
      contentType: "application/json",
      json: { detail: "User not found" },
    })
  })

  await page.goto("/douyin")

  await page.waitForURL("/login")
  expect(
    await page.evaluate(() => localStorage.getItem("access_token")),
  ).toBeNull()
})

test("renders a waiting-login task and its protected QR code", async ({
  page,
}) => {
  const taskId = "38a8148c-c8b6-4c6c-b7c4-93580d687388"
  const now = new Date().toISOString()
  const png = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
    "base64",
  )

  await page.route(`**/api/v1/douyin/tasks/${taskId}**`, async (route) => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname.endsWith("/media-summary")) {
      await route.fulfill({
        json: {
          total: 0,
          queued: 0,
          downloading: 0,
          downloaded: 0,
          download_failed: 0,
          subtitle_pending: 0,
          subtitle_running: 0,
          subtitle_completed: 0,
          subtitle_failed: 0,
          ...emptyMigrationSummary,
        },
      })
      return
    }
    if (pathname.endsWith("/media")) {
      await route.fulfill({ json: { data: [], count: 0 } })
      return
    }
    if (pathname.endsWith("/qrcode")) {
      await route.fulfill({ status: 200, contentType: "image/png", body: png })
      return
    }
    if (pathname.endsWith("/awemes")) {
      await route.fulfill({ json: { data: [], count: 0 } })
      return
    }
    await route.fulfill({
      json: {
        id: taskId,
        owner_id: "c7e0bb1c-891a-4b4a-8f12-26c1ddd8239d",
        crawl_type: "search",
        status: "waiting_login",
        request: {
          crawl_type: "search",
          login_type: "qrcode",
          keywords: ["FastAPI"],
          max_awemes: 10,
        },
        aweme_count: 0,
        comment_count: 0,
        action_count: 0,
        error: null,
        has_qrcode: true,
        created_at: now,
        started_at: now,
        finished_at: null,
      },
    })
  })

  await page.goto(`/douyin/${taskId}`)

  await expect(
    page.getByText("等待扫码登录", { exact: true }).last(),
  ).toBeVisible()
  await expect(page.getByAltText("抖音登录二维码")).toBeVisible()
  await expect(page.getByText("FastAPI", { exact: true })).toBeVisible()
})

test("shows an accepted media resume with actionable live progress", async ({
  page,
}) => {
  const taskId = "0dfdf538-0bf9-43f2-94a6-b2757840f81d"
  const assetId = "58a8148c-c8b6-4c6c-b7c4-93580d687300"
  const now = new Date().toISOString()

  await page.route(`**/api/v1/douyin/tasks/${taskId}**`, async (route) => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname.endsWith("/media-summary")) {
      await route.fulfill({
        json: {
          total: 14,
          queued: 4,
          downloading: 3,
          downloaded: 6,
          download_failed: 1,
          subtitle_pending: 0,
          subtitle_running: 0,
          subtitle_completed: 6,
          subtitle_failed: 0,
          local_downloaded: 6,
          minio_downloaded: 0,
          ...emptyMigrationSummary,
        },
      })
      return
    }
    if (pathname.endsWith("/works")) {
      await route.fulfill({
        json: {
          count: 1,
          data: [
            {
              aweme: {
                id: "78a8148c-c8b6-4c6c-b7c4-93580d687300",
                task_id: taskId,
                aweme_id: "7647937915624551281",
                aweme_type: "0",
                title: "恢复中的视频",
                description: "",
                create_time: 1_700_000_000,
                creator_hash: "creator-hash",
                sec_uid: "anonymous-sec-uid",
                nickname: "测**户",
                liked_count: 10,
                collected_count: 2,
                comment_count: 1,
                share_count: 0,
                aweme_url: "",
                cover_url: "",
                video_download_url: "",
                music_download_url: "",
                note_download_url: "",
                source_keyword: "恢复",
                fetched_at: now,
              },
              persisted_comment_count: 0,
              media: {
                id: assetId,
                task_id: taskId,
                aweme_id: "7647937915624551281",
                storage_backend: "local",
                status: "downloading",
                progress: 6,
                attempt_count: 3,
                mime_type: "video/mp4",
                file_size: 0,
                sha256: "",
                error: null,
                download_available: false,
                created_at: now,
                updated_at: now,
                completed_at: null,
                ...idleMediaMigration,
                subtitle: null,
              },
            },
          ],
        },
      })
      return
    }
    if (pathname.endsWith("/media")) {
      await route.fulfill({ json: { data: [], count: 0 } })
      return
    }
    if (pathname.endsWith("/awemes")) {
      await route.fulfill({ json: { data: [], count: 0 } })
      return
    }
    await route.fulfill({
      json: {
        id: taskId,
        owner_id: "c7e0bb1c-891a-4b4a-8f12-26c1ddd8239d",
        crawl_type: "search",
        status: "processing_media",
        request: {
          crawl_type: "search",
          keywords: ["恢复"],
          download_media: true,
          translate_subtitles: true,
        },
        aweme_count: 14,
        comment_count: 91,
        action_count: 0,
        checkpoint_phase: "completed",
        resume_count: 3,
        can_resume_crawl: false,
        can_resume_media: false,
        error: null,
        has_qrcode: false,
        created_at: now,
        started_at: now,
        finished_at: null,
        last_resumed_at: now,
      },
    })
  })

  await page.goto(`/douyin/${taskId}`)

  await expect(page.getByText("当前阶段：媒体处理")).toBeVisible()
  await expect(page.getByText("第 3 次恢复正在执行")).toBeVisible()
  await expect(page.getByText("第 3 次恢复正在处理媒体")).toBeVisible()
  await expect(
    page.getByText("下载中 3 条，排队 4 条，下载失败 1 条", { exact: false }),
  ).toBeVisible()
  await expect(page.getByText("视频完成").locator("..")).toContainText("6 / 14")
  await expect(page.getByText("已尝试 3 次", { exact: false })).toBeVisible()
})

test("shows media progress, persisted subtitle and retranslation action", async ({
  page,
}) => {
  const taskId = "48a8148c-c8b6-4c6c-b7c4-93580d687399"
  const assetId = "58a8148c-c8b6-4c6c-b7c4-93580d687399"
  const secondAssetId = "58a8148c-c8b6-4c6c-b7c4-93580d687398"
  const now = new Date().toISOString()
  let retranslateCalls = 0
  let previewSessionCalls = 0
  let previewStreamCalls = 0
  let previewSessionUrl = ""

  await page.route(`**/api/v1/douyin/tasks/${taskId}**`, async (route) => {
    const url = new URL(route.request().url())
    const pathname = url.pathname
    if (pathname.endsWith(`/media/${assetId}/preview-session`)) {
      previewSessionCalls += 1
      previewSessionUrl = url.toString()
      await route.fulfill({
        status: 201,
        json: { message: "Media preview session created" },
      })
      return
    }
    if (pathname.endsWith(`/media/${assetId}/preview`)) {
      previewStreamCalls += 1
      await route.fulfill({
        status: 206,
        contentType: "video/mp4",
        headers: {
          "Accept-Ranges": "bytes",
          "Content-Range": "bytes 0-3/4",
          "Content-Length": "4",
        },
        body: Buffer.from([0, 0, 0, 0]),
      })
      return
    }
    if (pathname.endsWith(`/media/${secondAssetId}/preview-session`)) {
      await route.fulfill({
        status: 201,
        json: { message: "Media preview session created" },
      })
      return
    }
    if (pathname.endsWith(`/media/${secondAssetId}/preview`)) {
      await route.fulfill({
        status: 206,
        contentType: "video/mp4",
        headers: {
          "Accept-Ranges": "bytes",
          "Content-Range": "bytes 0-3/4",
          "Content-Length": "4",
        },
        body: Buffer.from([0, 0, 0, 0]),
      })
      return
    }
    if (pathname.endsWith(`/media/${assetId}/retranslate`)) {
      retranslateCalls += 1
      await route.fulfill({ json: { message: "Subtitle translation queued" } })
      return
    }
    if (pathname.endsWith("/works")) {
      await route.fulfill({
        json: {
          count: 2,
          data: [
            {
              aweme: {
                id: "78a8148c-c8b6-4c6c-b7c4-93580d687390",
                task_id: taskId,
                aweme_id: "123456",
                aweme_type: "0",
                title: "可预览的视频",
                description: "",
                create_time: 1_700_000_000,
                creator_hash: "creator-hash",
                sec_uid: "anonymous-sec-uid",
                nickname: "测**户",
                liked_count: 10,
                collected_count: 2,
                comment_count: 1,
                share_count: 0,
                aweme_url: "https://www.douyin.com/video/123456",
                cover_url: "",
                video_download_url: "",
                music_download_url: "",
                note_download_url: "",
                source_keyword: "测试",
                fetched_at: now,
              },
              persisted_comment_count: 0,
              media: {
                id: assetId,
                task_id: taskId,
                aweme_id: "123456",
                storage_backend: "local",
                status: "downloaded",
                progress: 100,
                attempt_count: 1,
                mime_type: "video/mp4",
                file_size: 1024,
                sha256: "abc",
                error: null,
                download_available: true,
                created_at: now,
                updated_at: now,
                completed_at: now,
                ...idleMediaMigration,
                subtitle: {
                  id: "68a8148c-c8b6-4c6c-b7c4-93580d687399",
                  asset_id: assetId,
                  task_id: taskId,
                  aweme_id: "123456",
                  status: "completed",
                  progress: 100,
                  attempt_count: 1,
                  requested_backend: "api",
                  actual_backend: "api",
                  model: "whisper-1",
                  language: "zh",
                  duration_seconds: 3,
                  full_text: "这是远程 API 返回的字幕",
                  segments: [],
                  error: null,
                  created_at: now,
                  started_at: now,
                  finished_at: now,
                },
              },
            },
            {
              aweme: {
                id: "78a8148c-c8b6-4c6c-b7c4-93580d687391",
                task_id: taskId,
                aweme_id: "654321",
                aweme_type: "0",
                title: "可滑动切换的视频",
                description: "",
                create_time: 1_699_999_000,
                creator_hash: "creator-hash-2",
                sec_uid: "anonymous-sec-uid-2",
                nickname: "另一个作者",
                liked_count: 8,
                collected_count: 1,
                comment_count: 2,
                share_count: 1,
                aweme_url: "",
                cover_url: "",
                video_download_url: "",
                music_download_url: "",
                note_download_url: "",
                source_keyword: "测试",
                fetched_at: now,
              },
              persisted_comment_count: 1,
              media: {
                id: secondAssetId,
                task_id: taskId,
                aweme_id: "654321",
                storage_backend: "minio",
                status: "downloaded",
                progress: 100,
                attempt_count: 1,
                mime_type: "video/mp4",
                file_size: 2048,
                sha256: "def",
                error: null,
                download_available: true,
                created_at: now,
                updated_at: now,
                completed_at: now,
                ...idleMediaMigration,
                subtitle: null,
              },
            },
          ],
        },
      })
      return
    }
    if (pathname.endsWith("/media-summary")) {
      await route.fulfill({
        json: {
          total: 2,
          queued: 0,
          downloading: 0,
          downloaded: 2,
          download_failed: 0,
          subtitle_pending: 0,
          subtitle_running: 0,
          subtitle_completed: 1,
          subtitle_failed: 0,
          ...emptyMigrationSummary,
        },
      })
      return
    }
    if (pathname.endsWith("/media")) {
      await route.fulfill({
        json: {
          count: 1,
          data: [
            {
              id: assetId,
              task_id: taskId,
              aweme_id: "123456",
              storage_backend: "local",
              status: "downloaded",
              progress: 100,
              attempt_count: 1,
              mime_type: "video/mp4",
              file_size: 1024,
              sha256: "abc",
              error: null,
              download_available: true,
              created_at: now,
              updated_at: now,
              completed_at: now,
              ...idleMediaMigration,
              subtitle: {
                id: "68a8148c-c8b6-4c6c-b7c4-93580d687399",
                asset_id: assetId,
                task_id: taskId,
                aweme_id: "123456",
                status: "completed",
                progress: 100,
                attempt_count: 1,
                requested_backend: "api",
                actual_backend: "api",
                model: "whisper-1",
                language: "zh",
                duration_seconds: 3,
                full_text: "这是远程 API 返回的字幕",
                segments: [],
                error: null,
                created_at: now,
                started_at: now,
                finished_at: now,
              },
            },
          ],
        },
      })
      return
    }
    if (pathname.endsWith("/awemes")) {
      await route.fulfill({ json: { data: [], count: 0 } })
      return
    }
    await route.fulfill({
      json: {
        id: taskId,
        owner_id: "c7e0bb1c-891a-4b4a-8f12-26c1ddd8239d",
        crawl_type: "detail",
        status: "succeeded",
        request: {
          crawl_type: "detail",
          video_ids: ["123456"],
          download_media: true,
          translate_subtitles: true,
        },
        aweme_count: 1,
        comment_count: 0,
        action_count: 0,
        error: null,
        has_qrcode: false,
        created_at: now,
        started_at: now,
        finished_at: now,
      },
    })
  })

  await page.goto(`/douyin/${taskId}`)

  await expect(page.getByText("zh · 已完成", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: "预览视频" }).first().click()
  await expect(page.getByRole("heading", { name: "视频预览" })).toBeVisible()
  await expect(page.locator("video")).toHaveAttribute(
    "src",
    new RegExp(`/media/${assetId}/preview\\?v=`),
  )
  await expect.poll(() => previewSessionCalls).toBe(1)
  expect(new URL(previewSessionUrl).origin).toBe(new URL(page.url()).origin)
  await expect.poll(() => previewStreamCalls).toBeGreaterThan(0)
  await page.getByRole("button", { name: "Close" }).click()
  await page.getByRole("button", { name: "重新翻译" }).first().click()
  await expect.poll(() => retranslateCalls).toBe(1)
  await expect(
    page.getByRole("link", { name: "在抖音中打开视频" }).first(),
  ).toHaveAttribute("href", "https://www.douyin.com/video/123456")

  await page.getByRole("link", { name: "沉浸播放", exact: true }).click()
  await expect(page).toHaveURL(new RegExp(`/douyin/${taskId}/feed`))
  await expect(page.getByText("1 / 2", { exact: true })).toBeVisible()
  await page.mouse.wheel(0, 500)
  await expect(page.getByText("2 / 2", { exact: true })).toBeVisible()
  await expect(
    page.getByText("可滑动切换的视频", { exact: true }).first(),
  ).toBeVisible()
})

test("shows per-video comments and creates follow-up crawl tasks", async ({
  page,
}) => {
  const taskId = "78a8148c-c8b6-4c6c-b7c4-93580d687399"
  const childTaskId = "88a8148c-c8b6-4c6c-b7c4-93580d687399"
  const awemeId = "7390000000000000001"
  const now = new Date().toISOString()
  let recrawlCalls = 0

  const taskPayload = (id: string, crawlType = "search") => ({
    id,
    owner_id: "c7e0bb1c-891a-4b4a-8f12-26c1ddd8239d",
    crawl_type: crawlType,
    status: "succeeded",
    request:
      crawlType === "detail"
        ? { crawl_type: "detail", video_ids: [awemeId] }
        : { crawl_type: "search", keywords: ["作品操作"] },
    aweme_count: id === taskId ? 1 : 0,
    comment_count: id === taskId ? 1 : 0,
    action_count: 0,
    checkpoint_phase: "completed",
    resume_count: 0,
    can_resume_crawl: false,
    can_resume_media: false,
    error: null,
    has_qrcode: false,
    created_at: now,
    started_at: now,
    finished_at: now,
    last_resumed_at: null,
  })

  await page.route("**/api/v1/douyin/tasks/**", async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const pathname = url.pathname
    if (pathname.endsWith(`/awemes/${awemeId}/comments/recrawl`)) {
      const body = request.postDataJSON()
      expect(body.max_comments_per_aweme).toBe(12)
      expect(body.fetch_sub_comments).toBe(true)
      recrawlCalls += 1
      await route.fulfill({ json: taskPayload(childTaskId, "detail") })
      return
    }
    if (pathname.endsWith("/works")) {
      await route.fulfill({
        json: pathname.includes(taskId)
          ? {
              count: 1,
              data: [
                {
                  aweme: {
                    id: "98a8148c-c8b6-4c6c-b7c4-93580d687399",
                    task_id: taskId,
                    aweme_id: awemeId,
                    aweme_type: "0",
                    title: "可操作的视频",
                    description: "",
                    create_time: 1_700_000_000,
                    creator_hash: "creator-hash",
                    sec_uid: "anonymous-sec-uid",
                    nickname: "测**户",
                    liked_count: 10,
                    collected_count: 2,
                    comment_count: 1,
                    share_count: 0,
                    aweme_url: `https://www.douyin.com/video/${awemeId}`,
                    cover_url: "",
                    video_download_url: "",
                    music_download_url: "",
                    note_download_url: "",
                    source_keyword: "作品操作",
                    fetched_at: now,
                  },
                  persisted_comment_count: 1,
                  media: null,
                },
              ],
            }
          : { data: [], count: 0 },
      })
      return
    }
    if (pathname.endsWith("/media-summary")) {
      await route.fulfill({
        json: {
          total: 0,
          queued: 0,
          downloading: 0,
          downloaded: 0,
          download_failed: 0,
          subtitle_pending: 0,
          subtitle_running: 0,
          subtitle_completed: 0,
          subtitle_failed: 0,
          ...emptyMigrationSummary,
        },
      })
      return
    }
    if (pathname.endsWith("/media")) {
      await route.fulfill({ json: { data: [], count: 0 } })
      return
    }
    if (pathname.endsWith("/awemes")) {
      await route.fulfill({
        json: pathname.includes(taskId)
          ? {
              count: 1,
              data: [
                {
                  id: "98a8148c-c8b6-4c6c-b7c4-93580d687399",
                  task_id: taskId,
                  aweme_id: awemeId,
                  aweme_type: "0",
                  title: "可操作的视频",
                  description: "",
                  create_time: null,
                  creator_hash: "creator-hash",
                  sec_uid: "anonymous-sec-uid",
                  nickname: "测***户",
                  liked_count: 10,
                  collected_count: 2,
                  comment_count: 1,
                  share_count: 0,
                  aweme_url: `https://www.douyin.com/video/${awemeId}`,
                  cover_url: "",
                  video_download_url: "",
                  music_download_url: "",
                  note_download_url: "",
                  source_keyword: "作品操作",
                  fetched_at: now,
                },
              ],
            }
          : { data: [], count: 0 },
      })
      return
    }
    if (pathname.endsWith("/comments")) {
      expect(url.searchParams.get("aweme_id")).toBe(awemeId)
      await route.fulfill({
        json: {
          count: 1,
          data: [
            {
              id: "a8a8148c-c8b6-4c6c-b7c4-93580d687399",
              task_id: taskId,
              comment_id: "comment-1",
              aweme_id: awemeId,
              parent_comment_id: "0",
              content: "这是这个视频的评论",
              create_time: 1_700_000_000,
              creator_hash: "commenter-hash",
              sec_uid: "anonymous-commenter",
              nickname: "评***户",
              sub_comment_count: 2,
              like_count: 3,
              pictures: "",
              fetched_at: now,
            },
          ],
        },
      })
      return
    }
    await route.fulfill({
      json: pathname.includes(childTaskId)
        ? taskPayload(childTaskId, "detail")
        : taskPayload(taskId),
    })
  })

  await page.goto(`/douyin/${taskId}`)
  await expect(page.getByText("可操作的视频")).toBeVisible()

  await page.getByRole("button", { name: "查看评论" }).click()
  await expect(page.getByText("这是这个视频的评论")).toBeVisible()
  await page.keyboard.press("Escape")

  await page.getByRole("button", { name: "作者作品" }).click()
  await expect(page.getByText("最大作者作品数")).toBeVisible()
  await expect(page.getByText("同时抓取每个作品的评论")).toBeVisible()
  await page.keyboard.press("Escape")

  await page.getByRole("button", { name: "重爬评论" }).click()
  await page.getByLabel("每个视频最大评论数").fill("12")
  await page.getByText("抓取子评论", { exact: true }).click()
  await page.getByRole("button", { name: "创建并进入任务" }).click()

  await expect.poll(() => recrawlCalls).toBe(1)
  await page.waitForURL(`/douyin/${childTaskId}`)
})

test("uploads local media to MinIO only after explicit confirmation", async ({
  page,
}) => {
  const taskId = "b8a8148c-c8b6-4c6c-b7c4-93580d687399"
  const assetId = "c8a8148c-c8b6-4c6c-b7c4-93580d687399"
  const now = new Date().toISOString()
  let migrationCalls = 0

  await page.route(`**/api/v1/douyin/tasks/${taskId}**`, async (route) => {
    const request = route.request()
    const pathname = new URL(request.url()).pathname
    if (pathname.endsWith("/media/migrate-to-minio")) {
      expect(request.postDataJSON()).toEqual({ asset_ids: [] })
      migrationCalls += 1
      await route.fulfill({
        status: 202,
        json: { queued: 1, skipped: 0, message: "Queued 1 media migrations" },
      })
      return
    }
    if (pathname.endsWith("/media-summary")) {
      await route.fulfill({
        json: {
          total: 1,
          queued: 0,
          downloading: 0,
          downloaded: 1,
          download_failed: 0,
          subtitle_pending: 0,
          subtitle_running: 0,
          subtitle_completed: 0,
          subtitle_failed: 0,
          local_downloaded: 1,
          minio_downloaded: 0,
          migration_queued: 0,
          migration_running: 0,
          migration_cleanup_pending: 0,
          migration_completed: 0,
          migration_failed: 0,
        },
      })
      return
    }
    if (pathname.endsWith("/media")) {
      await route.fulfill({
        json: {
          count: 1,
          data: [
            {
              id: assetId,
              task_id: taskId,
              aweme_id: "7654321",
              storage_backend: "local",
              status: "downloaded",
              progress: 100,
              attempt_count: 1,
              mime_type: "video/mp4",
              file_size: 1024,
              sha256: "abc",
              error: null,
              download_available: true,
              created_at: now,
              updated_at: now,
              completed_at: now,
              migration_status: "idle",
              migration_progress: 0,
              migration_attempt_count: 0,
              migration_error: null,
              migration_started_at: null,
              migration_finished_at: null,
              subtitle: null,
            },
          ],
        },
      })
      return
    }
    if (pathname.endsWith("/awemes")) {
      await route.fulfill({ json: { data: [], count: 0 } })
      return
    }
    await route.fulfill({
      json: {
        id: taskId,
        owner_id: "c7e0bb1c-891a-4b4a-8f12-26c1ddd8239d",
        crawl_type: "detail",
        status: "succeeded",
        request: { crawl_type: "detail", video_ids: ["7654321"] },
        aweme_count: 1,
        comment_count: 0,
        action_count: 0,
        checkpoint_phase: "completed",
        resume_count: 0,
        can_resume_crawl: false,
        can_resume_media: false,
        error: null,
        has_qrcode: false,
        created_at: now,
        started_at: now,
        finished_at: now,
        last_resumed_at: null,
      },
    })
  })

  await page.goto(`/douyin/${taskId}`)
  await page.getByRole("button", { name: "上传本地视频到 MinIO（1）" }).click()
  await expect(
    page.getByText("完整回读校验通过后才会删除本地文件"),
  ).toBeVisible()
  await page.getByRole("button", { name: "确认上传并迁移" }).click()

  await expect.poll(() => migrationCalls).toBe(1)
  await expect(page.getByText("已提交 1 个视频迁移任务")).toBeVisible()
})

test("filters the cross-task video library and shows publish metadata", async ({
  page,
}) => {
  const taskId = "d8a8148c-c8b6-4c6c-b7c4-93580d687399"
  const assetId = "e8a8148c-c8b6-4c6c-b7c4-93580d687399"
  const now = new Date().toISOString()
  let observedSearch = ""

  await page.route("**/api/v1/douyin/library/**", async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith("/creators")) {
      await route.fulfill({
        json: {
          count: 1,
          data: [
            {
              creator_hash: "creator-library",
              nickname: "资源库作者",
              work_count: 1,
            },
          ],
        },
      })
      return
    }
    observedSearch = url.searchParams.get("search") || ""
    await route.fulfill({
      json: {
        count: 1,
        data: [
          {
            aweme: {
              id: "f8a8148c-c8b6-4c6c-b7c4-93580d687399",
              task_id: taskId,
              aweme_id: "7650000000000000001",
              aweme_type: "0",
              title: "资源库中的视频",
              description: "用于验证全局检索",
              create_time: 1_700_000_000,
              creator_hash: "creator-library",
              sec_uid: "anonymous-sec-uid",
              nickname: "资源库作者",
              liked_count: 1200,
              collected_count: 88,
              comment_count: 36,
              share_count: 9,
              aweme_url: "https://www.douyin.com/video/7650000000000000001",
              cover_url: "",
              video_download_url: "",
              music_download_url: "",
              note_download_url: "",
              source_keyword: "资源库",
              fetched_at: now,
            },
            persisted_comment_count: 10,
            media: {
              id: assetId,
              task_id: taskId,
              aweme_id: "7650000000000000001",
              storage_backend: "minio",
              status: "downloaded",
              progress: 100,
              attempt_count: 1,
              mime_type: "video/mp4",
              file_size: 1048576,
              sha256: "abc",
              error: null,
              download_available: true,
              created_at: now,
              updated_at: now,
              completed_at: now,
              ...idleMediaMigration,
              subtitle: null,
            },
          },
        ],
      },
    })
  })
  await page.route("**/api/v1/douyin/tasks?**", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })

  await page.goto("/douyin-library")
  await expect(page.getByRole("heading", { name: "视频资源库" })).toBeVisible()
  await expect(page.getByText("资源库中的视频")).toBeVisible()
  await expect(page.getByText("资源库作者").first()).toBeVisible()
  await expect(page.getByText("10").first()).toBeVisible()
  await expect(
    page.getByRole("link", { name: "在抖音中打开视频" }),
  ).toHaveAttribute("href", "https://www.douyin.com/video/7650000000000000001")
  await expect(page.getByRole("link", { name: "沉浸播放" })).toHaveAttribute(
    "href",
    new RegExp(`/douyin/${taskId}/feed\\?start=video-7650000000000000001$`),
  )

  await page.getByPlaceholder("搜索标题、描述、创作者或作品号").fill("全局检索")
  await expect.poll(() => observedSearch).toBe("全局检索")
})

test("manages keywords, syncs history and prepares batch task selection", async ({
  page,
}) => {
  const keywordId = "118a8148-c8b6-4c6c-b7c4-93580d687399"
  const now = new Date().toISOString()
  let bulkCreateCalls = 0
  let historySyncCalls = 0

  await page.route("**/api/v1/douyin/keywords/**", async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.pathname.endsWith("/bulk")) {
      bulkCreateCalls += 1
      expect(request.postDataJSON().keywords).toEqual(["新关键词"])
      await route.fulfill({
        status: 201,
        json: { data: [], created_count: 1, existing_count: 0 },
      })
      return
    }
    if (url.pathname.endsWith("/sync/history")) {
      historySyncCalls += 1
      await route.fulfill({
        json: {
          task_count: 2,
          keyword_count: 3,
          created_count: 1,
          binding_count: 2,
        },
      })
      return
    }
    if (url.pathname.endsWith(`/by-id/${keywordId}/tasks`)) {
      await route.fulfill({ json: [] })
      return
    }
    await route.fulfill({
      json: {
        count: 1,
        data: [
          {
            id: keywordId,
            keyword: "FastAPI 爬虫",
            enabled: true,
            notes: "技术内容方向",
            status: "crawled",
            task_count: 2,
            active_task_count: 0,
            success_task_count: 2,
            failed_task_count: 0,
            aweme_count: 18,
            last_task_id: null,
            last_task_status: "succeeded",
            last_crawled_at: now,
            created_at: now,
            updated_at: now,
          },
        ],
      },
    })
  })

  await page.goto("/douyin-keywords")
  await expect(page.getByRole("heading", { name: "关键词管理" })).toBeVisible()
  await expect(page.getByText("FastAPI 爬虫")).toBeVisible()
  await expect(
    page.getByRole("table").getByText("已爬取", { exact: true }),
  ).toBeVisible()
  await expect(page.getByText("18", { exact: true }).first()).toBeVisible()

  await page.getByRole("button", { name: "添加关键词" }).click()
  await page
    .getByRole("textbox", { name: "关键词", exact: true })
    .fill("新关键词")
  await page.getByRole("button", { name: "保存关键词" }).click()
  await expect.poll(() => bulkCreateCalls).toBe(1)

  await page.getByRole("button", { name: "同步历史任务" }).click()
  await expect.poll(() => historySyncCalls).toBe(1)

  await page.getByRole("checkbox").last().click()
  await expect(page.getByRole("button", { name: "批量创建任务" })).toBeEnabled()
})

test("shows live API documentation and MCP tool catalog", async ({ page }) => {
  await page.route("**/api/v1/system/integrations/", async (route) => {
    await route.fulfill({
      json: {
        api_title: "Douyin Crawler API",
        api_version: "0.1.0",
        api_openapi_url: "http://127.0.0.1:8000/api/v1/openapi.json",
        api_swagger_url: "http://127.0.0.1:8000/docs",
        api_operation_count: 1,
        api_operations: [
          {
            method: "POST",
            path: "/api/v1/douyin/tasks",
            summary: "创建抖音任务",
            description: "通过 CDP 创建爬取任务。",
            operation_id: "douyin-create_task",
            tags: ["douyin"],
            auth_required: true,
            parameters: [],
            request_body: {
              content: {
                "application/json": {
                  schema: { $ref: "#/components/schemas/CrawlTaskCreate" },
                },
              },
            },
            response_codes: ["202", "422"],
          },
        ],
        mcp_server_name: "Douyin Crawler API",
        mcp_streamable_http_url: "http://127.0.0.1:8766/mcp",
        mcp_health_url: "http://127.0.0.1:8766/health",
        mcp_stdio_command: "uv run python -m app.mcp_server",
        mcp_http_command:
          "uv run python -m app.mcp_server --transport streamable-http --host 127.0.0.1 --port 8766",
        mcp_tool_count: 1,
        mcp_tools: [
          {
            name: "create_douyin_task",
            title: null,
            description: "创建抖音任务，可使用托管账号或账号池。",
            input_schema: {
              type: "object",
              required: ["crawl_type"],
              properties: {
                crawl_type: {
                  type: "string",
                  enum: ["search", "detail"],
                },
              },
            },
            output_schema: { type: "object" },
          },
        ],
      },
    })
  })

  await page.goto("/developer-tools")
  await expect(page.getByRole("heading", { name: "开发者中心" })).toBeVisible()
  await expect(page.getByText("/api/v1/douyin/tasks")).toBeVisible()
  await expect(page.getByText("创建抖音任务", { exact: true })).toBeVisible()

  await page.getByRole("tab", { name: "MCP 工具" }).click()
  await expect(page.getByText("create_douyin_task")).toBeVisible()
  await page.getByText("create_douyin_task").click()
  await expect(page.getByText("crawl_type")).toBeVisible()
  await expect(page.getByText("search / detail")).toBeVisible()
})

test("discovers remote browser slots and auto-assigns an available slot", async ({
  page,
}) => {
  const accountId = "318a8148-c8b6-4c6c-b7c4-93580d687300"
  const now = new Date().toISOString()
  let createCalls = 0

  await page.route("**/api/v1/douyin/accounts**", async (route) => {
    const request = route.request()
    const pathname = new URL(request.url()).pathname
    if (pathname.endsWith("/browser-slots")) {
      await route.fulfill({
        json: {
          count: 3,
          data: [
            {
              name: null,
              label: "Docker 默认槽位",
              is_default: true,
              available: false,
              configured: true,
              viewer_available: true,
              occupied_account_id: accountId,
              occupied_account_name: "默认账号",
            },
            {
              name: "pool-1",
              label: "pool-1",
              is_default: false,
              available: true,
              configured: true,
              viewer_available: true,
              occupied_account_id: null,
              occupied_account_name: null,
            },
            {
              name: "pool-2",
              label: "pool-2",
              is_default: false,
              available: false,
              configured: true,
              viewer_available: true,
              occupied_account_id: "418a8148-c8b6-4c6c-b7c4-93580d687300",
              occupied_account_name: "另一个账号",
            },
          ],
        },
      })
      return
    }
    if (pathname.endsWith("/pools")) {
      await route.fulfill({ json: { data: [], count: 0 } })
      return
    }
    if (request.method() === "POST") {
      expect(request.postDataJSON()).toMatchObject({
        name: "自动槽位账号",
        browser_mode: "remote",
        remote_slot: "pool-1",
      })
      createCalls += 1
      await route.fulfill({
        status: 201,
        json: {
          id: "518a8148-c8b6-4c6c-b7c4-93580d687300",
          name: "自动槽位账号",
          browser_mode: "remote",
          remote_slot: "pool-1",
          status: "login_required",
          is_logged_in: false,
          weight: 1,
          priority: 0,
          concurrency_limit: 1,
          daily_task_limit: 100,
          tasks_today: 0,
          min_request_interval_seconds: 1,
          active_leases: 0,
          failure_streak: 0,
          cooldown_until: null,
          last_verified_at: null,
          last_used_at: null,
          last_error: null,
          enabled: true,
          created_at: now,
          updated_at: now,
        },
      })
      return
    }
    await route.fulfill({
      json: {
        count: 1,
        data: [
          {
            id: accountId,
            name: "默认账号",
            browser_mode: "remote",
            remote_slot: null,
            status: "login_required",
            is_logged_in: false,
            weight: 1,
            priority: 0,
            concurrency_limit: 1,
            daily_task_limit: 100,
            tasks_today: 0,
            min_request_interval_seconds: 1,
            active_leases: 0,
            failure_streak: 0,
            cooldown_until: null,
            last_verified_at: null,
            last_used_at: null,
            last_error: null,
            enabled: true,
            created_at: now,
            updated_at: now,
          },
        ],
      },
    })
  })

  await page.goto("/douyin-accounts")

  await expect(page.getByText("远程槽位可用").locator("..")).toContainText(
    "1 / 3",
  )
  await expect(page.getByText("已绑定：默认账号")).toBeVisible()
  await page.getByRole("button", { name: "添加账号" }).click()
  await page.getByLabel("账号别名").fill("自动槽位账号")
  await expect(
    page.getByRole("combobox", { name: "远程浏览器槽位" }),
  ).toContainText("自动分配（pool-1）")
  await page.getByRole("button", { name: "创建账号" }).click()

  await expect.poll(() => createCalls).toBe(1)
})

test("prepares and explicitly confirms a video interaction", async ({
  page,
}) => {
  const taskId = "218a8148-c8b6-4c6c-b7c4-93580d687399"
  const accountId = "318a8148-c8b6-4c6c-b7c4-93580d687399"
  const interactionId = "418a8148-c8b6-4c6c-b7c4-93580d687399"
  const awemeId = "7660000000000000001"
  const now = new Date().toISOString()
  let preflightCalls = 0
  let prepareCalls = 0
  let confirmCalls = 0

  await page.route("**/api/v1/douyin/accounts**", async (route) => {
    await route.fulfill({
      json: {
        count: 1,
        data: [
          {
            id: accountId,
            name: "已登录互动账号",
            browser_mode: "remote",
            remote_slot: "account-1",
            status: "ready",
            is_logged_in: true,
            weight: 1,
            priority: 0,
            concurrency_limit: 1,
            daily_task_limit: 100,
            tasks_today: 1,
            min_request_interval_seconds: 1,
            active_leases: 0,
            failure_streak: 0,
            cooldown_until: null,
            last_verified_at: now,
            last_used_at: null,
            last_error: null,
            enabled: true,
            created_at: now,
            updated_at: now,
          },
        ],
      },
    })
  })
  await page.route("**/api/v1/douyin/interactions**", async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.pathname.endsWith("/quota")) {
      await route.fulfill({
        json: [
          {
            account_id: accountId,
            account_name: "已登录互动账号",
            daily_limit: 50,
            used_today: 1,
            remaining_today: 49,
            min_interval_seconds: 30,
            cooldown_until: null,
            available: true,
          },
        ],
      })
      return
    }
    if (url.pathname.endsWith("/preflight")) {
      expect(request.postDataJSON().content).toBe("人工确认的测试评论")
      preflightCalls += 1
      await route.fulfill({
        json: {
          allowed: true,
          message: "发送前检查通过",
          account_name: "已登录互动账号",
          remaining_daily_quota: 49,
        },
      })
      return
    }
    if (url.pathname.endsWith(`/${interactionId}/confirm`)) {
      confirmCalls += 1
      await route.fulfill({ json: interactionPayload("queued") })
      return
    }
    if (request.method() === "POST") {
      prepareCalls += 1
      await route.fulfill({
        status: 201,
        json: interactionPayload("pending_confirmation"),
      })
      return
    }
    await route.fulfill({ json: { data: [], count: 0 } })
  })
  await page.route(`**/api/v1/douyin/tasks/${taskId}**`, async (route) => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname.endsWith("/works")) {
      await route.fulfill({
        json: {
          count: 1,
          data: [
            {
              aweme: {
                id: "518a8148-c8b6-4c6c-b7c4-93580d687399",
                task_id: taskId,
                aweme_id: awemeId,
                aweme_type: "0",
                title: "可以发起互动的视频",
                description: "",
                create_time: 1_700_000_000,
                creator_hash: "creator-hash",
                sec_uid: "hashed-sec-uid",
                nickname: "测**者",
                liked_count: 10,
                collected_count: 2,
                comment_count: 1,
                share_count: 0,
                aweme_url: `https://www.douyin.com/video/${awemeId}`,
                cover_url: "",
                video_download_url: "",
                music_download_url: "",
                note_download_url: "",
                source_keyword: "互动",
                fetched_at: now,
              },
              persisted_comment_count: 0,
              media: null,
            },
          ],
        },
      })
      return
    }
    if (pathname.endsWith("/media-summary")) {
      await route.fulfill({
        json: {
          total: 0,
          queued: 0,
          downloading: 0,
          downloaded: 0,
          download_failed: 0,
          subtitle_pending: 0,
          subtitle_running: 0,
          subtitle_completed: 0,
          subtitle_failed: 0,
          ...emptyMigrationSummary,
        },
      })
      return
    }
    if (pathname.endsWith("/media") || pathname.endsWith("/shards")) {
      await route.fulfill({ json: { data: [], count: 0 } })
      return
    }
    await route.fulfill({
      json: {
        id: taskId,
        owner_id: "c7e0bb1c-891a-4b4a-8f12-26c1ddd8239d",
        account_id: accountId,
        account_pool_id: null,
        account_strategy: "least_loaded",
        crawl_type: "detail",
        status: "succeeded",
        request: { crawl_type: "detail", video_ids: [awemeId] },
        aweme_count: 1,
        comment_count: 0,
        action_count: 0,
        checkpoint_phase: "completed",
        resume_count: 0,
        can_resume_crawl: false,
        can_resume_media: false,
        error: null,
        has_qrcode: false,
        created_at: now,
        started_at: now,
        finished_at: now,
        last_resumed_at: null,
      },
    })
  })

  await page.goto(`/douyin/${taskId}`)
  await expect(page.getByText("可以发起互动的视频")).toBeVisible()
  await expect(
    page.getByRole("button", { name: "私信", exact: true }),
  ).toBeVisible()
  await page.getByRole("button", { name: "评论", exact: true }).click()
  await expect(page.getByRole("heading", { name: "评论视频" })).toBeVisible()
  await page.getByLabel("发送内容").fill("人工确认的测试评论")
  await page.getByRole("button", { name: "发送前检查" }).click()
  await expect(page.getByText("等待最终确认")).toBeVisible()
  await expect.poll(() => preflightCalls).toBe(1)
  await expect.poll(() => prepareCalls).toBe(1)
  expect(confirmCalls).toBe(0)
  await page.getByRole("button", { name: "确认并发送" }).click()
  await expect.poll(() => confirmCalls).toBe(1)

  function interactionPayload(status: string) {
    return {
      id: interactionId,
      task_id: taskId,
      account_id: accountId,
      account_name: "已登录互动账号",
      aweme_id: awemeId,
      target_comment_id: null,
      interaction_type: "video_comment",
      content_preview: "人工确认的测试评论",
      status,
      failure_code: null,
      error: null,
      attempt_count: 0,
      result_platform_id: null,
      human_confirmed_at: status === "queued" ? now : null,
      started_at: null,
      finished_at: null,
      created_at: now,
      updated_at: now,
      can_confirm: status === "pending_confirmation",
      can_retry: false,
      can_cancel: true,
    }
  }
})

test("shows authenticated browser screenshots in the interaction timeline", async ({
  page,
}) => {
  const interactionId = "618a8148-c8b6-4c6c-b7c4-93580d687399"
  const taskId = "718a8148-c8b6-4c6c-b7c4-93580d687399"
  const eventId = "818a8148-c8b6-4c6c-b7c4-93580d687399"
  const now = new Date().toISOString()
  const image = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
    "base64",
  )
  let screenshotCalls = 0
  const interaction = {
    id: interactionId,
    task_id: taskId,
    account_id: "918a8148-c8b6-4c6c-b7c4-93580d687399",
    account_name: "截图测试账号",
    aweme_id: "7660000000000000002",
    target_comment_id: null,
    interaction_type: "video_comment",
    content_preview: "截图日志测试评论",
    status: "failed",
    failure_code: "comment_not_available",
    error: "没有找到评论输入框",
    attempt_count: 1,
    result_platform_id: null,
    human_confirmed_at: now,
    started_at: now,
    finished_at: now,
    created_at: now,
    updated_at: now,
    can_confirm: false,
    can_retry: true,
    can_cancel: false,
  }

  await page.route("**/api/v1/douyin/interactions**", async (route) => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname.endsWith("/quota")) {
      await route.fulfill({ json: [] })
      return
    }
    if (pathname.endsWith(`/events/${eventId}/screenshot`)) {
      screenshotCalls += 1
      await route.fulfill({
        status: 200,
        contentType: "image/png",
        body: image,
      })
      return
    }
    if (pathname.endsWith(`/${interactionId}`)) {
      await route.fulfill({
        json: {
          ...interaction,
          content: "截图日志测试评论",
          events: [
            {
              id: eventId,
              event: "browser_video_opened",
              from_status: "running",
              to_status: "running",
              detail: "已打开目标视频页面",
              attempt_number: 1,
              has_screenshot: true,
              created_at: now,
            },
          ],
        },
      })
      return
    }
    await route.fulfill({ json: { data: [interaction], count: 1 } })
  })

  await page.goto("/douyin-interactions")
  await page.getByRole("button", { name: "查看详情" }).click()
  await expect(page.getByText("浏览器操作日志")).toBeVisible()
  await expect(page.getByText("1 张截图")).toBeVisible()
  await expect(page.getByText("打开目标视频", { exact: true })).toBeVisible()
  await expect(page.getByAltText("打开目标视频操作截图")).toBeVisible()
  await expect.poll(() => screenshotCalls).toBeGreaterThanOrEqual(1)
  await page.getByRole("button", { name: "查看操作截图大图" }).click()
  await expect(
    page.getByRole("heading", { name: "打开目标视频" }),
  ).toBeVisible()
  await expect(page.getByAltText("打开目标视频操作截图大图")).toBeVisible()
})
