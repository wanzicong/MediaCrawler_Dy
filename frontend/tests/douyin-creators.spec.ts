import { expect, test } from "@playwright/test"

const trackPayload = {
  id: "track-1",
  name: "私域增长",
  description: "",
  enabled: true,
  is_default: true,
  keyword_count: 3,
  enabled_keyword_count: 3,
  task_count: 2,
  active_task_count: 0,
  aweme_count: 40,
  comment_count: 12,
  last_task_id: null,
  last_task_status: null,
  last_task_created_at: null,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
}

function creatorPayload(
  overrides: Partial<{
    id: string
    nickname: string
    sec_uid: string
    creator_hash: string
    status: string
    task_count: number
    aweme_count: number
    enabled: boolean
    is_placeholder: boolean
    track_id: string
  }> = {},
) {
  const now = new Date().toISOString()
  return {
    id: "creator-1",
    track_id: "track-1",
    track_name: "私域增长",
    track_is_default: true,
    sec_uid: "MS4wLjABAAAAabcdefgh123456",
    creator_hash: "hash-a",
    nickname: "露营达人",
    enabled: true,
    is_placeholder: false,
    notes: "",
    status: "crawled",
    task_count: 3,
    active_task_count: 0,
    success_task_count: 3,
    failed_task_count: 0,
    aweme_count: 18,
    last_task_id: "task-1",
    last_task_status: "succeeded",
    last_crawled_at: "2026-08-01T00:00:00Z",
    created_at: now,
    updated_at: now,
    ...overrides,
  }
}

test("creator directory lists the managed creator roster and deep-links into the library", async ({
  page,
}) => {
  let requestedTrack = "unset"
  let requestedSort = "unset"
  await page.route("**/api/v1/douyin/tracks**", async (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    await route.fulfill({
      json: { data: [trackPayload], count: 1 },
    })
  })
  await page.route("**/api/v1/douyin/creators/**", async (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    const params = new URL(route.request().url()).searchParams
    requestedTrack = params.get("track_id") ?? ""
    // overview 汇总查询不带排序参数，只在主列表查询时记录
    if (params.get("sort_by")) {
      requestedSort = `${params.get("sort_by")}:${params.get("sort_order")}`
    }
    await route.fulfill({
      json: {
        count: 3,
        data: [
          creatorPayload({
            id: "creator-b",
            creator_hash: "hash-b",
            nickname: "带货小王子",
            status: "unprocessed",
            task_count: 0,
            aweme_count: 2,
          }),
          creatorPayload({
            id: "creator-a",
            creator_hash: "hash-a",
            nickname: "露营达人",
            status: "crawled",
            task_count: 3,
            aweme_count: 18,
          }),
          creatorPayload({
            id: "creator-c",
            creator_hash: "hash-c",
            nickname: "私域老司机",
            status: "active",
            task_count: 1,
            aweme_count: 7,
          }),
        ],
      },
    })
  })

  await page.goto("/douyin-creators")
  await expect(page.getByRole("heading", { name: "达人列表" })).toBeVisible()
  await expect.poll(() => requestedTrack).toBe("")
  await expect.poll(() => requestedSort).toBe("last_crawled_at:desc")

  // 默认按最近爬取排序（后端排序，前端按返回顺序展示）
  const names = page.locator("p.truncate.font-medium[title]")
  await expect(names.nth(0)).toHaveText("带货小王子")

  // 卡片展示昵称、状态徽章、任务与作品数
  await expect(page.getByText("3 个任务 · 18 个作品")).toBeVisible()
  await expect(page.getByText("已爬取", { exact: true }).first()).toBeVisible()
  await expect(page.getByText("进行中", { exact: true }).first()).toBeVisible()
  await expect(page.getByText("未爬取", { exact: true }).first()).toBeVisible()
  await expect(page.locator("body")).not.toContainText("abcdefgh123456")

  await page.getByRole("button", { name: "横条" }).click()
  await expect(page.getByText("3 个任务 · 18 个作品")).toBeVisible()
  await page.getByRole("button", { name: "卡片" }).click()
  await expect(page.getByLabel("编辑达人 露营达人")).toBeVisible()
  await page.getByRole("button", { name: "表格" }).click()

  // 达人卡片直达视频资源库并带上创作者过滤
  await expect(
    page.getByRole("link", { name: "查看 露营达人 的作品" }),
  ).toHaveAttribute("href", /\/douyin-library\?creator=hash-a/)

  // 切换排序会把 sort_by / sort_order 带给后端
  await page.getByLabel("达人排序方式").click()
  await page.getByRole("option", { name: "昵称 A-Z" }).click()
  await expect.poll(() => requestedSort).toBe("nickname:asc")

  // 按赛道筛选会把 track_id 带给后端
  await page.getByLabel("按赛道筛选达人").click()
  await page.getByRole("option", { name: /私域增长/ }).click()
  await expect.poll(() => requestedTrack).toBe("track-1")
})

