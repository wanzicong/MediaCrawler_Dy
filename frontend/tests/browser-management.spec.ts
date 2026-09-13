import { expect, test } from "@playwright/test"

const checkedAt = new Date().toISOString()

const LOCAL_ACCOUNT_ID = "c7e0bb1c-891a-4b4a-8f12-26c1ddd8239d"
const REMOTE_ACCOUNT_ID = "c7e0bb1c-891a-4b4a-8f12-26c1ddd8239e"

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
        occupied_account_id: LOCAL_ACCOUNT_ID,
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
        occupied_account_id: REMOTE_ACCOUNT_ID,
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

test("浏览器管理以列表形式展示槽位，并支持登录与查看画面", async ({ page }) => {
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
          id: LOCAL_ACCOUNT_ID,
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

  // 页面语义是「管理」，概览用统计行表达
  await expect(page.getByRole("heading", { name: "浏览器管理" })).toBeVisible()
  await expect(page.getByText("浏览器监控", { exact: true })).toHaveCount(0)
  await expect(page.getByText("槽位 4", { exact: false })).toBeVisible()
  await expect(page.getByText("在线 3", { exact: false })).toBeVisible()
  await expect(page.getByText("已绑定 2", { exact: false })).toBeVisible()
  await expect(page.getByText("可绑定 2", { exact: false })).toBeVisible()

  const localTab = page.getByRole("tab", { name: /本机浏览器（2）/ })
  const remoteTab = page.getByRole("tab", { name: /云端浏览器（2）/ })
  await expect(localTab).toHaveAttribute("data-state", "active")

  // 本机分栏：一行一个槽位；默认隐藏「当前活动页面」「探测延迟」两列
  const table = page.getByTestId("browser-slot-table")
  await expect(table).toHaveAttribute("data-browser-mode", "local")
  expect(await page.getByRole("columnheader").allTextContents()).toEqual([
    "连接状态",
    "槽位",
    "CDP 端点",
    "绑定账号",
    "页面数",
    "最近探测",
    "操作",
  ])

  const boundRow = page.getByRole("row", { name: /本机浏览器 1/ })
  await expect(boundRow).toContainText("在线")
  await expect(boundRow).toContainText("127.0.0.1:9333")
  await expect(boundRow).toContainText("本机大号")
  await expect(boundRow).toContainText("1 页")
  await expect(
    boundRow.getByRole("button", { name: /登录该账号/ }),
  ).toBeVisible()

  const freeRow = page.getByRole("row", { name: /本机浏览器 2/ })
  await expect(freeRow).toContainText("离线")
  await expect(freeRow).toContainText("可绑定")
  await expect(freeRow.getByRole("button", { name: /登录该账号/ })).toHaveCount(
    0,
  )

  // 列设置：把默认隐藏的「当前活动页面」打开
  await page.getByRole("button", { name: /设置显示的列/ }).click()
  await page.getByRole("menuitemcheckbox", { name: "当前活动页面" }).click()
  await page.keyboard.press("Escape")
  await expect(
    page.getByRole("columnheader", { name: "当前活动页面" }),
  ).toBeVisible()
  await expect(page.getByTestId("browser-active-page").first()).toContainText(
    "抖音首页",
  )

  // 管理动作：在该槽位绑定账号上直接发起登录
  await boundRow.getByRole("button", { name: /登录该账号/ }).click()
  await expect.poll(() => loginCalls.length).toBe(1)
  expect(loginCalls[0]).toContain(
    `/douyin/accounts/by-id/${LOCAL_ACCOUNT_ID}/login`,
  )

  // 云端分栏：云端槽位提供「查看画面」，在对话框里嵌入 noVNC
  await remoteTab.click()
  await expect(remoteTab).toHaveAttribute("data-state", "active")
  await expect(page.getByTestId("browser-slot-table")).toHaveAttribute(
    "data-browser-mode",
    "remote",
  )

  const defaultRow = page.getByRole("row", { name: /云端默认槽位/ })
  await expect(defaultRow).toContainText("默认")
  await expect(defaultRow).toContainText("127.0.0.1:9222")
  await defaultRow.getByRole("button", { name: /查看画面/ }).click()
  await expect(page.getByTestId("browser-viewer-dialog")).toBeVisible()
  await expect(
    page.locator('iframe[title="云端默认槽位 实时浏览器"]'),
  ).toBeVisible()
  // 画面是 iframe，按键会被嵌页吞掉，这里用对话框自带的关闭按钮
  await page
    .getByTestId("browser-viewer-dialog")
    .getByRole("button", { name: "关闭" })
    .click()
  await expect(page.getByTestId("browser-viewer-dialog")).toHaveCount(0)

  // 未绑定账号的槽位只提供「查看画面」，没有登录入口
  const poolRow = page.getByRole("row", { name: /pool-1/ })
  await expect(poolRow).toContainText("可绑定")
  await expect(poolRow.getByRole("button", { name: /登录该账号/ })).toHaveCount(
    0,
  )
  await expect(poolRow.getByRole("button", { name: /查看画面/ })).toBeVisible()
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
  await expect(page.getByTestId("browser-slot-table")).toHaveAttribute(
    "data-browser-mode",
    "remote",
  )

  // 本机分栏空态（表格内一行）给出可执行的启用指引
  await page.getByRole("tab", { name: /本机浏览器（0）/ }).click()
  await expect(page.getByText("尚未启用本机槽位")).toBeVisible()
  await expect(
    page.getByText("DOUYIN_LOCAL_CDP_SLOT_COUNT", { exact: false }),
  ).toBeVisible()
})
