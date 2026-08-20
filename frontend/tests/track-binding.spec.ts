import { expect, type Page, test } from "@playwright/test"

const ownerId = "c7e0bb1c-891a-4b4a-8f12-26c1ddd8239d"
const defaultTrackId = "11111111-1111-4111-8111-111111111111"
const growthTrackId = "22222222-2222-4222-8222-222222222222"
const taskId = "33333333-3333-4333-8333-333333333333"
const keywordId = "44444444-4444-4444-8444-444444444444"

const now = new Date().toISOString()
const tracks = [
  trackFixture(defaultTrackId, "默认赛道", true),
  trackFixture(growthTrackId, "私域增长", false),
]

function trackFixture(id: string, name: string, isDefault: boolean) {
  return {
    id,
    name,
    description: isDefault ? "承接未明确归属的数据" : "验证赛道归属",
    enabled: true,
    is_default: isDefault,
    keyword_count: 1,
    enabled_keyword_count: 1,
    task_count: 1,
    active_task_count: 0,
    aweme_count: 1,
    comment_count: 1,
    last_task_id: null,
    last_task_status: null,
    last_run_at: null,
    prompt: "赛道绑定测试提示词",
    created_at: now,
    updated_at: now,
  }
}

function taskFixture(trackId = growthTrackId) {
  const track = tracks.find((item) => item.id === trackId) ?? tracks[0]
  return {
    id: taskId,
    owner_id: ownerId,
    track_id: track.id,
    track_name: track.name,
    track_is_default: track.is_default,
    account_id: null,
    account_pool_id: null,
    account_strategy: "least_loaded",
    crawl_type: "search",
    status: "succeeded",
    request: { keywords: ["露营"] },
    aweme_count: 1,
    comment_count: 1,
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
  }
}

function keywordFixture(trackId = growthTrackId) {
  const track = tracks.find((item) => item.id === trackId) ?? tracks[0]
  return {
    id: keywordId,
    track_id: track.id,
    track_name: track.name,
    track_is_default: track.is_default,
    keyword: track.is_default ? "默认关键词" : "露营装备",
    enabled: true,
    notes: "赛道绑定测试",
    status: "crawled",
    task_count: 1,
    active_task_count: 0,
    success_task_count: 1,
    failed_task_count: 0,
    aweme_count: 10,
    last_task_id: taskId,
    last_task_status: "succeeded",
    last_crawled_at: now,
    created_at: now,
    updated_at: now,
  }
}

async function mockTrackCatalog(page: Page) {
  await page.route("**/api/v1/douyin/tracks**", async (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    const url = new URL(route.request().url())
    const requestedLimit = url.searchParams.get("limit")
    // The reusable selector loads the complete catalog in one bounded request.
    // The track-management page itself omits the limit and uses API pagination.
    if (requestedLimit !== null) expect(requestedLimit).toBe("200")
    await route.fulfill({ json: { data: tracks, count: tracks.length } })
  })
}

async function mockAccountChoices(page: Page) {
  await page.route("**/api/v1/douyin/accounts**", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })
}

test("track selector exposes a retry path when the catalog cannot be loaded", async ({
  page,
}) => {
  let attempts = 0
  await page.route("**/api/v1/douyin/tracks**", async (route) => {
    attempts += 1
    if (attempts === 1) {
      await route.fulfill({ status: 503, json: { detail: "暂时不可用" } })
      return
    }
    await route.fulfill({ json: { data: tracks, count: tracks.length } })
  })
  await page.route("**/api/v1/douyin/tasks?**", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })

  await page.goto("/douyin")
  await expect(page.getByRole("alert").getByText("赛道加载失败")).toBeVisible()
  await page.getByRole("button", { name: "重新加载赛道" }).click()
  await expect(page.getByLabel("按赛道筛选任务")).toContainText("全部赛道")
  expect(attempts).toBe(2)
})

