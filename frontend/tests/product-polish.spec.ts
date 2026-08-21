import { expect, type Page, test } from "@playwright/test"

const ownerId = "c7e0bb1c-891a-4b4a-8f12-26c1ddd8239d"

const emptyMediaSummary = {
  total: 0,
  queued: 0,
  downloading: 0,
  downloaded: 0,
  download_failed: 0,
  subtitle_pending: 0,
  subtitle_running: 0,
  subtitle_completed: 0,
  subtitle_failed: 0,
  local_downloaded: 0,
  minio_downloaded: 0,
  migration_queued: 0,
  migration_running: 0,
  migration_cleanup_pending: 0,
  migration_completed: 0,
  migration_failed: 0,
}

function taskFixture({
  id,
  now,
  displayTitle,
  displayAuthor,
  awemeId,
}: {
  id: string
  now: string
  displayTitle: string
  displayAuthor: string
  awemeId: string
}) {
  return {
    id,
    owner_id: ownerId,
    account_id: null,
    account_pool_id: null,
    account_strategy: "least_loaded",
    crawl_type: "detail",
    status: "succeeded",
    request: {
      crawl_type: "detail",
      video_ids: [awemeId],
      fetch_comments: false,
      download_media: false,
      translate_subtitles: false,
      max_awemes: 1,
    },
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
    display_title: displayTitle,
    display_author: displayAuthor,
    display_aweme_id: awemeId,
  }
}

async function mockCreateTaskDependencies(page: Page) {
  await page.route("**/api/v1/douyin/accounts?**", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })
  await page.route("**/api/v1/douyin/accounts/pools**", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })
}

async function mockTaskDetailDependencies({
  page,
  taskId,
  task,
  mediaSummary = emptyMediaSummary,
  mediaSummaryStatus = 200,
}: {
  page: Page
  taskId: string
  task: Record<string, unknown>
  mediaSummary?: typeof emptyMediaSummary
  mediaSummaryStatus?: number
}) {
  await page.route(`**/api/v1/douyin/tasks/${taskId}**`, async (route) => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname.endsWith("/media-summary")) {
      await route.fulfill({
        status: mediaSummaryStatus,
        json:
          mediaSummaryStatus === 200
            ? mediaSummary
            : { detail: "媒体摘要服务暂时不可用" },
      })
      return
    }
    if (pathname.endsWith("/works")) {
      await route.fulfill({ json: { data: [], count: 0 } })
      return
    }
    if (pathname.endsWith("/shards")) {
      await route.fulfill({ json: { data: [], count: 0 } })
      return
    }
    await route.fulfill({ json: task })
  })
  await page.route("**/api/v1/douyin/tags?**", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })
  await page.route("**/api/v1/douyin/interactions?**", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })
}

test("uses content identity and short references for duplicate detail tasks", async ({
  page,
}) => {
  const now = new Date().toISOString()
  const awemeId = "7671284134611116154"
  const firstTask = taskFixture({
    id: "11111111-1111-4111-8111-aaaaaaaa0001",
    now,
    displayTitle: "露营装备清单",
    displayAuthor: "帐篷研究所",
    awemeId,
  })
  const secondTask = taskFixture({
    id: "22222222-2222-4222-8222-bbbbbbbb0002",
    now,
    displayTitle: "露营装备清单",
    displayAuthor: "帐篷研究所",
    awemeId,
  })

  await mockCreateTaskDependencies(page)
  await page.route("**/api/v1/douyin/tasks?**", async (route) => {
    await route.fulfill({
      json: { data: [firstTask, secondTask], count: 2 },
    })
  })

  await page.goto("/douyin")

  await expect(
    page.getByRole("heading", { name: "抖音任务管理" }),
  ).toBeVisible()
  const table = page.getByRole("table")
  const firstRow = table.getByRole("row").filter({ hasText: "任务 #AA0001" })
  const secondRow = table.getByRole("row").filter({ hasText: "任务 #BB0002" })
  await expect(firstRow).toContainText("露营装备清单")
  await expect(firstRow).toContainText("@帐篷研究所")
  await expect(secondRow).toContainText("露营装备清单")
  await expect(secondRow).toContainText("@帐篷研究所")
  await expect(table).not.toContainText(awemeId)
})