test("creator directory creates tasks from selected creators with track binding", async ({
  page,
}) => {
  let createdBody: Record<string, unknown> | null = null
  await page.route("**/api/v1/douyin/tracks**", async (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    await route.fulfill({
      json: { data: [trackPayload], count: 1 },
    })
  })
  await page.route("**/api/v1/douyin/creators/**", async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (request.method() === "GET") {
      await route.fulfill({
        json: {
          count: 2,
          data: [
            creatorPayload({ id: "creator-1" }),
            creatorPayload({
              id: "creator-2",
              nickname: "带货小王子",
              creator_hash: "hash-b",
            }),
          ],
        },
      })
      return
    }
    if (url.pathname.endsWith("/batch-tasks")) {
      createdBody = request.postDataJSON() as Record<string, unknown>
      await route.fulfill({ json: { count: 2, data: [] } })
      return
    }
    await route.fallback()
  })
  await page.route("**/api/v1/douyin/accounts**", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })
  await page.route("**/api/v1/douyin/account-pools**", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })

  await page.goto("/douyin-creators")
  await expect(page.getByRole("heading", { name: "达人列表" })).toBeVisible()

  // 批量创建任务需要明确的赛道归属，先选中赛道再勾选达人
  await page.getByLabel("按赛道筛选达人").click()
  await page.getByRole("option", { name: /私域增长/ }).click()
  await page.getByLabel("选择达人 露营达人").check()
  await page.getByLabel("选择达人 带货小王子").check()
  await expect(page.getByText("已选择 2 位达人")).toBeVisible()
  await page.getByRole("button", { name: "批量创建任务" }).click()
  await expect(
    page.getByRole("heading", { name: "从 2 位达人创建任务" }),
  ).toBeVisible()
  await page.getByRole("button", { name: "确认创建并运行" }).click()

  await expect.poll(() => createdBody).not.toBeNull()
  expect(createdBody?.creator_ids).toEqual(["creator-1", "creator-2"])
  expect(createdBody?.track_id).toBe("track-1")
  expect(createdBody?.max_awemes).toBe(10)
})

test("creator directory adds new creators into the selected track", async ({
  page,
}) => {
  let createdCreators: Record<string, unknown> | null = null
  await page.route("**/api/v1/douyin/tracks**", async (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    await route.fulfill({
      json: { data: [trackPayload], count: 1 },
    })
  })
  await page.route("**/api/v1/douyin/creators/**", async (route) => {
    const request = route.request()
    if (request.method() === "GET") {
      await route.fulfill({ json: { count: 0, data: [] } })
      return
    }
    if (
      request.method() === "POST" &&
      !request.url().endsWith("/batch-tasks")
    ) {
      createdCreators = request.postDataJSON() as Record<string, unknown>
      await route.fulfill({
        json: { data: [], created_count: 2, existing_count: 0 },
      })
      return
    }
    await route.fallback()
  })

  await page.goto("/douyin-creators")
  await expect(page.getByText("当前赛道还没有达人")).toBeVisible()

  // 选择赛道后批量添加达人
  await page.getByLabel("按赛道筛选达人").click()
  await page.getByRole("option", { name: /私域增长/ }).click()
  await page.getByRole("button", { name: "添加达人" }).click()
  await page
    .getByLabel("达人主页链接或平台达人标识")
    .fill("https://www.douyin.com/user/MS4wLjABAAAAabcdef\nMS4wLjABAAAAaaaaaa")
  await page.getByLabel("统一备注（可选）").fill("头部达人")
  await page.getByRole("button", { name: "保存达人" }).click()

  await expect.poll(() => createdCreators).not.toBeNull()
  expect(createdCreators?.creators).toEqual([
    "https://www.douyin.com/user/MS4wLjABAAAAabcdef",
    "MS4wLjABAAAAaaaaaa",
  ])
  expect(createdCreators?.track_id).toBe("track-1")
  expect(createdCreators?.notes).toBe("头部达人")
})