test("default track is clearly marked and protected from destructive actions", async ({
  page,
}) => {
  await mockTrackCatalog(page)
  await page.goto("/douyin-tracks")

  const defaultCard = page.getByRole("link", { name: "查看赛道 默认赛道 详情" })
  await expect(defaultCard.getByText("默认", { exact: true })).toBeVisible()
  await defaultCard.getByRole("button", { name: "赛道操作" }).click()
  await expect(
    page.getByRole("menuitem", { name: "默认赛道必须启用" }),
  ).toHaveAttribute("data-disabled", "")
  await expect(
    page.getByRole("menuitem", { name: "默认赛道不可删除" }),
  ).toHaveAttribute("data-disabled", "")
  await page.keyboard.press("Escape")

  const growthCard = page.getByRole("link", { name: "查看赛道 私域增长 详情" })
  await growthCard.getByRole("button", { name: "赛道操作" }).click()
  await page.getByRole("menuitem", { name: "删除赛道" }).click()
  await expect(
    page.getByText("其关键词、采集任务和内容数据都会完整迁移到默认赛道"),
  ).toBeVisible()
})

test("track run defaults to all enabled keywords and submits an ordered subset", async ({
  page,
}) => {
  const tentKeywordId = "55555555-5555-4555-8555-555555555555"
  const stoveKeywordId = "66666666-6666-4666-8666-666666666666"
  const disabledKeywordId = "77777777-7777-4777-8777-777777777777"
  const runKeywords = [
    {
      ...keywordFixture(growthTrackId),
      id: tentKeywordId,
      keyword: "露营帐篷",
    },
    {
      ...keywordFixture(growthTrackId),
      id: stoveKeywordId,
      keyword: "户外炉具",
    },
    {
      ...keywordFixture(growthTrackId),
      id: disabledKeywordId,
      keyword: "停用旧词",
      enabled: false,
    },
  ]
  const submittedBodies: Array<Record<string, unknown>> = []
  let keywordRequests = 0
  let taskRequests = 0
  let releaseKeywords: (() => void) | undefined
  const keywordGate = new Promise<void>((resolve) => {
    releaseKeywords = resolve
  })

  await mockTrackCatalog(page)
  await mockAccountChoices(page)
  await page.route(
    `**/api/v1/douyin/tracks/${growthTrackId}/keywords`,
    async (route) => {
      keywordRequests += 1
      await keywordGate
      await route.fulfill({ json: { data: runKeywords, count: 3 } })
    },
  )
  await page.route(
    `**/api/v1/douyin/tracks/${growthTrackId}/tasks`,
    async (route) => {
      taskRequests += 1
      submittedBodies.push(route.request().postDataJSON())
      if (taskRequests === 3) {
        await route.fulfill({
          status: 409,
          json: { detail: "赛道或关键词已发生变化" },
        })
        return
      }
      await route.fulfill({
        status: 201,
        json: { data: [taskFixture(growthTrackId)], count: 1 },
      })
    },
  )

  await page.goto("/douyin-tracks")
  const growthCard = page.getByRole("link", { name: "查看赛道 私域增长 详情" })
  await growthCard.getByRole("button", { name: "运营这个赛道" }).click()
  await expect(page.getByText("正在加载本次采集关键词…")).toBeVisible()
  releaseKeywords?.()

  await expect(page.getByText("已选择 2 / 2")).toBeVisible()
  // 两个启用词都已跑过任务，"仅选未采集"无可选目标而应禁用。
  await expect(page.getByLabel("仅选择从未采集过的关键词")).toBeDisabled()
  const tentChip = page.getByLabel("选择采集关键词 露营帐篷")
  const stoveChip = page.getByLabel("选择采集关键词 户外炉具")
  await expect(tentChip).toHaveAttribute("aria-pressed", "true")
  await expect(stoveChip).toHaveAttribute("aria-pressed", "true")
  await expect(
    page
      .getByRole("group", { name: "选择本次采集关键词" })
      .getByText("停用旧词", { exact: true }),
  ).toBeVisible()
  await expect(
    page.getByText(/另有 \d+ ?个已停用关键词，不会加入本次任务/),
  ).toBeVisible()

  await tentChip.click()
  await expect(page.getByText("已选择 1 / 2")).toBeVisible()
  const requestsBeforeRefetch = keywordRequests
  await page.getByLabel("刷新本次采集关键词").click()
  await expect
    .poll(() => keywordRequests)
    .toBeGreaterThan(requestsBeforeRefetch)
  await expect(tentChip).toHaveAttribute("aria-pressed", "false")
  await page.getByLabel("全选本次采集关键词").click()
  await expect(page.getByText("已选择 2 / 2")).toBeVisible()
  await page.getByLabel("清空本次采集关键词选择").click()
  await expect(page.getByText("已选择 0 / 2")).toBeVisible()
  await expect(
    page.getByRole("button", { name: "启动赛道采集" }),
  ).toBeDisabled()

  await page.getByLabel("全选本次采集关键词").click()
  await page.getByLabel("选择采集关键词 露营帐篷").click()
  await page.getByRole("button", { name: "启动赛道采集" }).click()
  await expect
    .poll(() => submittedBodies[0]?.keyword_ids)
    .toEqual([stoveKeywordId])

  await growthCard.getByRole("button", { name: "运营这个赛道" }).click()
  await expect(page.getByText("已选择 2 / 2")).toBeVisible()
  await page.setViewportSize({ width: 375, height: 812 })
  await expect(
    page.getByRole("group", { name: "选择本次采集关键词" }),
  ).toBeVisible()
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true)
  await page.setViewportSize({ width: 844, height: 390 })
  await expect(
    page.getByRole("group", { name: "选择本次采集关键词" }),
  ).toBeVisible()
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true)
  await page.getByRole("button", { name: "启动赛道采集" }).click()
  await expect.poll(() => submittedBodies[1]?.keyword_ids).toEqual([])

  await page.setViewportSize({ width: 1280, height: 720 })
  await growthCard.getByRole("button", { name: "运营这个赛道" }).click()
  await expect(page.getByText("已选择 2 / 2")).toBeVisible()
  const requestsBeforeConflict = keywordRequests
  await page.getByRole("button", { name: "启动赛道采集" }).click()
  await expect
    .poll(() => keywordRequests)
    .toBeGreaterThan(requestsBeforeConflict)
  await expect(
    page.getByRole("heading", { name: "私域增长 · 运营工作区" }),
  ).not.toBeVisible()
})

