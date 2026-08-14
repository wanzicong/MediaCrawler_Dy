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

  const collection = page.getByTestId("sidebar-group-collection")
  await expect(collection.getByText("采集", { exact: true })).toBeVisible()
  await expect(collection.getByText("任务与策略", { exact: true })).toBeVisible()
  await expect(collection.getByRole("link", { name: "抖音任务" })).toBeVisible()
  await expect(collection.getByRole("link", { name: "赛道管理" })).toBeVisible()
  await expect(
    collection.getByRole("link", { name: "关键词管理" }),
  ).toBeVisible()
  await expect(collection.getByRole("link", { name: "视频资源库" })).toHaveCount(
    0,
  )

  const content = page.getByTestId("sidebar-group-content")
  await expect(content.getByText("内容", { exact: true })).toBeVisible()
  await expect(content.getByText("资产与数据", { exact: true })).toBeVisible()
  await expect(content.getByRole("link", { name: "视频资源库" })).toBeVisible()
  await expect(content.getByRole("link", { name: "评论管理" })).toBeVisible()
  await expect(content.getByRole("link", { name: "标签管理" })).toBeVisible()
  await expect(content.getByRole("link", { name: "抖音任务" })).toHaveCount(0)
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
