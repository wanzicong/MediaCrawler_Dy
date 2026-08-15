import { expect, test } from "@playwright/test"

test("shows the product brand mark in the application shell", async ({
  page,
}) => {
  await page.goto("/")

  const homeLink = page.getByRole("link", { name: /灵感采集台/ }).first()
  await expect(homeLink).toBeVisible()
  await expect(
    homeLink.locator('svg[viewBox="0 0 64 64"]:visible'),
  ).toBeVisible()
  await expect(page.locator('link[rel="icon"]')).toHaveAttribute(
    "href",
    "/assets/images/brand-mark.svg",
  )
})

test("separates collection workflows from content assets in the sidebar", async ({
  page,
}) => {
  await page.goto("/")

  const overview = page.getByTestId("sidebar-group-overview")
  const collection = page.getByTestId("sidebar-group-collection")
  await expect(overview.getByText("概览", { exact: true })).toBeVisible()
  await expect(overview.getByRole("link", { name: "工作台" })).toBeVisible()
  await expect(overview).toHaveJSProperty("previousElementSibling", null)
  await expect(collection.getByText("采集", { exact: true })).toBeVisible()
  await expect(
    collection.getByText("任务与策略", { exact: true }),
  ).toBeVisible()
  await expect(collection.getByRole("link").first()).toHaveAccessibleName(
    "赛道管理",
  )
  await expect(collection.getByRole("link", { name: "抖音任务" })).toBeVisible()
  await expect(collection.getByRole("link", { name: "赛道管理" })).toBeVisible()
  await expect(
    collection.getByRole("link", { name: "关键词管理" }),
  ).toBeVisible()
  await expect(
    collection.getByRole("link", { name: "视频资源库" }),
  ).toHaveCount(0)

  const content = page.getByTestId("sidebar-group-content")
  await expect(content.getByText("内容", { exact: true })).toBeVisible()
  await expect(content.getByText("资产与数据", { exact: true })).toBeVisible()
  await expect(content.getByRole("link", { name: "视频资源库" })).toBeVisible()
  await expect(content.getByRole("link", { name: "评论管理" })).toBeVisible()
  await expect(content.getByRole("link", { name: "标签管理" })).toBeVisible()
  await expect(content.getByRole("link", { name: "抖音任务" })).toHaveCount(0)
})

test("mobile navigation trigger announces its current state", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto("/")

  const trigger = page.locator('[data-sidebar="trigger"]')
  await expect(trigger).toHaveAccessibleName("打开导航")
  await expect(trigger).toHaveAttribute("aria-expanded", "false")
  await trigger.click()

  await expect(trigger).toHaveAttribute("aria-expanded", "true")
  await expect(trigger).toHaveAttribute("aria-label", "收起导航")
  await expect(trigger.getByText("收起导航")).toBeAttached()
  await expect(page.getByText("在移动设备上显示主要导航。")).toBeAttached()
  await expect(page.getByRole("link", { name: "工作台" })).toBeVisible()

  await page.keyboard.press("Escape")
  await expect(page.getByRole("button", { name: "打开导航" })).toHaveAttribute(
    "aria-expanded",
    "false",
  )
})

test("shows the same brand mark on the login page", async ({ browser }) => {
  const context = await browser.newContext({
    storageState: { cookies: [], origins: [] },
    viewport: { width: 1440, height: 900 },
  })
  const page = await context.newPage()

  await page.goto("/login")
  await expect(page.getByText("灵感采集台", { exact: true })).toBeVisible()
  await expect(page.locator('svg[viewBox="0 0 64 64"]')).toBeVisible()
  await expect(page).toHaveTitle("登录 - 灵感采集台")

  await context.close()
})

test("unknown routes use a productized Chinese empty page", async ({
  page,
}) => {
  await page.goto("/this-page-does-not-exist")

  await expect(page.getByTestId("not-found")).toBeVisible()
  await expect(page.getByRole("heading", { name: "页面不存在" })).toBeVisible()
  await expect(page.getByRole("link", { name: "返回工作台" })).toBeVisible()
})
