import { expect, test } from "@playwright/test"

test("shows a compact task list with track, target and account first", async ({
  page,
}) => {
  const now = new Date().toISOString()
  const trackId = "00d5dae3-5481-4a36-ac38-e91a7abcee51"

  await page.route("**/api/v1/douyin/tracks?**", async (route) => {
    await route.fulfill({
      json: {
        count: 1,
        data: [
          {
            id: trackId,
            name: "S粉丝管理",
            description: "",
            is_default: false,
            enabled: true,
            keyword_count: 0,
            creator_count: 0,
            task_count: 1,
            aweme_count: 1,
            comment_count: 1,
            running_task_count: 0,
            failed_task_count: 0,
            created_at: now,
            updated_at: now,
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
    await route.fulfill({
      json: {
        count: 1,
        data: [
          {
            id: "18ead600-0000-4000-8000-000000000001",
            owner_id: "c7e0bb1c-891a-4b4a-8f12-26c1ddd8239d",
            track_id: trackId,
            track_name: "S粉丝管理",
            track_is_default: false,
            account_id: "c7e0bb1c-891a-4b4a-8f12-26c1ddd8239e",
            account_name: "小虎老师",
            account_pool_id: null,
            account_pool_name: null,
            account_strategy: "least_loaded",
            crawl_type: "detail",
            status: "succeeded",
            request: {
              browser_mode: "remote",
              video_ids: ["7671284134611116154"],
            },
            display_title: "付费进群系统搭建",
            display_author: "小虎老师",
            display_aweme_id: "7671284134611116154",
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
          },
        ],
      },
    })
  })

  await page.goto("/douyin")
  await page.getByRole("button", { name: "表格" }).click()

  const headers = await page.getByRole("columnheader").allTextContents()
  expect(headers.slice(0, 4)).toEqual(["所属赛道", "任务目标", "状态", "账号"])

  const row = page.getByRole("row").filter({ hasText: "付费进群系统搭建" })
  const cells = row.getByRole("cell")
  await expect(cells.nth(0)).toContainText("S粉丝管理")
  await expect(cells.nth(1).locator("p")).toHaveText(
    "【指定作品】付费进群系统搭建",
  )
  await expect(cells.nth(3)).toContainText("小虎老师（云端浏览器）")
  await expect(row.getByText(/任务 #/)).toHaveCount(0)

  const pageStack = page.locator(".page-stack")
  const taskTable = page.getByRole("table")
  const [pageStackBox, tableBox] = await Promise.all([
    pageStack.boundingBox(),
    taskTable.boundingBox(),
  ])
  expect(pageStackBox).not.toBeNull()
  expect(tableBox).not.toBeNull()
  expect((tableBox?.y ?? 0) - (pageStackBox?.y ?? 0)).toBeLessThan(270)
  await expect(page.getByText("数据每 3 秒自动刷新")).toHaveCount(0)
})
