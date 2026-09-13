import { expect, test } from "@playwright/test"

const checkedAt = new Date().toISOString()

/** 浏览器管理页的两个分栏共用同一份槽位数据，这里同时给出本机与云端槽位。 */
function browserSlots() {
  return {
    count: 4,
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
        active_page_title: "抖音首页",
        active_page_url: "https://www.douyin.com/",
        latency_ms: 12,
        checked_at: checkedAt,
        occupied_account_id: "c7e0bb1c-891a-4b4a-8f12-26c1ddd8239d",
        occupied_account_name: "本机大号",
      },
      {
        name: "local-2",
        browser_mode: "local",
        label: "本机浏览器 2",
        is_default: false,
        available: true,
        configured: true,
        cdp_endpoint: "127.0.0.1:9334",
        viewer_available: false,
        viewer_url: null,
        cdp_healthy: false,
        page_count: 0,
        active_page_title: null,
        active_page_url: null,
        latency_ms: null,
        checked_at: checkedAt,
        occupied_account_id: null,
        occupied_account_name: null,
      },
      {
        name: null,
        browser_mode: "remote",
        label: "云端默认槽位",
        is_default: true,
        available: false,
        configured: true,
        cdp_endpoint: "127.0.0.1:9222",
        viewer_available: true,
        viewer_url: "http://127.0.0.1:6081/vnc.html?autoconnect=1",
        cdp_healthy: true,
        page_count: 1,
        active_page_title: "抖音首页",
        active_page_url: "https://www.douyin.com/",
        latency_ms: 42,
        checked_at: checkedAt,
        occupied_account_id: "c7e0bb1c-891a-4b4a-8f12-26c1ddd8239e",
        occupied_account_name: "大号",
      },
      {
        name: "pool-1",
        browser_mode: "remote",
        label: "pool-1",
        is_default: false,
        available: true,
        configured: true,
        cdp_endpoint: "127.0.0.1:9224",
        viewer_available: true,
        viewer_url: "http://127.0.0.1:6082/vnc.html?autoconnect=1",
        cdp_healthy: true,
        page_count: 2,
        active_page_title: "抖音账号中心",
        active_page_url: "https://www.douyin.com/user/self",
        latency_ms: 35,
        checked_at: checkedAt,
        occupied_account_id: null,
        occupied_account_name: null,
      },
    ],
  }
}

