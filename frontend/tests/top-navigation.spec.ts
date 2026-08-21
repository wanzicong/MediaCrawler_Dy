import { expect, test } from "@playwright/test"

test("switches between feature modules from the desktop top navigation", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto("/douyin")

  const navigation = page.getByTestId("top-module-navigation")
  await expect(navigation).toBeVisible()

  await page.getByTestId("top-module-trigger-content").click()
  const libraryLink = page.getByRole("menuitem", { name: "视频资源库" })
  await expect(libraryLink).toBeVisible()
  await libraryLink.click()

  await expect(page).toHaveURL(/\/douyin-library$/)
  await expect(
    navigation.getByRole("button", { name: /内容资产/ }),
  ).toHaveClass(/text-primary/)
})

test("uses one grouped module menu on a narrow screen", async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 800 })
  await page.goto("/douyin-comments")

  const compactTrigger = page.getByTestId("top-module-compact-trigger")
  await expect(compactTrigger).toBeVisible()
  await expect(compactTrigger).toContainText("内容资产")
  await compactTrigger.click()

  await expect(page.getByRole("menuitem", { name: "抖音任务" })).toBeVisible()
  await expect(
    page.getByRole("menuitem", { name: "评论管理" }),
  ).toHaveAttribute("aria-current", "page")
  await page.getByRole("menuitem", { name: "抖音任务" }).click()
  await expect(page).toHaveURL(/\/douyin$/)
})
