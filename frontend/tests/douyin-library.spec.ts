import { expect, test } from "@playwright/test"

const idleMediaMigration = {
  migration_status: "idle",
  migration_progress: 0,
  migration_attempt_count: 0,
  migration_error: null,
  migration_started_at: null,
  migration_finished_at: null,
}

test("video library lists undownloaded works with three switchable layouts", async ({
  page,
}) => {
  const libTaskId = "7a6b5c4d-3e2f-4a1b-9c8d-7e6f5a4b3c2d"
  const now = new Date().toISOString()
  const longTitle =
    "这是一条很长很长的视频标题用来验证表格视图里长标题截断之后悬浮展示完整内容的效果长度一定要足够长"
  const awemeBase = {
    task_id: libTaskId,
    aweme_type: "video",
    description: "",
    create_time: 1735689600,
    creator_hash: "creator-1",
    sec_uid: "sec-1",
    aweme_url: "",
    cover_url: "",
    video_download_url: "",
    music_download_url: "",
    note_download_url: "",
    fetched_at: now,
  }
  const downloadedWork = {
    aweme: {
      ...awemeBase,
      id: "w-1",
      aweme_id: "7300000000000000001",
      title: "已下载的露营视频",
      nickname: "露营达人",
      liked_count: 1200,
      collected_count: 300,
      comment_count: 88,
      share_count: 12,
      source_keyword: "露营",
    },
    persisted_comment_count: 66,
    media: {
      id: "m-1",
      task_id: libTaskId,
      aweme_id: "7300000000000000001",
      storage_backend: "local",
      status: "downloaded",
      progress: 100,
      attempt_count: 1,
      mime_type: "video/mp4",
      file_size: 2048,
      sha256: "x",
      error: null,
      download_available: true,
      created_at: now,
      updated_at: now,
      completed_at: now,
      ...idleMediaMigration,
      subtitle: null,
    },
    tags: [],
  }
  const pendingWork = {
    aweme: {
      ...awemeBase,
      id: "w-2",
      aweme_id: "7300000000000000002",
      title: longTitle,
      nickname: "户外玩家",
      liked_count: 34,
      collected_count: 5,
      comment_count: 2,
      share_count: 0,
      source_keyword: "户外",
      video_download_url:
        "https://www.douyin.com/aweme/v1/play/?video_id=temporary",
    },
    persisted_comment_count: 0,
    media: null,
    tags: [],
  }
  let requestedDownloadStatus = "unset"
  await page.route("**/api/v1/douyin/tracks**", async (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    await route.fulfill({ json: { data: [], count: 0 } })
  })
  await page.route("**/api/v1/douyin/library/works**", async (route) => {
    requestedDownloadStatus =
      new URL(route.request().url()).searchParams.get("download_status") ?? ""
    await route.fulfill({
      json: { data: [downloadedWork, pendingWork], count: 2 },
    })
  })
  await page.route("**/api/v1/douyin/library/creators**", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })
  await page.route("**/api/v1/douyin/tags/**", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })
  await page.route("**/api/v1/douyin/tasks**", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })

  await page.goto("/douyin-library")
  await expect.poll(() => requestedDownloadStatus).toBe("all")
  await expect(page.getByText("已下载的露营视频")).toBeVisible()
  await expect(page.getByText("未下载", { exact: true }).first()).toBeVisible()
  await expect(page.getByText("本地", { exact: true }).first()).toBeVisible()

  await page.getByLabel("视频尚未下载").click()
  const unavailableDialog = page.getByRole("dialog")
  await expect(unavailableDialog.getByText("视频尚未下载")).toBeVisible()
  await expect(
    unavailableDialog.getByText("临时地址不是稳定播放流", { exact: false }),
  ).toBeVisible()
  await expect(unavailableDialog.locator("video")).toHaveCount(0)
  await expect(
    unavailableDialog.getByRole("link", { name: "去创建下载任务" }),
  ).toHaveAttribute("href", `/douyin/${libTaskId}`)
  await page.keyboard.press("Escape")

  await page.getByLabel("按下载状态筛选").click()
  await page.getByRole("option", { name: "已下载" }).click()
  await expect.poll(() => requestedDownloadStatus).toBe("downloaded")
  await page.getByLabel("按下载状态筛选").click()
  await page.getByRole("option", { name: "全部状态" }).click()
  await expect.poll(() => requestedDownloadStatus).toBe("all")

  await page.getByRole("button", { name: "横条" }).click()
  await expect(page.getByRole("heading", { name: longTitle })).toBeVisible()

  await page.getByRole("button", { name: "表格", exact: true }).click()
  const titleText = page.locator("td").getByText(longTitle)
  await titleText.hover()
  await expect(page.getByRole("tooltip")).toContainText("很长很长的视频标题")

  await page.reload()
  await expect(page.getByRole("button", { name: "表格" })).toHaveAttribute(
    "aria-pressed",
    "true",
  )
  await expect(
    page.getByRole("columnheader", { name: "已存评论" }),
  ).toBeVisible()
})

