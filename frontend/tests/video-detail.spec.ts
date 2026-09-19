import { expect, type Page, test } from "@playwright/test"

const idleMediaMigration = {
  migration_status: "idle",
  migration_progress: 0,
  migration_attempt_count: 0,
  migration_error: null,
  migration_started_at: null,
  migration_finished_at: null,
}

const awemeId = "7300000000000000009"
const downloadedTaskId = "11111111-1111-4111-8111-111111111111"
const onlineTaskId = "22222222-2222-4222-8222-222222222222"
const title = "带字幕的拆解视频"

/**
 * 同一个作品在两个任务下都采集过：一个已下载（带字幕），
 * 一个只留了采集地址。详情页要能把两份都列出来。
 */
function makeCopy({
  taskId,
  id,
  downloaded,
}: {
  taskId: string
  id: string
  downloaded: boolean
}) {
  const now = new Date().toISOString()
  return {
    aweme: {
      id: `w-${id}`,
      task_id: taskId,
      aweme_id: awemeId,
      aweme_type: "video",
      title,
      description: "",
      create_time: 1735689600,
      creator_hash: `creator-${id}`,
      sec_uid: `sec-${id}`,
      nickname: "字幕达人",
      liked_count: 99,
      collected_count: 12,
      comment_count: 6,
      share_count: 2,
      aweme_url: "",
      cover_url: "",
      video_download_url:
        "https://www.douyin.com/aweme/v1/play/?video_id=temporary",
      music_download_url: "",
      note_download_url: "",
      source_keyword: "拆解",
      source_type: "keyword",
      source_name: "拆解",
      source_label: "拆解",
      fetched_at: now,
    },
    persisted_comment_count: 3,
    media: {
      id: `m-${id}`,
      task_id: taskId,
      aweme_id: awemeId,
      storage_backend: "local",
      status: downloaded ? "downloaded" : "failed",
      progress: downloaded ? 100 : 0,
      attempt_count: 1,
      mime_type: "video/mp4",
      file_size: downloaded ? 2048 : 0,
      sha256: "x",
      error: downloaded ? null : "服务未安装 FFmpeg",
      download_available: downloaded,
      created_at: now,
      updated_at: now,
      completed_at: downloaded ? now : null,
      ...idleMediaMigration,
      subtitle: downloaded
        ? {
            id: "sub-1",
            asset_id: `m-${id}`,
            task_id: taskId,
            aweme_id: awemeId,
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
          }
        : null,
    },
    tags: [{ id: "tag-1", name: "拆解" }],
  }
}

const downloadedCopy = makeCopy({
  taskId: downloadedTaskId,
  id: "1",
  downloaded: true,
})
const onlineCopy = makeCopy({
  taskId: onlineTaskId,
  id: "2",
  downloaded: false,
})

const taskNames: Record<string, string> = {
  [downloadedTaskId]: "拆解任务",
  [onlineTaskId]: "复采任务",
}

type MockWork = typeof downloadedCopy

/**
 * 复刻作品库接口的筛选语义：默认只返回「已下载」的作品，且默认按作品去重。
 *
 * 详情页必须显式传 `download_status=all` + `group_by=task`，否则下载失败的作品
 * 会被过滤掉（线上就是这么报「没有找到这个作品」的），或只看到其中一个副本。
 */
function queryLibrary(works: MockWork[], params: URLSearchParams) {
  const downloadStatus = params.get("download_status") ?? "downloaded"
  const groupBy = params.get("group_by") ?? "work"
  const search = params.get("search")
  let rows = works
  if (search) {
    rows = rows.filter(
      (row) =>
        row.aweme.aweme_id.includes(search) ||
        row.aweme.title.includes(search) ||
        row.aweme.nickname.includes(search),
    )
  }
  if (downloadStatus !== "all") {
    rows = rows.filter((row) => row.media?.status === downloadStatus)
  }
  if (groupBy === "work") {
    const seen = new Set<string>()
    rows = rows.filter((row) => {
      if (seen.has(row.aweme.aweme_id)) return false
      seen.add(row.aweme.aweme_id)
      return true
    })
  }
  return { data: rows, count: rows.length }
}

function makeTask(taskId: string) {
  return {
    id: taskId,
    owner_id: "00000000-0000-4000-8000-000000000001",
    track_id: "33333333-3333-4333-8333-333333333333",
    track_name: "测试赛道",
    track_is_default: true,
    account_id: null,
    account_name: null,
    account_pool_id: null,
    account_pool_name: null,
    account_strategy: "least_loaded",
    crawl_type: "search",
    status: "succeeded",
    request: {},
    display_title: taskNames[taskId],
    display_author: "字幕达人",
    aweme_count: 1,
    comment_count: 3,
    action_count: 0,
    checkpoint_phase: "completed",
    resume_count: 0,
    can_resume_crawl: false,
    can_resume_media: false,
    error: null,
    created_at: new Date().toISOString(),
    started_at: null,
    finished_at: null,
  }
}

/**
 * 详情页只依赖两个接口：作品库（按作品号搜索）与任务列表（补赛道 / 状态）。
 * 播放流的会话接口单独 mock，避免真的去连后端。
 */
