import { expect, type Page } from "@playwright/test"

export async function signUpNewUser(
  page: Page,
  name: string,
  email: string,
  password: string,
) {
  await page.goto("/signup")

  await page.getByTestId("full-name-input").fill(name)
  await page.getByTestId("email-input").fill(email)
  await page.getByTestId("password-input").fill(password)
  await page.getByTestId("confirm-password-input").fill(password)
  await page.getByRole("button", { name: "注册" }).click()
  await page.goto("/login")
}

export async function logInUser(page: Page, email: string, password: string) {
  await page.goto("/login")

  await page.getByTestId("email-input").fill(email)
  await page.getByTestId("password-input").fill(password)
  await page.getByRole("button", { name: "登录" }).click()
  await page.waitForURL("/")
  await expect(
    page.getByRole("heading", { name: /欢迎回来|你好，/ }),
  ).toBeVisible()
}

export async function logOutUser(page: Page) {
  const userMenu = page.locator('[data-testid="user-menu"]:visible')
  const openMenu = page.locator(
    '[data-slot="dropdown-menu-content"][data-state="open"]',
  )

  if ((await openMenu.count()) === 0) {
    await expect(userMenu).toHaveCount(1)
    await expect(userMenu).toHaveAttribute("aria-expanded", "false")
    await expect(
      page.locator('[data-slot="dropdown-menu-content"][data-state="closed"]'),
    ).toHaveCount(0)
    await userMenu.click()
    await expect(openMenu).toHaveCount(1)
  }

  const logoutItem = openMenu.getByRole("menuitem", { name: "退出登录" })
  await expect(logoutItem).toBeVisible()
  await logoutItem.click()
  await page.waitForURL("/login")
}