test("renders disabled task stages without completed progress semantics", async ({
  page,
}) => {
  const taskId = "33333333-3333-4333-8333-cccccccc0003"
  const now = new Date().toISOString()
  const task = taskFixture({
    id: taskId,
    now,
    displayTitle: "城市夜景拍摄攻略",
    displayAuthor: "光影观察员",
    awemeId: "7671284134611116155",
  })

  await page.route(`**/api/v1/douyin/tasks/${taskId}**`, async (route) => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname.endsWith("/media-summary")) {
      await route.fulfill({ json: emptyMediaSummary })
      return
    }
    if (pathname.endsWith("/works")) {
      await route.fulfill({ json: { data: [], count: 0 } })
      return
    }
    if (pathname.endsWith("/shards")) {
      await route.fulfill({ json: { data: [], count: 0 } })
      return
    }
    await route.fulfill({ json: task })
  })
  await page.route("**/api/v1/douyin/tags?**", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })
  await page.route("**/api/v1/douyin/interactions?**", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })

  await page.goto(`/douyin/${taskId}`)

  await expect(
    page.getByRole("heading", { name: "城市夜景拍摄攻略" }),
  ).toBeVisible()
  await expect(page.getByText(/@光影观察员/)).toBeVisible()
  await expect(page.getByText("任务 #CC0003", { exact: false })).toBeVisible()
  await expect(page.getByText(taskId, { exact: true })).not.toBeVisible()

  const progress = page.getByTestId("task-execution-progress")
  await expect(progress).toContainText("1 个完成 · 3 个未启用")
  await expect(progress).toContainText("已完成 1 / 1")
  await expect(progress).not.toContainText("阶段 4 / 4")

  for (const stageName of ["comments", "download", "subtitle"]) {
    const stage = page.locator(`[data-stage="${stageName}"]`)
    await expect(stage).toContainText("未启用")
    await expect(stage).not.toContainText("100%")
    await expect(stage.locator('[data-progress-state="skipped"]')).toHaveCount(
      1,
    )
    await expect(stage.getByRole("progressbar")).toHaveCount(0)
  }

  await page.getByText("任务配置", { exact: true }).click()
  await expect(page.getByText(taskId, { exact: true })).toBeVisible()
})

test("settles enabled media stages when a successful task has no processable content", async ({
  page,
}) => {
  const taskId = "88888888-8888-4888-8888-bbbbbbbb0008"
  const now = new Date().toISOString()
  const baseTask = taskFixture({
    id: taskId,
    now,
    displayTitle: "空结果采集任务",
    displayAuthor: "内容观察员",
    awemeId: "7671284134611116158",
  })
  const task = {
    ...baseTask,
    request: {
      ...baseTask.request,
      fetch_comments: true,
      download_media: true,
      translate_subtitles: true,
    },
  }
  await mockTaskDetailDependencies({ page, taskId, task })

  await page.goto(`/douyin/${taskId}`)

  const progress = page.getByTestId("task-execution-progress")
  await expect(progress).toContainText("4 个完成")
  await expect(progress).toContainText("已完成 4 / 4")
  for (const stageName of ["download", "subtitle"]) {
    const stage = page.locator(`[data-stage="${stageName}"]`)
    await expect(stage).toContainText("任务已结束，无可处理内容")
    await expect(stage).toContainText("100%")
    await expect(stage).not.toContainText("待处理")
  }
})