async function mockDetailRoutes(
  page: Page,
  works: unknown[] = [downloadedCopy, onlineCopy],
  onLibraryRequest?: (params: URLSearchParams) => void,
) {
  await page.route("**/api/v1/douyin/library/works**", async (route) => {
    const params = new URL(route.request().url()).searchParams
    onLibraryRequest?.(params)
    await route.fulfill({ json: queryLibrary(works as MockWork[], params) })
  })
  await page.route("**/api/v1/douyin/tasks**", async (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    await route.fulfill({
      json: {
        data: [makeTask(downloadedTaskId), makeTask(onlineTaskId)],
        count: 2,
      },
    })
  })
  // 注册顺序即优先级（后注册的先匹配），预览流必须排在 `tasks**` 之后
  // 会话与流地址分开匹配：`preview-session` / `online-preview-session` 都要精确命中
  await page.route(/\/preview-session$/, async (route) => {
    await route.fulfill({ status: 201, json: { message: "ok" } })
  })
  await page.route(/\/online-preview-session$/, async (route) => {
    await route.fulfill({ status: 201, json: { message: "ok" } })
  })
  await page.route(/\/preview\?/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "video/mp4",
      body: "video",
    })
  })
  await page.route(/\/online-preview\?/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "video/mp4",
      body: "video",
    })
  })
}

test("video detail page plays the work and lists every task that collected it", async ({
  page,
}) => {
  const libraryRequests: URLSearchParams[] = []
  await mockDetailRoutes(page, [downloadedCopy, onlineCopy], (params) =>
    libraryRequests.push(params),
  )

  await page.goto(`/douyin-library/video/${awemeId}`)

  // 详情页必须显式放开下载状态、切到任务粒度，否则下载失败的副本会被默认过滤掉
  await expect.poll(() => libraryRequests.length).toBeGreaterThan(0)
  expect(libraryRequests[0].get("search")).toBe(awemeId)
  expect(libraryRequests[0].get("download_status")).toBe("all")
  expect(libraryRequests[0].get("group_by")).toBe("task")

  await expect(page.getByRole("heading", { name: title })).toBeVisible()
  await expect(page.getByText("字幕达人").first()).toBeVisible()
  await expect(page.getByText("#拆解")).toBeVisible()

  // 有已下载的副本时优先播本地文件
  await expect(page.locator("video")).toHaveCount(1)
  await expect(page.getByText("播放已下载的文件（按需读取片段）")).toBeVisible()

  // 互动数据与处理状态
  await expect(page.getByText("互动数据")).toBeVisible()
  await expect(page.getByText("处理状态")).toBeVisible()
  // 同一份状态在「处理状态」卡片与「采集来源」表格里都会出现
  await expect(page.getByText("本地已存").first()).toBeVisible()
  await expect(page.getByText("字幕完成").first()).toBeVisible()

  // 字幕内容直接开在页面上
  await expect(page.getByText("大家好这里是完整字幕内容")).toBeVisible()

  // 采集来源：两个任务的副本都在
  await expect(page.getByText("采集来源（2 个任务）")).toBeVisible()
  await expect(
    page.getByRole("link", { name: `进入任务 ${downloadedTaskId}` }),
  ).toBeVisible()
  await expect(
    page.getByRole("link", { name: `进入任务 ${onlineTaskId}` }),
  ).toBeVisible()
  await expect(page.getByText("测试赛道").first()).toBeVisible()
  await expect(page.getByText("下载失败").first()).toBeVisible()
})

test("video detail falls back to the captured address when nothing is downloaded", async ({
  page,
}) => {
  await mockDetailRoutes(page, [onlineCopy])
  // 覆盖流地址：统计真实发起的取流次数（正则后注册者优先）
  let onlineStreamCalls = 0
  await page.route(/\/online-preview\?/, async (route) => {
    onlineStreamCalls += 1
    await route.fulfill({
      status: 200,
      contentType: "video/mp4",
      body: "video",
    })
  })

  await page.goto(`/douyin-library/video/${awemeId}`)

  await expect(page.getByRole("heading", { name: title })).toBeVisible()
  await expect(page.locator("video")).toHaveCount(1)
  await expect(page.getByText("播放采集地址（服务端代理转发）")).toBeVisible()
  await expect.poll(() => onlineStreamCalls).toBeGreaterThan(0)
})

test("unknown work shows an empty state instead of a broken page", async ({
  page,
}) => {
  await mockDetailRoutes(page, [])

  await page.goto(`/douyin-library/video/${awemeId}`)

  await expect(page.getByText("没有找到这个作品")).toBeVisible()
  await page.getByRole("link", { name: "返回视频资源库" }).click()
  await expect(page).toHaveURL(/\/douyin-library(\?|$)/)
})

test("video list titles open the detail page", async ({ page }) => {
  await page.route("**/api/v1/douyin/tracks**", async (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    await route.fulfill({ json: { data: [], count: 0 } })
  })
  await mockDetailRoutes(page)
  await page.route("**/api/v1/douyin/library/creators**", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })
  await page.route("**/api/v1/douyin/tags/**", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })

  await page.goto("/douyin-library")
  await page.getByLabel(`查看视频详情：${title}`).first().click()

  await expect(page).toHaveURL(new RegExp(`/douyin-library/video/${awemeId}$`))
  await expect(page.getByRole("heading", { name: title })).toBeVisible()
  await expect(page.getByText("采集来源（2 个任务）")).toBeVisible()
})
