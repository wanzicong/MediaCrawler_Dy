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