test("track run can select only the keywords that were never crawled", async ({
  page,
}) => {
  const freshKeywordAId = "aaaa1111-1111-4111-8111-111111111111"
  const crawledKeywordId = "bbbb2222-2222-4222-8222-222222222222"
  const freshKeywordBId = "cccc3333-3333-4333-8333-333333333333"
  const runKeywords = [
    {
      ...keywordFixture(growthTrackId),
      id: freshKeywordAId,
      keyword: "新词露营灯",
      task_count: 0,
      aweme_count: 0,
    },
    {
      ...keywordFixture(growthTrackId),
      id: crawledKeywordId,
      keyword: "老词帐篷",
      task_count: 5,
    },
    {
      ...keywordFixture(growthTrackId),
      id: freshKeywordBId,
      keyword: "新词折叠椅",
      task_count: 0,
      aweme_count: 0,
    },
  ]
  const submittedBodies: Array<Record<string, unknown>> = []

  await mockTrackCatalog(page)
  await mockAccountChoices(page)
  await page.route(
    `**/api/v1/douyin/tracks/${growthTrackId}/keywords`,
    async (route) => {
      await route.fulfill({ json: { data: runKeywords, count: 3 } })
    },
  )
  await page.route(
    `**/api/v1/douyin/tracks/${growthTrackId}/tasks`,
    async (route) => {
      submittedBodies.push(route.request().postDataJSON())
      await route.fulfill({
        status: 201,
        json: { data: [taskFixture(growthTrackId)], count: 1 },
      })
    },
  )

  await page.goto("/douyin-tracks")
  const growthCard = page.getByRole("link", { name: "查看赛道 私域增长 详情" })
  await growthCard.getByRole("button", { name: "运营这个赛道" }).click()
  await expect(page.getByText("已选择 3 / 3")).toBeVisible()

  const freshAChip = page.getByLabel("选择采集关键词 新词露营灯")
  const freshBChip = page.getByLabel("选择采集关键词 新词折叠椅")
  const crawledChip = page.getByLabel("选择采集关键词 老词帐篷")
  await page.getByLabel("仅选择从未采集过的关键词").click()
  await expect(page.getByText("已选择 2 / 3")).toBeVisible()
  await expect(freshAChip).toHaveAttribute("aria-pressed", "true")
  await expect(freshBChip).toHaveAttribute("aria-pressed", "true")
  await expect(crawledChip).toHaveAttribute("aria-pressed", "false")

  await page.getByRole("button", { name: "启动赛道采集" }).click()
  await expect
    .poll(() => submittedBodies[0]?.keyword_ids)
    .toEqual([freshKeywordAId, freshKeywordBId])
})

