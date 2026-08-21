import { expect, test } from "@playwright/test"

const navigationLayoutKey = "media-crawler-navigation-layout"

test.beforeEach(async ({ page }) => {
  await page.addInitScript(
    (key) => window.localStorage.removeItem(key),
    navigationLayoutKey,
  )
})

test("uses direct horizontal module and page navigation by default", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto("/douyin-accounts")

  const navigation = page.getByTestId("horizontal-navigation")
  await expect(navigation).toBeVisible()
  await expect(page.getByTestId("page-content-container")).toHaveClass(
    /max-w-none/,
  )
  await expect(
    page.getByTestId("horizontal-module-operations"),
  ).toHaveAttribute("data-active", "true")
  await expect(
    navigation.getByRole("link", { name: "账号池", exact: true }),
  ).toHaveAttribute("aria-current", "page")
  await expect(
    navigation.getByRole("link", { name: "请求日志", exact: true }),
  ).toBeVisible()

  await page.getByTestId("horizontal-module-content").click()

  await expect(page).toHaveURL(/\/douyin-library$/)
  await expect(
    navigation.getByRole("link", { name: "评论管理", exact: true }),
  ).toBeVisible()
})

test("switches to sidebar navigation and remembers the layout", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto("/douyin")

  await page.getByRole("button", { name: "使用侧边导航" }).click()
  await expect(page.getByTestId("horizontal-navigation")).toHaveCount(0)
  await expect(page.getByTestId("page-content-container")).toHaveClass(
    /max-w-\[1600px\]/,
  )
  await expect(page.getByRole("link", { name: "赛道管理" })).toBeVisible()

  await page.reload()

  await expect(page.getByTestId("horizontal-navigation")).toHaveCount(0)
  await expect(
    page.getByRole("button", { name: "使用侧边导航" }),
  ).toHaveAttribute("aria-pressed", "true")

  await page.getByRole("button", { name: "使用横向导航" }).click()
  await expect(page.getByTestId("horizontal-navigation")).toBeVisible()
})
