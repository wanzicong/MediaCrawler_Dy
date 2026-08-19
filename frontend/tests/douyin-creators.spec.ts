import { expect, test } from "@playwright/test"

test("creator directory aggregates authors and links into the video library", async ({
  page,
}) => {
  let requestedTrack = "unset"
  await page.route("**/api/v1/douyin/tracks**", async (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    await route.fulfill({
      json: {
        data: [
          {
            id: "track-1",
            name: "私域增长",
            description: "",
            enabled: true,
            keyword_count: 3,
            enabled_keyword_count: 3,
            task_count: 2,
            active_task_count: 0,
            aweme_count: 40,
            comment_count: 12,
            last_task_id: null,
            last_task_status: null,
            last_task_created_at: null,
            is_default: false,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
        ],
        count: 1,
      },
    })
  })
  await page.route("**/api/v1/douyin/library/creators**", async (route) => {
    requestedTrack =
      new URL(route.request().url()).searchParams.get("track_id") ?? ""
    await route.fulfill({
      json: {
        count: 3,
        data: [
          { creator_hash: "hash-b", nickname: "带货小王子", work_count: 2 },
          { creator_hash: "hash-a", nickname: "露营达人", work_count: 18 },
          { creator_hash: "hash-c", nickname: "私域老司机", work_count: 7 },
        ],
      },
    })
  })

  await page.goto("/douyin-creators")
  await expect(page.getByRole("heading", { name: "达人列表" })).toBeVisible()
  await expect.poll(() => requestedTrack).toBe("")

  // 默认按作品数从多到少排序
  const names = page.locator("p.truncate.font-medium[title]")
  await expect(names.nth(0)).toHaveText("露营达人")
  await expect(names.nth(1)).toHaveText("私域老司机")
  await expect(names.nth(2)).toHaveText("带货小王子")
  await expect(page.getByText("已爬取 18 个作品")).toBeVisible()
  await expect(
    page.locator("[data-slot=avatar-fallback]", { hasText: "露" }),
  ).toBeVisible()

  // 昵称搜索过滤
  await page.getByPlaceholder("搜索达人昵称").fill("私域")
  await expect(names).toHaveCount(1)
  await expect(names.nth(0)).toHaveText("私域老司机")
  await page.getByPlaceholder("搜索达人昵称").fill("")
  await expect(names).toHaveCount(3)

  // 切换昵称排序
  await page.getByLabel("达人排序方式").click()
  await page.getByRole("option", { name: "昵称 A → Z" }).click()
  await expect(names.nth(0)).toHaveText("带货小王子")

  // 按赛道筛选会把 track_id 带给后端
  await page.getByLabel("按赛道筛选达人").click()
  await page.getByRole("option", { name: /私域增长/ }).click()
  await expect.poll(() => requestedTrack).toBe("track-1")

  // 达人卡片直达视频资源库并带上创作者过滤
  await expect(
    page.getByRole("link", { name: "查看 露营达人 的作品" }),
  ).toHaveAttribute("href", /\/douyin-library\?creator=hash-a/)
})