test("track run recovers from keyword query errors and explains an empty track", async ({
  page,
}) => {
  let attempts = 0
  await mockTrackCatalog(page)
  await mockAccountChoices(page)
  await page.route(
    `**/api/v1/douyin/tracks/${growthTrackId}/keywords`,
    async (route) => {
      attempts += 1
      if (attempts === 1) {
        await route.fulfill({ status: 503, json: { detail: "暂时不可用" } })
        return
      }
      await route.fulfill({ json: { data: [], count: 0 } })
    },
  )

  await page.goto("/douyin-tracks")
  const growthCard = page.getByRole("link", { name: "查看赛道 私域增长 详情" })
  await growthCard.getByRole("button", { name: "运营这个赛道" }).click()
  await expect(
    page.getByRole("alert").getByText("关键词读取失败，暂时不能启动采集。"),
  ).toBeVisible()
  await page.getByRole("button", { name: "重新加载" }).click()
  await expect(page.getByText("当前赛道还没有关键词")).toBeVisible()
  await expect(
    page.getByRole("button", { name: "启动赛道采集" }),
  ).toBeDisabled()
  expect(attempts).toBe(2)
})

test("track run blocks disabled tracks and oversized separate batches", async ({
  page,
}) => {
  const disabledTrackId = "88888888-8888-4888-8888-888888888888"
  const disabledTrack = {
    ...trackFixture(disabledTrackId, "暂停赛道", false),
    enabled: false,
  }
  const manyKeywords = Array.from({ length: 21 }, (_, index) => ({
    ...keywordFixture(growthTrackId),
    id: `99999999-9999-4999-8999-${String(index).padStart(12, "0")}`,
    keyword: `批量关键词 ${index + 1}`,
  }))
  await page.route("**/api/v1/douyin/tracks**", async (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    if (
      new URL(route.request().url()).pathname.endsWith(`/${disabledTrackId}`)
    ) {
      await route.fulfill({ json: disabledTrack })
      return
    }
    await route.fulfill({
      json: { data: [...tracks, disabledTrack], count: 3 },
    })
  })
  await mockAccountChoices(page)
  await page.route(
    `**/api/v1/douyin/tracks/${growthTrackId}/keywords`,
    async (route) => {
      await route.fulfill({ json: { data: manyKeywords, count: 21 } })
    },
  )

  await page.goto("/douyin-tracks")
  const disabledCard = page.getByRole("link", {
    name: "查看赛道 暂停赛道 详情",
  })
  await expect(
    disabledCard.getByRole("button", { name: "运营这个赛道" }),
  ).toBeDisabled()
  await page.goto(`/douyin-tracks?run=${disabledTrackId}`)
  await expect(
    page.getByRole("alert").getByText("当前赛道已停用"),
  ).toBeVisible()
  await expect(
    page.getByRole("button", { name: "启动赛道采集" }),
  ).toBeDisabled()
  await page.keyboard.press("Escape")

  const growthCard = page.getByRole("link", { name: "查看赛道 私域增长 详情" })
  await growthCard.getByRole("button", { name: "运营这个赛道" }).click()
  await expect(page.getByText("已选择 21 / 21")).toBeVisible()
  await page.getByLabel("任务组织方式").click()
  await page.getByRole("option", { name: "每词独立任务" }).click()
  await expect(
    page.getByRole("alert").getByText("每词独立任务一次最多选择 20 个关键词"),
  ).toBeVisible()
  await expect(
    page.getByRole("button", { name: "启动赛道采集" }),
  ).toBeDisabled()
})