test("shows an explicit media progress error when the summary request fails", async ({
  page,
}) => {
  const taskId = "99999999-9999-4999-8999-cccccccc0009"
  const now = new Date().toISOString()
  const baseTask = taskFixture({
    id: taskId,
    now,
    displayTitle: "媒体摘要异常任务",
    displayAuthor: "内容观察员",
    awemeId: "7671284134611116159",
  })
  const task = {
    ...baseTask,
    request: {
      ...baseTask.request,
      fetch_comments: true,
      download_media: true,
      translate_subtitles: true,
    },
  }
  await mockTaskDetailDependencies({
    page,
    taskId,
    task,
    mediaSummaryStatus: 500,
  })

  await page.goto(`/douyin/${taskId}`)

  const progress = page.getByTestId("task-execution-progress")
  await expect(progress).toContainText("2 个异常")
  for (const stageName of ["download", "subtitle"]) {
    const stage = page.locator(`[data-stage="${stageName}"]`)
    await expect(stage).toContainText("媒体进度读取失败，系统将自动重试")
    await expect(stage).not.toContainText("待处理")
  }
})

test("translates task configuration and shard states into business Chinese", async ({
  page,
}) => {
  const taskId = "66666666-6666-4666-8666-ffffffff0006"
  const now = new Date().toISOString()
  const task = {
    ...taskFixture({
      id: taskId,
      now,
      displayTitle: "露营选题采集",
      displayAuthor: "户外观察员",
      awemeId: "7671284134611116156",
    }),
    crawl_type: "search",
    request: {
      crawl_type: "search",
      login_type: "qrcode",
      browser_mode: "local",
      keywords: ["露营"],
      max_awemes: 1,
      fetch_comments: true,
      download_media: true,
      translate_subtitles: true,
      request_delay_level: "steady",
      publish_time: 7,
      media_processing_mode: "immediate",
      media_storage: "minio",
      transcription_language: "auto",
      account_strategy: "least_loaded",
      creator_ids: ["MS4wLjABAAAAinternal-author-id"],
    },
    creator_names: ["露营达人"],
  }

  await page.route(`**/api/v1/douyin/tasks/${taskId}**`, async (route) => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname.endsWith("/media-summary")) {
      await route.fulfill({
        json: {
          ...emptyMediaSummary,
          total: 1,
          downloaded: 1,
          minio_downloaded: 1,
          subtitle_completed: 1,
        },
      })
      return
    }
    if (pathname.endsWith("/works")) {
      await route.fulfill({ json: { data: [], count: 0 } })
      return
    }
    if (pathname.endsWith("/shards")) {
      await route.fulfill({
        json: {
          data: [
            {
              id: "77777777-7777-4777-8777-aaaaaaaa0007",
              task_id: taskId,
              account_id: null,
              account_name: "内容账号甲",
              shard_index: 0,
              status: "queued",
              request: {},
              aweme_count: 0,
              comment_count: 0,
              error: null,
              started_at: null,
              finished_at: null,
              created_at: now,
            },
          ],
          count: 1,
        },
      })
      return
    }
    await route.fulfill({ json: task })
  })
  await page.route("**/api/v1/douyin/tags?**", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })
  await page.route("**/api/v1/douyin/interactions?**", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })

  await page.goto(`/douyin/${taskId}`)

  await expect(page.getByText("@户外观察员", { exact: true })).toHaveCount(0)

  const shardHeading = page.getByText("内容账号甲", { exact: true })
  await expect(shardHeading.locator("..")).toContainText("等待调度")
  await expect(shardHeading.locator("..")).not.toContainText("queued")

  await page.getByText("任务配置", { exact: true }).click()
  const config = page.locator("details")
  for (const label of [
    "关键词搜索",
    "扫码登录",
    "本机浏览器",
    "稳 · 随机 3–6 秒",
    "一周内",
    "逐条异步处理",
    "云端存储",
    "自动识别",
    "最少负载",
  ]) {
    await expect(config.getByText(label, { exact: true })).toBeVisible()
  }
  for (const internalValue of [
    "search",
    "qrcode",
    "local",
    "steady",
    "immediate",
    "minio",
    "auto",
    "least_loaded",
    "MS4wLjABAAAAinternal-author-id",
  ]) {
    await expect(config.getByText(internalValue, { exact: true })).toHaveCount(
      0,
    )
  }
  await expect(config.getByText("露营达人", { exact: true })).toBeVisible()
})

