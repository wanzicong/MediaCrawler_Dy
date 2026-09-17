import { expect, test } from "@playwright/test"

/**
 * 任务列表聚合（任务 + 内容）与分页。
 *
 * 背景：同一条赛道、同一采集类型、同一批目标内容会反复跑，逐条列出时
 * 重复任务把列表撑满，用户看不出「跑了几次、一共采到多少」。
 */
const now = new Date()
const iso = (minutesAgo: number) =>
  new Date(now.getTime() - minutesAgo * 60_000).toISOString()

function makeTask({
  id,
  keyword,
  trackId,
  trackName,
  minutesAgo,
  awemeCount,
  commentCount,
}: {
  id: string
  keyword: string
  trackId: string
  trackName: string
  minutesAgo: number
  awemeCount: number
  commentCount: number
}) {
  return {
    id,
    owner_id: "c7e0bb1c-891a-4b4a-8f12-26c1ddd8239d",
    track_id: trackId,
    track_name: trackName,
    track_is_default: false,
    account_id: null,
    account_name: null,
    account_pool_id: null,
    account_pool_name: null,
    account_strategy: "least_loaded",
    crawl_type: "search",
    status: "succeeded",
    request: { keywords: [keyword], browser_mode: "remote" },
    display_title: null,
    display_author: null,
    creator_names: [],
    source_type: "keyword",
    source_names: [keyword],
    source_label: `关键词：${keyword}`,
    display_aweme_id: null,
    aweme_count: awemeCount,
    comment_count: commentCount,
    action_count: 0,
    checkpoint_phase: "completed",
    resume_count: 0,
    can_resume_crawl: false,
    can_resume_media: false,
    error: null,
    has_qrcode: false,
    created_at: iso(minutesAgo),
    started_at: iso(minutesAgo),
    finished_at: iso(minutesAgo),
    last_resumed_at: null,
  }
}

test("aggregates the task list by task + content with pagination", async ({
  page,
}) => {
  const trackId = "00d5dae3-5481-4a36-ac38-e91a7abcee51"
  const tasks: ReturnType<typeof makeTask>[] = []
  // 6 组 × 4 次运行 = 24 条任务；默认每页 10 组
  for (let group = 0; group < 6; group += 1) {
    for (let run = 0; run < 4; run += 1) {
      tasks.push(
        makeTask({
          id: `10000000-0000-4000-8000-${String(group * 10 + run).padStart(12, "0")}`,
          keyword: `关键词${group}`,
          trackId,
          trackName: "聚合赛道",
          minutesAgo: group * 10 + run,
          awemeCount: 2,
          commentCount: 3,
        }),
      )
    }
  }

  await page.route("**/api/v1/douyin/tracks?**", async (route) => {
    await route.fulfill({
      json: {
        count: 1,
        data: [
          {
            id: trackId,
            name: "聚合赛道",
            description: "",
            is_default: false,
            enabled: true,
            keyword_count: 6,
            creator_count: 0,
            task_count: tasks.length,
            aweme_count: 48,
            comment_count: 72,
            running_task_count: 0,
            failed_task_count: 0,
            created_at: now.toISOString(),
            updated_at: now.toISOString(),
          },
        ],
      },
    })
  })
  await page.route("**/api/v1/douyin/accounts?**", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })
  await page.route("**/api/v1/douyin/accounts/pools**", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })
  await page.route("**/api/v1/douyin/tasks?**", async (route) => {
    await route.fulfill({ json: { count: tasks.length, data: tasks } })
  })

  await page.goto("/douyin")

  // 默认就是聚合视图：24 条任务收敛成 6 组
  await expect(page.getByText("共 6 组（24 个任务）")).toBeVisible()
  const aggregatedRows = page.locator("tbody tr").filter({ hasText: "关键词" })
  await expect(aggregatedRows).toHaveCount(6)

  // 每组 4 次运行、作品 8、评论 12
  const firstRow = aggregatedRows.first()
  await expect(firstRow).toContainText("4")
  await expect(firstRow).toContainText("作品")
  await expect(firstRow).toContainText("8")
  await expect(firstRow).toContainText("12")

  // 展开一组可以看到组内每次运行
  await firstRow.getByRole("button", { expanded: false }).click()
  await expect(page.getByText("组内运行记录（4 次，最近在前）")).toBeVisible()

  // 切到逐条：恢复成一行一条任务，并同样有分页
  await page.getByRole("button", { name: "逐条", exact: true }).click()
  await expect(page.getByText(/共 24 个任务/)).toBeVisible()
  await expect(page.locator("tbody tr")).toHaveCount(10)
  await page.getByRole("button", { name: "下一页" }).click()
  await expect(page.locator("tbody tr")).toHaveCount(10)

  // 切回聚合：分组展示保持不变
  await page.getByRole("button", { name: "聚合", exact: true }).click()
  await expect(page.getByText("共 6 组（24 个任务）")).toBeVisible()
})