test("track run keeps all-keyword sentinel above the explicit selection limit", async ({
  page,
}) => {
  const manyKeywords = Array.from({ length: 202 }, (_, index) => ({
    ...keywordFixture(growthTrackId),
    id: `aaaaaaaa-aaaa-4aaa-8aaa-${String(index).padStart(12, "0")}`,
    keyword: `长列表关键词 ${index + 1}`,
  }))
  let submittedBody: Record<string, unknown> | undefined

  await mockTrackCatalog(page)
  await mockAccountChoices(page)
  await page.route(
    `**/api/v1/douyin/tracks/${growthTrackId}/keywords`,
    async (route) => {
      await route.fulfill({ json: { data: manyKeywords, count: 202 } })
    },
  )
  await page.route(
    `**/api/v1/douyin/tracks/${growthTrackId}/tasks`,
    async (route) => {
      submittedBody = route.request().postDataJSON()
      await route.fulfill({
        status: 202,
        json: { data: [taskFixture(growthTrackId)], count: 1 },
      })
    },
  )

  await page.goto("/douyin-tracks")
  const growthCard = page.getByRole("link", { name: "查看赛道 私域增长 详情" })
  await growthCard.getByRole("button", { name: "运营这个赛道" }).click()
  await expect(page.getByText("已选择 202 / 202")).toBeVisible()
  // 默认的“每词独立任务”受 20 词上限约束；本用例验证 200 词显式选择上限，
  // 因此先切换到组合任务模式，把该上限隔离开。
  await page.getByLabel("任务组织方式").click()
  await page.getByRole("option", { name: "组合任务" }).click()

  await page
    .getByLabel("选择采集关键词 长列表关键词 1", { exact: true })
    .click()
  await expect(page.getByText("已选择 201 / 202")).toBeVisible()
  await expect(
    page.getByRole("alert").getByText("部分选择一次最多 200 个关键词"),
  ).toBeVisible()
  await expect(
    page.getByRole("button", { name: "启动赛道采集" }),
  ).toBeDisabled()

  await page
    .getByLabel("选择采集关键词 长列表关键词 2", { exact: true })
    .click()
  await expect(page.getByText("已选择 200 / 202")).toBeVisible()
  await expect(
    page.getByRole("alert").getByText("部分选择一次最多 200 个关键词"),
  ).not.toBeVisible()
  await expect(page.getByRole("button", { name: "启动赛道采集" })).toBeEnabled()

  await page.getByLabel("全选本次采集关键词").click()
  await expect(page.getByText("已选择 202 / 202")).toBeVisible()
  await page.getByRole("button", { name: "启动赛道采集" }).click()
  await expect.poll(() => submittedBody?.keyword_ids).toEqual([])
})

test("direct task creation visibly defaults to a track and submits the selected track", async ({
  page,
}) => {
  let createdBody: Record<string, unknown> = {}
  await mockTrackCatalog(page)
  await mockAccountChoices(page)
  await page.route("**/api/v1/douyin/tasks**", async (route) => {
    const request = route.request()
    const pathname = new URL(request.url()).pathname
    if (request.method() === "POST" && pathname.endsWith("/tasks")) {
      createdBody = request.postDataJSON()
      await route.fulfill({ status: 201, json: taskFixture(growthTrackId) })
      return
    }
    if (pathname.endsWith(`/tasks/${taskId}`)) {
      await route.fulfill({ json: taskFixture(growthTrackId) })
      return
    }
    await route.fulfill({ json: { data: [], count: 0 } })
  })

  await page.goto("/douyin")
  await expect(page.getByLabel("按赛道筛选任务")).toContainText("全部赛道")
  await page.getByRole("button", { name: "创建任务" }).click()
  let trackSelect = page.getByLabel("选择所属赛道")
  await expect(trackSelect).toContainText("默认赛道")
  await trackSelect.click()
  await page.getByRole("option", { name: "私域增长" }).click()
  await page.getByRole("dialog").getByRole("button", { name: "取消" }).click()

  // Reopening an unscoped creator must not retain a stale track choice.
  await page.getByRole("button", { name: "创建任务" }).click()
  trackSelect = page.getByLabel("选择所属赛道")
  await expect(trackSelect).toContainText("默认赛道")
  await trackSelect.click()
  await page.getByRole("option", { name: "私域增长" }).click()
  await page.getByLabel("搜索关键词").fill("露营装备")
  await page.getByRole("button", { name: "创建并运行" }).click()

  await expect.poll(() => createdBody.track_id).toBe(growthTrackId)
})

