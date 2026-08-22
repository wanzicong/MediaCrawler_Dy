import { expect, test } from "@playwright/test"

test("keeps browser controls fixed and switches the selected slot", async ({
  page,
}) => {
  await page.route("**/api/v1/douyin/accounts/browser-slots", async (route) => {
    const checkedAt = new Date().toISOString()
    await route.fulfill({
      json: {
        count: 2,
        data: [
          {
            name: null,
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
            occupied_account_id: "c7e0bb1c-891a-4b4a-8f12-26c1ddd8239d",
            occupied_account_name: "大号",
          },
          {
            name: "pool-1",
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
            occupied_account_id: "c7e0bb1c-891a-4b4a-8f12-26c1ddd8239e",
            occupied_account_name: "小号",
          },
        ],
      },
    })
  })
  for (const port of [6081, 6082]) {
    await page.route(`http://127.0.0.1:${port}/**`, async (route) => {
      await route.fulfill({ contentType: "text/html", body: "<p>noVNC</p>" })
    })
  }

  await page.goto("/douyin-browsers")

  await expect(page.getByText("常驻浏览器", { exact: true })).toHaveCount(0)
  await expect(page.getByText("连接状态", { exact: true })).toHaveCount(0)
  await expect(page.getByText("已绑定账号", { exact: true })).toHaveCount(0)
  await expect(page.getByText("活动页面", { exact: true })).toHaveCount(0)
  await expect(page.getByTestId("browser-monitor-workspace")).toHaveClass(
    /xl:sticky/,
  )
  await expect(page.getByTestId("browser-viewer-panel")).toHaveClass(
    /xl:h-full/,
  )
  await expect(page.getByTestId("browser-slot-list")).toHaveClass(
    /overflow-y-auto/,
  )
  await expect(page.getByTestId("browser-active-page")).toContainText(
    "抖音首页",
  )
  await expect(
    page.locator('iframe[title="云端默认槽位 实时浏览器"]'),
  ).toBeVisible()

  const poolSlot = page.getByRole("button", { name: /pool-1/ })
  await expect(poolSlot).toHaveAttribute("aria-pressed", "false")
  await poolSlot.click()

  await expect(poolSlot).toHaveAttribute("aria-pressed", "true")
  await expect(page.locator('iframe[title="pool-1 实时浏览器"]')).toBeVisible()
  await expect(page.getByTestId("browser-active-page")).toContainText(
    "抖音账号中心",
  )
})