function makeSubtitleWork() {
  const libTaskId = "7a6b5c4d-3e2f-4a1b-9c8d-7e6f5a4b3c2d"
  const now = new Date().toISOString()
  return {
    aweme: {
      id: "w-sub-1",
      task_id: libTaskId,
      aweme_id: "7300000000000000009",
      aweme_type: "video",
      title: "带字幕的拆解视频",
      description: "",
      create_time: 1735689600,
      creator_hash: "creator-sub",
      sec_uid: "sec-sub",
      nickname: "字幕达人",
      liked_count: 99,
      collected_count: 12,
      comment_count: 6,
      share_count: 2,
      aweme_url: "",
      cover_url: "",
      video_download_url: "",
      music_download_url: "",
      note_download_url: "",
      source_keyword: "拆解",
      fetched_at: now,
    },
    persisted_comment_count: 3,
    media: {
      id: "m-sub-1",
      task_id: libTaskId,
      aweme_id: "7300000000000000009",
      storage_backend: "local",
      status: "downloaded",
      progress: 100,
      attempt_count: 1,
      mime_type: "video/mp4",
      file_size: 2048,
      sha256: "x",
      error: null,
      download_available: true,
      created_at: now,
      updated_at: now,
      completed_at: now,
      ...idleMediaMigration,
      subtitle: {
        id: "sub-1",
        asset_id: "m-sub-1",
        task_id: libTaskId,
        aweme_id: "7300000000000000009",
        status: "completed",
        progress: 100,
        attempt_count: 1,
        requested_backend: "whisper",
        actual_backend: "whisper",
        model: "small",
        language: "zh",
        duration_seconds: 12,
        full_text: "大家好这里是完整字幕内容",
        segments: [{ start: 0, end: 1.5, text: "大家好" }],
        error: null,
        created_at: now,
        started_at: now,
        finished_at: now,
      },
    },
    tags: [],
  }
}

async function mockLibraryRoutes(
  page: import("@playwright/test").Page,
  works: unknown[],
) {
  await page.route("**/api/v1/douyin/tracks**", async (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    await route.fulfill({ json: { data: [], count: 0 } })
  })
  await page.route("**/api/v1/douyin/library/works**", async (route) => {
    await route.fulfill({ json: { data: works, count: works.length } })
  })
  await page.route("**/api/v1/douyin/library/creators**", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })
  await page.route("**/api/v1/douyin/tags/**", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })
  await page.route("**/api/v1/douyin/tasks**", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })
}