test("keyword workspace is scoped to one track and propagates it to create and batch task requests", async ({
  page,
}) => {
  let lastListTrack = ""
  let createdKeywordBody: Record<string, unknown> = {}
  let createdTaskBody: Record<string, unknown> = {}
  await mockTrackCatalog(page)
  await mockAccountChoices(page)
  await page.route("**/api/v1/douyin/keywords/**", async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.pathname.endsWith("/keywords/batch-tasks")) {
      createdTaskBody = request.postDataJSON()
      await route.fulfill({ json: { data: [taskFixture()], count: 1 } })
      return
    }
    if (request.method() === "POST") {
      createdKeywordBody = request.postDataJSON()
      await route.fulfill({
        status: 201,
        json: {
          data: [keywordFixture(String(createdKeywordBody.track_id))],
          created_count: 1,
          existing_count: 0,
        },
      })
      return
    }
    lastListTrack = url.searchParams.get("track_id") ?? ""
    const requestedTrack = lastListTrack || defaultTrackId
    await route.fulfill({
      json: { data: [keywordFixture(requestedTrack)], count: 1 },
    })
  })

  await page.goto("/douyin-keywords")
  await expect(page.getByLabel("按赛道筛选关键词")).toContainText("默认赛道")
  await expect.poll(() => lastListTrack).toBe(defaultTrackId)
  await page.getByLabel("按赛道筛选关键词").click()
  await page.getByRole("option", { name: "私域增长" }).click()
  await expect.poll(() => lastListTrack).toBe(growthTrackId)
  await expect(page.getByText("露营装备", { exact: true })).toBeVisible()
  await expect(page.getByRole("link", { name: "私域增长" })).toBeVisible()

  await page.getByRole("button", { name: "添加关键词" }).click()
  await expect(page.getByLabel("选择所属赛道")).toContainText("私域增长")
  await page.getByLabel("关键词", { exact: true }).fill("户外露营")
  await page.getByRole("button", { name: "保存关键词" }).click()
  await expect.poll(() => createdKeywordBody.track_id).toBe(growthTrackId)

  await page.getByLabel("选择关键词 露营装备").click()
  await page.getByRole("button", { name: "批量创建任务" }).click()
  await expect(
    page.getByRole("dialog").getByText("私域增长", { exact: true }),
  ).toBeVisible()
  await page.getByRole("button", { name: "确认创建并运行" }).click()
  await expect.poll(() => createdTaskBody.track_id).toBe(growthTrackId)
})

test("primary data filters send the selected track without hiding all tracks initially", async ({
  page,
}) => {
  let taskTrack = "unset"
  let libraryTrack = "unset"
  let commentTrack = "unset"
  let tagTrack = "unset"
  let interactionTrack = "unset"
  await mockTrackCatalog(page)
  await page.route("**/api/v1/douyin/tasks?**", async (route) => {
    taskTrack =
      new URL(route.request().url()).searchParams.get("track_id") ?? ""
    await route.fulfill({ json: { data: [taskFixture()], count: 1 } })
  })
  await page.route("**/api/v1/douyin/library/creators**", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })
  await page.route("**/api/v1/douyin/tags/**", async (route) => {
    tagTrack = new URL(route.request().url()).searchParams.get("track_id") ?? ""
    await route.fulfill({ json: { data: [], count: 0 } })
  })
  await page.route("**/api/v1/douyin/library/works**", async (route) => {
    libraryTrack =
      new URL(route.request().url()).searchParams.get("track_id") ?? ""
    await route.fulfill({ json: { data: [], count: 0 } })
  })
  await page.route("**/api/v1/douyin/comments?**", async (route) => {
    commentTrack =
      new URL(route.request().url()).searchParams.get("track_id") ?? ""
    await route.fulfill({
      json: {
        data: [],
        count: 0,
        summary: {
          matched_count: 0,
          top_level_count: 0,
          reply_count: 0,
          picture_count: 0,
          total_like_count: 0,
        },
      },
    })
  })
  await page.route("**/api/v1/douyin/interactions**", async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith("/quota")) {
      await route.fulfill({ json: [] })
      return
    }
    interactionTrack = url.searchParams.get("track_id") ?? ""
    await route.fulfill({ json: { data: [], count: 0 } })
  })

  await page.goto("/douyin")
  await expect(page.getByLabel("按赛道筛选任务")).toContainText("全部赛道")
  await expect.poll(() => taskTrack).toBe("")
  await page.getByLabel("按赛道筛选任务").click()
  await page.getByRole("option", { name: "私域增长" }).click()
  await expect.poll(() => taskTrack).toBe(growthTrackId)

  await page.goto("/douyin-library")
  await expect(page.getByLabel("按赛道筛选视频资源")).toContainText("全部赛道")
  await page.getByLabel("按赛道筛选视频资源").click()
  await page.getByRole("option", { name: "私域增长" }).click()
  await expect.poll(() => libraryTrack).toBe(growthTrackId)

  await page.goto("/douyin-comments")
  await expect(page.getByLabel("按赛道筛选评论")).toContainText("全部赛道")
  await page.getByLabel("按赛道筛选评论").click()
  await page.getByRole("option", { name: "私域增长" }).click()
  await expect.poll(() => commentTrack).toBe(growthTrackId)

  await page.goto("/douyin-tags")
  await expect(page.getByLabel("按赛道筛选标签")).toContainText("全部赛道")
  await page.getByLabel("按赛道筛选标签").click()
  await page.getByRole("option", { name: "私域增长" }).click()
  await expect.poll(() => tagTrack).toBe(growthTrackId)

  await page.goto("/douyin-interactions")
  await expect(page.getByLabel("按赛道筛选互动任务")).toContainText("全部赛道")
  await page.getByLabel("按赛道筛选互动任务").click()
  await page.getByRole("option", { name: "私域增长" }).click()
  await expect.poll(() => interactionTrack).toBe(growthTrackId)

  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.getByLabel("按赛道筛选互动任务")).toBeVisible()
  const noHorizontalOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth,
  )
  expect(noHorizontalOverflow).toBe(true)
})

