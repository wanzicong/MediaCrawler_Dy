import { expect, test } from "@playwright/test"

const checkedAt = new Date().toISOString()

/** 监控中心的两个分栏共用同一份槽位数据，这里同时给出本机与云端槽位。 */
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
        available: false,
        configured: true,
        viewer_available: true,
        viewer_url: "http://127.0.0.1:6082/vnc.html?autoconnect=1",
        cdp_healthy: true,
        page_count: 2,
        active_page_title: "抖音账号中心",
        active_page_url: "https://www.douyin.com/user/self",
        latency_ms: 35,
        checked_at: checkedAt,
        occupied_account_id: "c7e0bb1c-891a-4b4a-8f12-26c1ddd8249f",
        occupied_account_name: "小号",
      },
    ],
  }
}

test("splits local and remote slots into their own tabs", async ({ page }) => {
  await page.route("**/api/v1/douyin/accounts/browser-slots", async (route) => {
    await route.fulfill({ json: browserSlots() })
  })
  for (const port of [6081, 6082]) {
    await page.route(`http://127.0.0.1:${port}/**`, async (route) => {
      await route.fulfill({ contentType: "text/html", body: "<p>noVNC</p>" })
    })
  }

  await page.goto("/douyin-browsers")

  // 旧版单列表文案不应再出现
  await expect(page.getByText("常驻浏览器", { exact: true })).toHaveCount(0)
  await expect(page.getByText("连接状态", { exact: true })).toHaveCount(0)

  const localTab = page.getByRole("tab", { name: /本机浏览器（2）/ })
  const remoteTab = page.getByRole("tab", { name: /云端浏览器（2）/ })
  await expect(localTab).toBeVisible()
  await expect(remoteTab).toBeVisible()

  // 默认落在本机分栏：槽位列表只含本机槽位，云端的 noVNC 画面不出现
  await expect(localTab).toHaveAttribute("data-state", "active")
  const localWorkspace = page.getByTestId("browser-monitor-workspace")
  await expect(localWorkspace).toHaveAttribute("data-browser-mode", "local")
  await expect(localWorkspace).toHaveClass(/xl:sticky/)
  await expect(page.getByTestId("browser-viewer-panel")).toHaveClass(
    /xl:h-full/,
  )
  await expect(page.getByTestId("browser-slot-list")).toHaveClass(
    /overflow-y-auto/,
  )
  await expect(page.getByText("共 2 个 · 1 个在线")).toBeVisible()
  await expect(page.getByRole("button", { name: /本机浏览器 1/ })).toBeVisible()
  await expect(page.getByRole("button", { name: /pool-1/ })).toHaveCount(0)
  await expect(
    page.getByText("本机浏览器没有远程画面", { exact: true }),
  ).toBeVisible()
  await expect(page.locator("iframe")).toHaveCount(0)

  // 切到云端分栏：列表换成云端槽位，出现 noVNC 实时画面
  await remoteTab.click()
  await expect(remoteTab).toHaveAttribute("data-state", "active")
  await expect(page.getByTestId("browser-monitor-workspace")).toHaveAttribute(
    "data-browser-mode",
    "remote",
  )
  await expect(page.getByText("共 2 个 · 2 个在线")).toBeVisible()
  await expect(page.getByRole("button", { name: /pool-1/ })).toBeVisible()
  await expect(page.getByRole("button", { name: /本机浏览器 1/ })).toHaveCount(
    0,
  )
  await expect(page.getByTestId("browser-active-page")).toContainText(
    "抖音首页",
  )
  await expect(
    page.locator('iframe[title="云端默认槽位 实时浏览器"]'),
  ).toBeVisible()

  // 选中态按分栏各自保留：云端切到 pool-1
  const poolSlot = page.getByRole("button", { name: /pool-1/ })
  await expect(poolSlot).toHaveAttribute("aria-pressed", "false")
  await poolSlot.click()
  await expect(poolSlot).toHaveAttribute("aria-pressed", "true")
  await expect(page.locator('iframe[title="pool-1 实时浏览器"]')).toBeVisible()
  await expect(page.getByTestId("browser-active-page")).toContainText(
    "抖音账号中心",
  )

  // 切回本机分栏：本机栏仍选着 local-1，不会沿用云端的选中项
  await localTab.click()
  await expect(
    page.getByRole("button", { name: /本机浏览器 1/ }),
  ).toHaveAttribute("aria-pressed", "true")
  await expect(page.getByTestId("browser-active-page")).toContainText(
    "抖音首页",
  )
})

test("falls back to the remote tab when no local slot is configured", async ({
  page,
}) => {
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