test("subtitle dialog and preview tabs expose subtitle content", async ({
  page,
}) => {
  await mockLibraryRoutes(page, [makeSubtitleWork()])
  await page.route("**/preview-session", async (route) => {
    await route.fulfill({ status: 201, json: {} })
  })
  await page.route("**/preview?**", async (route) => {
    await route.fulfill({ status: 200, contentType: "video/mp4", body: "" })
  })

  await page.goto("/douyin-library")
  await page.getByLabel("查看字幕").click()
  const dialog = page.getByRole("dialog")
  await expect(dialog.getByText("大家好这里是完整字幕内容")).toBeVisible()
  await expect(dialog.getByText("字幕完成")).toBeVisible()
  await expect(dialog.getByText("大家好", { exact: true })).toBeVisible()
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"])
  await dialog.getByRole("button", { name: "复制字幕" }).click()
  await expect(page.getByText("字幕内容已复制")).toBeVisible()
  await page.keyboard.press("Escape")

  await page.getByLabel("预览视频").click()
  await expect(page.getByRole("heading", { name: "视频预览" })).toBeVisible()
  await page.getByRole("tab", { name: "字幕信息" }).click()
  await expect(
    page.getByRole("dialog").getByText("大家好这里是完整字幕内容"),
  ).toBeVisible()
  await page.getByRole("tab", { name: "视频信息" }).click()
  await expect(
    page.getByRole("dialog").getByText("带字幕的拆解视频"),
  ).toBeVisible()
  await expect(page.getByRole("dialog").getByText("字幕达人")).toBeVisible()
})

test("selects library videos and creates comment tasks with source settings", async ({
  page,
}) => {
  const work = makeSubtitleWork()
  const taskId = work.aweme.task_id
  const accountId = "5a4b3c2d-1e0f-4a9b-8c7d-6e5f4a3b2c1d"
  const task = {
    id: taskId,
    name: "字幕来源任务",
    platform: "douyin",
    status: "completed",
    account_id: accountId,
    account_name: "评论账号",
    account_pool_id: null,
    account_pool_name: null,
    track_id: null,
    track_name: null,
    track_is_default: false,
    aweme_count: 1,
    comment_count: 3,
    created_at: new Date().toISOString(),
    started_at: null,
    finished_at: null,
    error: null,
    checkpoint: null,
    request: {
      crawl_type: "search",
      keywords: ["拆解"],
      max_notes_count: 30,
      max_comments_per_aweme: 24,
      fetch_comments: true,
      fetch_sub_comments: true,
      request_delay_level: "ultra_steady",
    },
  }
  await mockLibraryRoutes(page, [work])
  await page.route("**/api/v1/douyin/tasks**", async (route) => {
    await route.fulfill({ json: { data: [task], count: 1 } })
  })
  let recrawlBody: Record<string, unknown> | undefined
  await page.route(
    "**/api/v1/douyin/tasks/**/awemes/**/comments/recrawl",
    async (route) => {
      recrawlBody = route.request().postDataJSON()
      await route.fulfill({ json: task })
    },
  )

  await page.goto("/douyin-library")
  await page.getByLabel("选择视频 带字幕的拆解视频").click()
  await expect(page.getByText("已选择 1 个视频")).toBeVisible()
  await page.getByRole("button", { name: "批量创建评论任务" }).click()

  await expect
    .poll(() => recrawlBody)
    .toMatchObject({
      account_id: accountId,
      fetch_sub_comments: true,
      max_comments_per_aweme: 24,
      request_delay_level: "ultra_steady",
    })
  await expect(page.getByText("已为 1 个视频创建评论采集任务")).toBeVisible()
  await expect(page.getByText("选择本页视频", { exact: true })).toBeVisible()
})

test("exports subtitles across all pages for the current filters", async ({
  page,
}) => {
  await mockLibraryRoutes(page, [makeSubtitleWork()])
  let exportLimit = ""
  let exportSubtitleStatus = "unset"
  await page.route("**/api/v1/douyin/library/works**", async (route) => {
    const params = new URL(route.request().url()).searchParams
    exportLimit = params.get("limit") ?? ""
    exportSubtitleStatus = params.get("subtitle_status") ?? ""
    await route.fulfill({
      json: {
        data: params.get("skip") === "0" ? [makeSubtitleWork()] : [],
        count: 156,
      },
    })
  })

  await page.goto("/douyin-library")
  await page.getByRole("combobox").filter({ hasText: "全部字幕" }).click()
  await page.getByRole("option", { name: "字幕完成" }).click()
  await expect.poll(() => exportSubtitleStatus).toBe("completed")

  const downloadPromise = page.waitForEvent("download")
  await page.getByRole("button", { name: "导出字幕" }).click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toMatch(/douyin-subtitles-.*\.txt/)
  expect(exportLimit).toBe("100")
  await expect(page.getByText(/已按筛选条件导出 1 条字幕/)).toBeVisible()
})