function creatorFixture(
  id: string,
  secUid: string,
  nickname: string,
  trackId = growthTrackId,
) {
  const track = tracks.find((item) => item.id === trackId) ?? tracks[0]
  return {
    id,
    track_id: track.id,
    track_name: track.name,
    track_is_default: track.is_default,
    sec_uid: secUid,
    creator_hash: `hash-${id}`,
    nickname,
    enabled: true,
    notes: "",
    status: "unprocessed",
    task_count: 0,
    active_task_count: 0,
    success_task_count: 0,
    failed_task_count: 0,
    aweme_count: 0,
    last_task_id: null,
    last_task_status: null,
    last_crawled_at: null,
    created_at: now,
    updated_at: now,
  }
}

test("track detail launches a creator crawl task from roster selection", async ({
  page,
}) => {
  let createdBody: Record<string, unknown> = {}
  await mockAccountChoices(page)
  await page.route("**/api/v1/douyin/tracks?**", async (route) => {
    await route.fulfill({ json: { data: tracks, count: tracks.length } })
  })
  await page.route("**/api/v1/douyin/tracks/**", async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith("/keywords")) {
      await route.fulfill({ json: { data: [], count: 0 } })
      return
    }
    if (url.pathname.endsWith("/creators")) {
      await route.fulfill({ json: { data: [], count: 0 } })
      return
    }
    await route.fulfill({
      json: trackFixture(growthTrackId, "私域增长", false),
    })
  })
  await page.route("**/api/v1/douyin/creators/**", async (route) => {
    const request = route.request()
    if (request.method() === "GET") {
      await route.fulfill({
        json: {
          count: 2,
          data: [
            creatorFixture("creator-abc", "sec-uid-abc", "露营达人"),
            creatorFixture("creator-def", "sec-uid-def", "带货小王子"),
          ],
        },
      })
      return
    }
    await route.fallback()
  })
  await page.route("**/api/v1/douyin/tasks**", async (route) => {
    const request = route.request()
    const pathname = new URL(request.url()).pathname
    if (request.method() === "POST" && pathname.endsWith("/tasks")) {
      createdBody = request.postDataJSON()
      await route.fulfill({
        status: 201,
        json: { ...taskFixture(growthTrackId), crawl_type: "creator" },
      })
      return
    }
    if (pathname.endsWith(`/tasks/${taskId}`)) {
      await route.fulfill({ json: taskFixture(growthTrackId) })
      return
    }
    await route.fulfill({ json: { data: [], count: 0 } })
  })

  await page.goto(`/douyin-tracks/${growthTrackId}`)
  // 入口位于赛道详情页头部操作区（无需切换到"任务"Tab）
  await page.getByRole("button", { name: "添加达人爬取" }).click()
  const dialog = page.getByRole("dialog")
  // Radix Select 同时渲染可见触发器与隐藏原生 select，这里按 button 限定触发器。
  await expect(
    dialog.locator('button[role="combobox"]').filter({ hasText: "创作者作品" }),
  ).toBeVisible()
  await expect(page.getByLabel("选择所属赛道")).toContainText("私域增长")
  // 从达人名单下拉勾选两位达人
  await expect(page.getByText("从达人名单选择")).toBeVisible()
  await page.getByLabel("选择达人 露营达人").check()
  await page.getByLabel("选择达人 带货小王子").check()
  await expect(page.getByText("已选 2 位")).toBeVisible()
  await page.getByRole("button", { name: "创建并运行" }).click()
  await expect.poll(() => createdBody.crawl_type).toBe("creator")
  expect(createdBody.creator_ids).toEqual(["sec-uid-abc", "sec-uid-def"])
  expect(createdBody.track_id).toBe(growthTrackId)
})

