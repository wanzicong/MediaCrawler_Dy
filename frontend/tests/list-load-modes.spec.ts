import { expect, type Page, test } from "@playwright/test"

const idleMediaMigration = {
  migration_status: "idle",
  migration_progress: 0,
  migration_attempt_count: 0,
  migration_error: null,
  migration_started_at: null,
  migration_finished_at: null,
}

const taskId = "11111111-1111-4111-8111-111111111111"

/** 造一条作品库行：编号就是它在全量结果里的序号（1 起）。 */
function makeWork(index: number) {
  const now = new Date().toISOString()
  return {
    aweme: {
      id: `w-${index}`,
      task_id: taskId,
      aweme_id: `73000000000000${String(index).padStart(4, "0")}`,
      aweme_type: "video",
      title: `作品 ${index}`,
      description: "",
      create_time: 1735689600,
      creator_hash: `creator-${index}`,
      sec_uid: `sec-${index}`,
      nickname: `作者 ${index}`,
      liked_count: index,
      collected_count: 0,
      comment_count: 0,
      share_count: 0,
      aweme_url: "",
      cover_url: "",
      video_download_url: "",
      music_download_url: "",
      note_download_url: "",
      source_keyword: "",
      fetched_at: now,
    },
    persisted_comment_count: 0,
    media: {
      id: `m-${index}`,
      task_id: taskId,
      aweme_id: `73000000000000${String(index).padStart(4, "0")}`,
      storage_backend: "local",
      status: "downloaded",
      progress: 100,
      attempt_count: 1,
      mime_type: "video/mp4",
      file_size: 1024,
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
}

function makeTask() {
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
    aweme_count: 90,
    comment_count: 0,
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

/** 按 skip / limit 切片的假后端：返回 { data, count } 与真实接口同形。 */
function slice(total: number, extra: Record<string, string>) {
  const skip = Number(extra.skip ?? 0)
  const limit = Number(extra.limit ?? 24)
  const data = []
  for (
    let index = skip + 1;
    index <= Math.min(skip + limit, total);
    index += 1
  ) {
    data.push(makeWork(index))
  }
  return { data, count: total }
}

/**
 * 续拉到「已加载全部」。
 *
 * 续拉有两种触发方式：滚到底自动续拉，或手动点「加载更多」（哨兵没进视口时）。
 * 两种都算正常行为，这里循环点，直到看到到底文案。
 */
async function loadUntilDone(page: Page) {
  const done = page.getByText(/已加载全部 \d+ 条/)
  const deadline = Date.now() + 25_000
  while (Date.now() < deadline) {
    if (await done.isVisible()) return
    const button = page.getByRole("button", { name: "加载更多" })
    // 加载期间按钮会暂时隐藏（换成「正在加载更多…」），点不到不算失败
    if (await button.count()) {
      await button.click({ timeout: 3_000 }).catch(() => undefined)
    }
    await page.waitForTimeout(300)
  }
  const loaderText = await page
    .getByTestId("scroll-loader")
    .innerText()
    .catch(() => "?")
  throw new Error(`列表没有加载到底，当前状态：${JSON.stringify(loaderText)}`)
}

async function mockLibraryPage(
  page: Page,
  total: number,
  onRequest?: (skip: number, limit: number) => void,
) {
  await page.route("**/api/v1/douyin/tracks**", async (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    await route.fulfill({ json: { data: [], count: 0 } })
  })
  await page.route("**/api/v1/douyin/library/creators**", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })
  await page.route("**/api/v1/douyin/tags/**", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })
  await page.route("**/api/v1/douyin/tasks**", async (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    await route.fulfill({ json: { data: [], count: 0 } })
  })
  await page.route("**/api/v1/douyin/library/works**", async (route) => {
    const params = new URL(route.request().url()).searchParams
    const skip = Number(params.get("skip") ?? 0)
    const limit = Number(params.get("limit") ?? 24)
    onRequest?.(skip, limit)
    await route.fulfill({
      json: slice(total, { skip: String(skip), limit: String(limit) }),
    })
  })
}

test("library list scrolls to load more and can switch back to paging", async ({
  page,
}) => {
  const requests: Array<[number, number]> = []
  await mockLibraryPage(page, 90, (skip, limit) => requests.push([skip, limit]))

  await page.goto("/douyin-library")

  // 默认就是滚动加载：只拉第一段，底部给续拉入口
  await expect(page.getByRole("button", { name: "滚动加载" })).toHaveAttribute(
    "aria-pressed",
    "true",
  )
  await expect(page.getByRole("button", { name: "分页" })).toHaveAttribute(
    "aria-pressed",
    "false",
  )
  await expect(page.getByText("已加载 32 / 90")).toBeVisible()
  expect(requests).toContainEqual([0, 32])

  // 哨兵进入视口后会自动续拉（滚到底就一直在底部继续加载），点按钮是兜底入口
  await loadUntilDone(page)
  expect(requests).toContainEqual([32, 32])
  expect(requests).toContainEqual([64, 32])

  // 三种视图都吃同一份累积结果：卡片视图能数出全部 90 张
  await page.getByRole("button", { name: "卡片" }).click()
  await expect(
    page.locator('[data-testid="library-card-grid"] > *'),
  ).toHaveCount(90)

  // 切到分页：回到「一页 32 条」，并出现页码跳转
  await page.getByRole("button", { name: "分页" }).click()
  await expect(page.getByText(/已加载/)).toHaveCount(0)
  await expect(page.getByLabel("跳到指定页码")).toBeVisible()
  await expect(
    page.locator('[data-testid="library-card-grid"] > *'),
  ).toHaveCount(32)
  await expect(page.getByText("作品 33")).toHaveCount(0)

  await page.getByRole("button", { name: "下一页" }).click()
  await expect(
    page.locator('[data-testid="library-card-grid"] > *'),
  ).toHaveCount(32)
  await expect(page.getByText("作品 33")).toBeVisible()
  await expect(page.getByText("作品 1", { exact: true })).toHaveCount(0)
  expect(requests).toContainEqual([32, 32])
})

test("task works panel scrolls to load more and can switch back to paging", async ({
  page,
}) => {
  const total = 45
  const requests: Array<[number, number]> = []
  await page.route(`**/api/v1/douyin/tasks/${taskId}**`, async (route) => {
    const url = new URL(route.request().url())
    const pathname = url.pathname
    if (pathname.endsWith("/works")) {
      const skip = Number(url.searchParams.get("skip") ?? 0)
      const limit = Number(url.searchParams.get("limit") ?? 20)
      requests.push([skip, limit])
      await route.fulfill({
        json: slice(total, { skip: String(skip), limit: String(limit) }),
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
          ...idleMediaMigration,
        },
      })
      return
    }
    if (
      pathname.endsWith("/media") ||
      pathname.endsWith("/awemes") ||
      pathname.endsWith("/interactions") ||
      pathname.endsWith("/shards")
    ) {
      await route.fulfill({ json: { data: [], count: 0 } })
      return
    }
    await route.fulfill({ json: makeTask() })
  })

  await page.goto(`/douyin/${taskId}`)
  await page.getByRole("tab", { name: /^作品数据/ }).click()

  // 默认滚动加载：任务作品数据一次拉 20 条，滚到底续拉
  await expect(page.getByText("当前结果 45 条")).toBeVisible()
  await expect(page.getByText("已加载 20 / 45")).toBeVisible()
  expect(requests).toContainEqual([0, 20])

  await loadUntilDone(page)
  expect(requests).toContainEqual([40, 20])

  // 切到分页：分页器回来，并只渲染当前页 20 行
  await page.getByRole("button", { name: "分页" }).click()
  await expect(page.getByText("共 45 项")).toBeVisible()
  await expect(page.getByText("作品 21", { exact: true })).toHaveCount(0)
  await page.getByRole("button", { name: "下一页" }).click()
  await expect(page.getByText("作品 21", { exact: true })).toBeVisible()
  expect(requests).toContainEqual([20, 20])
})
