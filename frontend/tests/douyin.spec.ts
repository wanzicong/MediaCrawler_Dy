import { expect, test } from "@playwright/test"

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

test("shows media progress, persisted subtitle and retranslation action", async ({
  page,
}) => {
  const taskId = "48a8148c-c8b6-4c6c-b7c4-93580d687399"
  const assetId = "58a8148c-c8b6-4c6c-b7c4-93580d687399"
  const now = new Date().toISOString()
  let retranslateCalls = 0

  await page.route(`**/api/v1/douyin/tasks/${taskId}**`, async (route) => {
    const url = new URL(route.request().url())
    const pathname = url.pathname
    if (pathname.endsWith(`/media/${assetId}/retranslate`)) {
      retranslateCalls += 1
      await route.fulfill({ json: { message: "Subtitle translation queued" } })
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
          subtitle_completed: 1,
          subtitle_failed: 0,
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

  await expect(page.getByText("这是远程 API 返回的字幕").first()).toBeVisible()
  await expect(page.getByText("字幕完成", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: "重新翻译字幕" }).click()
  await expect.poll(() => retranslateCalls).toBe(1)
})