test("creator dialog merges manually entered creators into the roster before submitting", async ({
  page,
}) => {
  let createdBody: Record<string, unknown> = {}
  let createdCreatorsBody: Record<string, unknown> | null = null
  await mockAccountChoices(page)
  await page.route("**/api/v1/douyin/tracks?**", async (route) => {
    await route.fulfill({ json: { data: tracks, count: tracks.length } })
  })
  await page.route("**/api/v1/douyin/tracks/**", async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith("/keywords")) {
      await route.fulfill({ json: { data: [], count: 0 } })
      return
    }
    if (url.pathname.endsWith("/creators")) {
      await route.fulfill({ json: { data: [], count: 0 } })
      return
    }
    await route.fulfill({
      json: trackFixture(growthTrackId, "私域增长", false),
    })
  })
  await page.route("**/api/v1/douyin/creators/**", async (route) => {
    const request = route.request()
    const pathname = new URL(request.url()).pathname
    if (request.method() === "GET") {
      await route.fulfill({
        json: {
          count: 1,
          data: [creatorFixture("creator-abc", "sec-uid-abc", "露营达人")],
        },
      })
      return
    }
    if (request.method() === "POST" && pathname.endsWith("/creators/bulk")) {
      createdCreatorsBody = request.postDataJSON()
      await route.fulfill({
        json: {
          data: [creatorFixture("creator-new", "sec-uid-new", "新达人手输")],
          created_count: 1,
          existing_count: 0,
        },
      })
      return
    }
    await route.fallback()
  })
  await page.route("**/api/v1/douyin/tasks**", async (route) => {
    const request = route.request()
    const pathname = new URL(request.url()).pathname
    if (request.method() === "POST" && pathname.endsWith("/tasks")) {
      createdBody = request.postDataJSON()
      await route.fulfill({
        status: 201,
        json: { ...taskFixture(growthTrackId), crawl_type: "creator" },
      })
      return
    }
    if (pathname.endsWith(`/tasks/${taskId}`)) {
      await route.fulfill({ json: taskFixture(growthTrackId) })
      return
    }
    await route.fulfill({ json: { data: [], count: 0 } })
  })

  await page.goto(`/douyin-tracks/${growthTrackId}`)
  await page.getByRole("button", { name: "添加达人爬取" }).click()
  // 勾选名单中已有达人，同时手动输入一位新达人
  await page.getByLabel("选择达人 露营达人").check()
  await page.getByRole("button", { name: "+ 手动输入新达人" }).click()
  await page
    .getByPlaceholder(/每行一个创作者主页链接或 sec_user_id/)
    .fill("https://www.douyin.com/user/MS4wLjABAAAAhandmade")
  await page.getByRole("button", { name: "创建并运行" }).click()

  // 手动输入的达人先写入当前赛道达人名单，再与已选达人合并提交
  await expect.poll(() => createdCreatorsBody).not.toBeNull()
  expect(createdCreatorsBody?.creators).toEqual([
    "https://www.douyin.com/user/MS4wLjABAAAAhandmade",
  ])
  expect(createdCreatorsBody?.track_id).toBe(growthTrackId)
  await expect.poll(() => createdBody.crawl_type).toBe("creator")
  expect(createdBody.creator_ids).toEqual(["sec-uid-abc", "sec-uid-new"])
  expect(createdBody.track_id).toBe(growthTrackId)
})
