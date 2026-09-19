import { expect, test } from "@playwright/test"

/**
 * 账号管理：重命名。
 *
 * 背景：账号名称原本只能删号重建，而重建会连带清掉槽位里的登录态，
 * 用户看到的是「明明登录了却丢失登录状态」。现在支持就地改名。
 */
test("renames a managed account without touching its slot", async ({
  page,
}) => {
  const now = new Date().toISOString()
  const accountId = "318a8148-c8b6-4c6c-b7c4-93580d687300"
  let accountName = "顶顶顶"
  let patchedBody: Record<string, unknown> = {}

  const accountPayload = () => ({
    id: accountId,
    name: accountName,
    browser_mode: "local",
    slot: "local-1",
    status: "ready",
    is_logged_in: true,
    weight: 1,
    priority: 0,
    concurrency_limit: 1,
    daily_task_limit: 100,
    tasks_today: 0,
    min_request_interval_seconds: 3,
    active_leases: 0,
    failure_streak: 0,
    cooldown_until: null,
    last_verified_at: now,
    last_used_at: null,
    last_error: null,
    enabled: true,
    created_at: now,
    updated_at: now,
  })

  await page.route("**/api/v1/douyin/accounts/pools**", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })
  await page.route(
    "**/api/v1/douyin/accounts/browser-slots**",
    async (route) => {
      await route.fulfill({
        json: {
          count: 1,
          data: [
            {
              name: "local-1",
              browser_mode: "local",
              label: "本机浏览器 1",
              is_default: false,
              available: false,
              configured: true,
              cdp_endpoint: "127.0.0.1:9333",
              viewer_available: false,
              viewer_url: null,
              cdp_healthy: true,
              page_count: 1,
              active_page_title: null,
              active_page_url: null,
              latency_ms: 5,
              checked_at: now,
              occupied_account_id: accountId,
              occupied_account_name: accountName,
            },
          ],
        },
      })
    },
  )
  await page.route("**/api/v1/douyin/accounts/by-id/**", async (route) => {
    patchedBody = route.request().postDataJSON() as Record<string, unknown>
    accountName = String(patchedBody.name)
    await route.fulfill({ json: accountPayload() })
  })
  await page.route("**/api/v1/douyin/accounts**", async (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    const pathname = new URL(route.request().url()).pathname
    // 只兜住账号列表：槽位/账号池各有自己的路由，别被这条通用规则吃掉
    if (!pathname.endsWith("/accounts")) return route.fallback()
    await route.fulfill({ json: { data: [accountPayload()], count: 1 } })
  })
  await page.route("**/api/v1/douyin/tracks?**", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })
  await page.route(
    "**/api/v1/douyin/accounts/by-id/*/verify",
    async (route) => {
      await route.fulfill({ json: accountPayload() })
    },
  )

  await page.goto("/douyin-accounts")
  await expect(page.getByText("顶顶顶", { exact: true })).toBeVisible()

  await page.getByRole("button", { name: "更多账号操作" }).first().click()
  await page.getByRole("menuitem", { name: "重命名" }).click()
  await expect(
    page.getByRole("heading", { name: "修改账号名称" }),
  ).toBeVisible()
  // 弹窗里预填当前名称，改完保存只提交 name，不带槽位等字段
  const nameInput = page.getByRole("textbox", { name: "账号名称" })
  await expect(nameInput).toHaveValue("顶顶顶")
  await nameInput.fill("顶顶顶（主号）")
  await page.getByRole("button", { name: "保存" }).click()

  await expect(page.getByText("账号名称已更新")).toBeVisible()
  expect(patchedBody).toEqual({ name: "顶顶顶（主号）" })
  await expect(page.getByText("顶顶顶（主号）", { exact: true })).toBeVisible()
})