test("creator directory syncs from awemes and completes placeholders", async ({
  page,
}) => {
  let awemeSyncCalled = false
  let patchBody: Record<string, unknown> | null = null
  await page.route("**/api/v1/douyin/tracks**", async (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    await route.fulfill({
      json: { data: [trackPayload], count: 1 },
    })
  })
  await page.route("**/api/v1/douyin/creators/**", async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (request.method() === "GET") {
      await route.fulfill({
        json: {
          count: 2,
          data: [
            creatorPayload({
              id: "creator-ph",
              nickname: "尘***客",
              sec_uid: "a1b2c3d4e5f60718",
              creator_hash: "a1b2c3d4e5f60718",
              is_placeholder: true,
              status: "unprocessed",
              task_count: 0,
            }),
            creatorPayload({ id: "creator-f", nickname: "露营达人" }),
          ],
        },
      })
      return
    }
    if (url.pathname.endsWith("/sync/awemes")) {
      awemeSyncCalled = true
      await route.fulfill({
        json: { total_count: 3, created_count: 2, existing_count: 1 },
      })
      return
    }
    if (request.method() === "PATCH") {
      patchBody = request.postDataJSON() as Record<string, unknown>
      await route.fulfill({
        json: creatorPayload({
          id: "creator-ph",
          nickname: "尘***客",
          sec_uid: "MS4wLjABAAAAcompleting",
          creator_hash: "a1b2c3d4e5f60718",
          is_placeholder: false,
          status: "unprocessed",
          task_count: 0,
        }),
      })
      return
    }
    await route.fallback()
  })

  await page.goto("/douyin-creators")
  await expect(page.getByRole("heading", { name: "达人列表" })).toBeVisible()

  // 占位达人：待补全徽章 + 不可勾选
  await expect(page.getByText("待补全", { exact: true }).first()).toBeVisible()
  await expect(page.getByLabel("选择达人 尘***客")).toBeDisabled()

  // 补全弹窗：填写主页链接 → PATCH 携带 sec_uid
  await page.getByRole("button", { name: "编辑达人 尘***客" }).click()
  await expect(page.getByRole("heading", { name: "补全达人" })).toBeVisible()
  await page
    .getByLabel("补全主页链接或平台达人标识")
    .fill("https://www.douyin.com/user/MS4wLjABAAAAcompleting")
  await page.getByRole("button", { name: "补全并保存" }).click()
  await expect.poll(() => patchBody).not.toBeNull()
  // 前端原样透传主页链接，链接→sec_user_id 的解析与哈希校验由后端完成
  expect(patchBody?.sec_uid).toBe(
    "https://www.douyin.com/user/MS4wLjABAAAAcompleting",
  )

  // 从历史作品同步：确认后调用导入接口并展示统计
  page.on("dialog", (dialog) => dialog.accept())
  await page.getByRole("button", { name: "从历史作品同步" }).click()
  await expect.poll(() => awemeSyncCalled).toBe(true)
  await expect(
    page.getByText("已聚合 3 位达人，导入 2 位（已存在 1 位）"),
  ).toBeVisible()
})