test("shows current account guidance but hides stale ready and busy errors", async ({
  page,
}) => {
  const now = new Date().toISOString()
  const accountFixture = ({
    id,
    name,
    status,
    lastError,
  }: {
    id: string
    name: string
    status: "login_required" | "verifying" | "ready" | "busy" | "unhealthy"
    lastError: string
  }) => ({
    id,
    name,
    browser_mode: "remote",
    remote_slot: null,
    status,
    is_logged_in: ["ready", "busy"].includes(status),
    weight: 1,
    priority: 0,
    concurrency_limit: 1,
    daily_task_limit: 100,
    tasks_today: 0,
    min_request_interval_seconds: 1,
    active_leases: 0,
    failure_streak: ["ready", "busy"].includes(status) ? 0 : 1,
    cooldown_until: null,
    last_verified_at: now,
    last_used_at: null,
    last_error: lastError,
    enabled: true,
    created_at: now,
    updated_at: now,
  })

  await page.route("**/api/v1/douyin/accounts**", async (route) => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname.endsWith("/browser-slots")) {
      await route.fulfill({ json: { data: [], count: 0 } })
      return
    }
    if (pathname.endsWith("/pools")) {
      await route.fulfill({ json: { data: [], count: 0 } })
      return
    }
    await route.fulfill({
      json: {
        data: [
          accountFixture({
            id: "44444444-4444-4444-8444-dddddddd0004",
            name: "稳定账号",
            status: "ready",
            lastError: "历史连接失败不应继续展示",
          }),
          accountFixture({
            id: "55555555-5555-4555-8555-eeeeeeee0005",
            name: "异常账号",
            status: "unhealthy",
            lastError: "当前浏览器连接失败",
          }),
          accountFixture({
            id: "66666666-6666-4666-8666-ffffffff0006",
            name: "待登录账号",
            status: "login_required",
            lastError: "请先完成扫码登录",
          }),
          accountFixture({
            id: "77777777-7777-4777-8777-aaaaaaaa0007",
            name: "验证中账号",
            status: "verifying",
            lastError: "浏览器已打开，请在页面内确认登录",
          }),
          accountFixture({
            id: "88888888-8888-4888-8888-bbbbbbbb0008",
            name: "执行中账号",
            status: "busy",
            lastError: "旧的失败信息不应显示",
          }),
        ],
        count: 2,
      },
    })
  })

  await page.goto("/douyin-accounts")

  const readyRow = page.getByRole("row").filter({ hasText: "稳定账号" })
  const unhealthyRow = page.getByRole("row").filter({ hasText: "异常账号" })
  const loginRequiredRow = page
    .getByRole("row")
    .filter({ hasText: "待登录账号" })
  const verifyingRow = page.getByRole("row").filter({ hasText: "验证中账号" })
  const busyRow = page.getByRole("row").filter({ hasText: "执行中账号" })
  await expect(readyRow).toContainText("可用")
  await expect(readyRow).not.toContainText("历史连接失败不应继续展示")
  await expect(unhealthyRow).toContainText("异常")
  await expect(unhealthyRow).toContainText("当前浏览器连接失败")
  await expect(loginRequiredRow).toContainText("请先完成扫码登录")
  await expect(verifyingRow).toContainText("浏览器已打开，请在页面内确认登录")
  await expect(busyRow).not.toContainText("旧的失败信息不应显示")
})