test("管理页按本机与云端分栏，并可直接发起账号登录", async ({ page }) => {
  const loginCalls: string[] = []
  await page.route("**/api/v1/douyin/accounts/browser-slots", async (route) => {
    await route.fulfill({ json: browserSlots() })
  })
  await page.route("**/api/v1/douyin/accounts/by-id/*/login", async (route) => {
    loginCalls.push(route.request().url())
    await route.fulfill({
      status: 202,
      json: {
        account: {
          id: "c7e0bb1c-891a-4b4a-8f12-26c1ddd8239d",
          name: "本机大号",
          browser_mode: "local",
          slot: "local-1",
          status: "verifying",
          is_logged_in: true,
          weight: 1,
          priority: 0,
          concurrency_limit: 1,
          daily_task_limit: 100,
          tasks_today: 0,
          min_request_interval_seconds: 1,
          active_leases: 0,
          failure_streak: 0,
          cooldown_until: null,
          last_verified_at: checkedAt,
          last_used_at: null,
          last_error: null,
          enabled: true,
          created_at: checkedAt,
          updated_at: checkedAt,
        },
        status: "verifying",
        browser_mode: "local",
        viewer_url: null,
        expires_at: checkedAt,
        message: "浏览器已打开，请完成登录后点击验证登录",
      },
    })
  })
  for (const port of [6081, 6082]) {
    await page.route(`http://127.0.0.1:${port}/**`, async (route) => {
      await route.fulfill({ contentType: "text/html", body: "<p>noVNC</p>" })
    })
  }

  await page.goto("/douyin-browsers")

  // 页面语义是「管理」而不是「监控」
  await expect(page.getByRole("heading", { name: "浏览器管理" })).toBeVisible()
  await expect(page.getByText("浏览器监控", { exact: true })).toHaveCount(0)
  await expect(page.getByText("槽位 4", { exact: false })).toBeVisible()
  await expect(page.getByText("在线 3", { exact: false })).toBeVisible()
  await expect(page.getByText("已绑定 2", { exact: false })).toBeVisible()
  await expect(page.getByText("可绑定 2", { exact: false })).toBeVisible()

  const localTab = page.getByRole("tab", { name: /本机浏览器（2）/ })
  const remoteTab = page.getByRole("tab", { name: /云端浏览器（2）/ })
  await expect(localTab).toHaveAttribute("data-state", "active")

  // 默认落在本机分栏：本机槽位没有 noVNC 画面，但给出 CDP 端点与绑定账号
  const workspace = page.getByTestId("browser-monitor-workspace")
  await expect(workspace).toHaveAttribute("data-browser-mode", "local")
  await expect(workspace).toHaveClass(/xl:sticky/)
  await expect(page.getByTestId("browser-viewer-panel")).toHaveClass(
    /xl:h-full/,
  )
  await expect(page.getByTestId("browser-slot-list")).toHaveClass(
    /overflow-y-auto/,
  )
  await expect(page.getByTestId("browser-cdp-endpoint")).toContainText(
    "127.0.0.1:9333",
  )
  await expect(page.getByTestId("browser-slot-actions")).toContainText(
    "本机大号",
  )
  await expect(page.getByText("可绑定账号")).toBeVisible()
  await expect(
    page.getByText("本机浏览器没有远程画面", { exact: true }),
  ).toBeVisible()
  await expect(page.locator("iframe")).toHaveCount(0)

  // 管理动作：在该槽位绑定账号上直接发起登录
  await page.getByRole("button", { name: /登录该账号/ }).click()
  await expect.poll(() => loginCalls.length).toBe(1)
  expect(loginCalls[0]).toContain(
    "/douyin/accounts/by-id/c7e0bb1c-891a-4b4a-8f12-26c1ddd8239d/login",
  )

  // 切到云端分栏：出现 noVNC 实时画面与云端槽位的 CDP 端点
  await remoteTab.click()
  await expect(remoteTab).toHaveAttribute("data-state", "active")
  await expect(page.getByTestId("browser-monitor-workspace")).toHaveAttribute(
    "data-browser-mode",
    "remote",
  )
  await expect(page.getByTestId("browser-cdp-endpoint")).toContainText(
    "127.0.0.1:9222",
  )
  await expect(page.getByTestId("browser-active-page")).toContainText(
    "抖音首页",
  )
  await expect(
    page.locator('iframe[title="云端默认槽位 实时浏览器"]'),
  ).toBeVisible()

  // 选中态按分栏各自保留：云端切到 pool-1（未绑定 → 无登录按钮）
  const poolSlot = page.getByRole("button", { name: /pool-1/ })
  await expect(poolSlot).toHaveAttribute("aria-pressed", "false")
  await poolSlot.click()
  await expect(poolSlot).toHaveAttribute("aria-pressed", "true")
  await expect(page.locator('iframe[title="pool-1 实时浏览器"]')).toBeVisible()
  await expect(page.getByTestId("browser-cdp-endpoint")).toContainText(
    "127.0.0.1:9224",
  )
  await expect(page.getByRole("button", { name: /登录该账号/ })).toHaveCount(0)

  // 切回本机分栏：本机栏仍选着 local-1
  await localTab.click()
  await expect(
    page.getByRole("button", { name: /本机浏览器 1/ }),
  ).toHaveAttribute("aria-pressed", "true")
  await expect(page.getByTestId("browser-cdp-endpoint")).toContainText(
    "127.0.0.1:9333",
  )
})

test("没有本机槽位时回落到云端分栏并给出启用指引", async ({ page }) => {
  const slots = browserSlots()
  await page.route("**/api/v1/douyin/accounts/browser-slots", async (route) => {
    await route.fulfill({
      json: {
        count: 2,
        data: slots.data.filter((slot) => slot.browser_mode === "remote"),
      },
    })
  })
  await page.route("http://127.0.0.1:6081/**", async (route) => {
    await route.fulfill({ contentType: "text/html", body: "<p>noVNC</p>" })
  })

  await page.goto("/douyin-browsers")

  await expect(
    page.getByRole("tab", { name: /云端浏览器（2）/ }),
  ).toHaveAttribute("data-state", "active")
  await expect(page.getByTestId("browser-monitor-workspace")).toHaveAttribute(
    "data-browser-mode",
    "remote",
  )

  // 本机分栏空态给出可执行的启用指引
  await page.getByRole("tab", { name: /本机浏览器（0）/ }).click()
  await expect(page.getByText("尚未启用本机槽位")).toBeVisible()
  await expect(
    page.getByText("DOUYIN_LOCAL_CDP_SLOT_COUNT", { exact: false }),
  ).toBeVisible()
})