test("shows explicit retry states instead of empty task and track data", async ({
  page,
}) => {
  let taskRequests = 0
  await page.route("**/api/v1/douyin/tasks?**", async (route) => {
    taskRequests += 1
    await route.fulfill({ status: 500, json: { detail: "服务异常" } })
  })
  await page.route("**/api/v1/douyin/accounts**", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })

  await page.goto("/douyin")
  const taskError = page.getByRole("alert").filter({
    hasText: "任务列表读取失败",
  })
  await expect(taskError).toBeVisible()
  await expect(page.getByText("还没有抖音任务")).toHaveCount(0)
  await expect(page.getByText("—", { exact: true })).toHaveCount(4)
  await taskError.getByRole("button", { name: "重试" }).click()
  await expect.poll(() => taskRequests).toBeGreaterThan(1)

  await page.route("**/api/v1/douyin/tracks**", async (route) => {
    await route.fulfill({ status: 500, json: { detail: "服务异常" } })
  })
  await page.goto("/douyin-tracks")
  await expect(
    page.getByRole("alert").filter({ hasText: "赛道列表读取失败" }),
  ).toBeVisible()
  await expect(page.getByText("还没有运营赛道")).toHaveCount(0)
  await expect(page.getByText("—", { exact: true })).toHaveCount(4)
})

test("shows independent account, pool, and browser slot query failures", async ({
  page,
}) => {
  await page.route("**/api/v1/douyin/accounts**", async (route) => {
    await route.fulfill({ status: 500, json: { detail: "服务异常" } })
  })

  await page.goto("/douyin-accounts")
  for (const message of ["账号列表读取失败", "浏览器槽位读取失败"]) {
    await expect(
      page.getByRole("alert").filter({ hasText: message }),
    ).toBeVisible()
  }
  await page.getByRole("tab", { name: /账号池管理/ }).click()
  await expect(
    page.getByRole("alert").filter({ hasText: "账号池列表读取失败" }),
  ).toBeVisible()
  await expect(page.getByText("—", { exact: true })).toHaveCount(4)
  await expect(page.getByText("尚未添加账号", { exact: false })).toHaveCount(0)

  await page.goto("/douyin-browsers")
  await expect(
    page.getByRole("alert").filter({ hasText: "浏览器槽位读取失败" }),
  ).toBeVisible()
  await expect(page.getByText("—", { exact: true })).toHaveCount(4)
})

test("distinguishes unavailable tasks from retryable detail failures", async ({
  page,
}) => {
  const taskId = "99999999-9999-4999-8999-dddddddd0010"
  let status = 404
  await page.route(`**/api/v1/douyin/tasks/${taskId}`, async (route) => {
    await route.fulfill({ status, json: { detail: "读取失败" } })
  })

  await page.goto(`/douyin/${taskId}`)
  await expect(page.getByText("任务不可用", { exact: true })).toBeVisible()
  await expect(page.getByRole("button", { name: "重试" })).toHaveCount(0)

  status = 500
  await page.reload()
  await expect(
    page.getByText("任务详情读取失败", { exact: true }),
  ).toBeVisible()
  await expect(page.getByRole("button", { name: "重试" })).toBeVisible()
})

test("keeps the account login guidance returned by the service", async ({
  page,
}) => {
  const now = new Date().toISOString()
  const account = {
    id: "aaaaaaaa-aaaa-4aaa-8aaa-eeeeeeee0011",
    name: "需要导航提示的账号",
    browser_mode: "local",
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
  }
  await page.route("**/api/v1/douyin/accounts**", async (route) => {
    const pathname = new URL(route.request().url()).pathname
    if (route.request().method() === "POST" && pathname.endsWith("/login")) {
      await route.fulfill({
        status: 202,
        json: {
          account: { ...account, status: "verifying" },
          status: "verifying",
          browser_mode: "local",
          viewer_url: null,
          expires_at: now,
          message: "请在已经打开的抖音页面完成登录",
        },
      })
      return
    }
    if (pathname.endsWith("/browser-slots") || pathname.endsWith("/pools")) {
      await route.fulfill({ json: { data: [], count: 0 } })
      return
    }
    await route.fulfill({ json: { data: [account], count: 1 } })
  })

  await page.goto("/douyin-accounts")
  await page
    .getByRole("row")
    .filter({ hasText: account.name })
    .getByRole("button", { name: "登录" })
    .click()
  await expect(page.getByText(/请在已经打开的抖音页面完成登录/)).toBeVisible()
  await expect(page.getByText(/完成登录后回到本页验证/)).toBeVisible()
})
