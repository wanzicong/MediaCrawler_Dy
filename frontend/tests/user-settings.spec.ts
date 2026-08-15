import { expect, type Page, test } from "@playwright/test"
import { firstSuperuser, firstSuperuserPassword } from "./config.ts"
import { createUser } from "./utils/privateApi.ts"
import { randomEmail, randomPassword } from "./utils/random"
import { logInUser, logOutUser } from "./utils/user"

const tabs = ["个人资料", "登录密码", "危险操作"]

async function openAppearanceMenu(page: Page) {
  const openMenu = page.locator(
    '[data-slot="dropdown-menu-content"][data-state="open"]',
  )
  if ((await openMenu.count()) === 0) {
    const visibleUserMenu = page.locator('[data-testid="user-menu"]:visible')
    const viewport = page.viewportSize()
    if (
      viewport &&
      viewport.width < 768 &&
      (await visibleUserMenu.count()) === 0
    ) {
      const openNavigation = page.getByRole("button", { name: "打开导航" })
      await expect(openNavigation).toBeVisible()
      await openNavigation.click()
    }
    await expect(visibleUserMenu).toHaveCount(1)
    await expect(visibleUserMenu).toHaveAttribute("aria-expanded", "false")
    await expect(
      page.locator('[data-slot="dropdown-menu-content"][data-state="closed"]'),
    ).toHaveCount(0)
    await visibleUserMenu.click()
    await expect(openMenu).toHaveCount(1)
  }
  const appearanceTrigger = openMenu.locator('[data-testid="theme-button"]')
  const lightMode = openMenu.locator('[data-testid="light-mode"]')
  if ((await lightMode.count()) === 0) {
    await expect(appearanceTrigger).toBeVisible()
    await appearanceTrigger.click()
  }
  await expect(lightMode).toHaveCount(1)
}

test("My profile tab is active by default", async ({ page }) => {
  await page.goto("/settings")
  await expect(page.getByRole("tab", { name: "个人资料" })).toHaveAttribute(
    "aria-selected",
    "true",
  )
})

test("All tabs are visible", async ({ page }) => {
  await page.goto("/settings")
  for (const tab of tabs) {
    await expect(page.getByRole("tab", { name: tab })).toBeVisible()
  }
})

test.describe("Edit user profile", () => {
  test.use({ storageState: { cookies: [], origins: [] } })
  let email: string
  let password: string

  test.beforeAll(async () => {
    email = randomEmail()
    password = randomPassword()
    await createUser({ email, password })
  })

  test.beforeEach(async ({ page }) => {
    await logInUser(page, email, password)
    await page.goto("/settings")
    await page.getByRole("tab", { name: "个人资料" }).click()
  })

  test("Edit user name with a valid name", async ({ page }) => {
    const updatedName = "Test User 2"

    await page.getByRole("button", { name: "编辑资料" }).click()
    await page.getByLabel("姓名").fill(updatedName)
    await page.getByRole("button", { name: "保存" }).click()

    await expect(page.getByText("个人资料已更新")).toBeVisible()
    await expect(
      page.locator("form").getByText(updatedName, { exact: true }),
    ).toBeVisible()
  })

  test("Edit user email with an invalid email shows error", async ({
    page,
  }) => {
    await page.getByRole("button", { name: "编辑资料" }).click()
    await page.getByLabel("邮箱").fill("")
    await page.locator("body").click()

    await expect(page.getByText("请输入有效的邮箱地址")).toBeVisible()
  })
})

test.describe("Edit user email", () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test("Edit user email with a valid email", async ({ page }) => {
    const email = randomEmail()
    const password = randomPassword()
    const updatedEmail = randomEmail()

    await createUser({ email, password })
    await logInUser(page, email, password)
    await page.goto("/settings")
    await page.getByRole("tab", { name: "个人资料" }).click()

    await page.getByRole("button", { name: "编辑资料" }).click()
    await page.getByLabel("邮箱").fill(updatedEmail)
    await page.getByRole("button", { name: "保存" }).click()

    await expect(page.getByText("个人资料已更新")).toBeVisible()
    await expect(
      page.locator("form").getByText(updatedEmail, { exact: true }),
    ).toBeVisible()
  })
})

test.describe("Cancel edit actions", () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test("Cancel edit action restores original name", async ({ page }) => {
    const email = randomEmail()
    const password = randomPassword()
    const user = await createUser({ email, password })

    await logInUser(page, email, password)
    await page.goto("/settings")
    await page.getByRole("tab", { name: "个人资料" }).click()
    await page.getByRole("button", { name: "编辑资料" }).click()
    await page.getByLabel("姓名").fill("Test User")
    await page.getByRole("button", { name: "取消" }).first().click()

    await expect(
      page.locator("form").getByText(user.full_name as string, { exact: true }),
    ).toBeVisible()
  })

  test("Cancel edit action restores original email", async ({ page }) => {
    const email = randomEmail()
    const password = randomPassword()
    await createUser({ email, password })

    await logInUser(page, email, password)
    await page.goto("/settings")
    await page.getByRole("tab", { name: "个人资料" }).click()
    await page.getByRole("button", { name: "编辑资料" }).click()
    await page.getByLabel("邮箱").fill(randomEmail())
    await page.getByRole("button", { name: "取消" }).first().click()

    await expect(
      page.locator("form").getByText(email, { exact: true }),
    ).toBeVisible()
  })
})

test.describe("Change password", () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test("Update password successfully", async ({ page }) => {
    const email = randomEmail()
    const password = randomPassword()
    const newPassword = randomPassword()

    await createUser({ email, password })
    await logInUser(page, email, password)

    await page.goto("/settings")
    await page.getByRole("tab", { name: "登录密码" }).click()
    await page.getByTestId("current-password-input").fill(password)
    await page.getByTestId("new-password-input").fill(newPassword)
    await page.getByTestId("confirm-password-input").fill(newPassword)
    await page.getByRole("button", { name: "更新密码" }).click()

    await expect(page.getByText("密码已更新")).toBeVisible()

    await logOutUser(page)
    await logInUser(page, email, newPassword)
  })
})

test.describe("Change password validation", () => {
  test.use({ storageState: { cookies: [], origins: [] } })
  let email: string
  let password: string

  test.beforeAll(async () => {
    email = randomEmail()
    password = randomPassword()
    await createUser({ email, password })
  })

  test.beforeEach(async ({ page }) => {
    await logInUser(page, email, password)
    await page.goto("/settings")
    await page.getByRole("tab", { name: "登录密码" }).click()
  })

  test("Update password with weak passwords", async ({ page }) => {
    const weakPassword = "weak"

    await page.getByTestId("current-password-input").fill(password)
    await page.getByTestId("new-password-input").fill(weakPassword)
    await page.getByTestId("confirm-password-input").fill(weakPassword)
    await page.getByRole("button", { name: "更新密码" }).click()

    await expect(page.getByText("密码至少需要 8 个字符")).toBeVisible()
  })

  test("New password and confirmation password do not match", async ({
    page,
  }) => {
    await page.getByTestId("current-password-input").fill(password)
    await page.getByTestId("new-password-input").fill(randomPassword())
    await page.getByTestId("confirm-password-input").fill(randomPassword())
    await page.getByRole("button", { name: "更新密码" }).click()

    await expect(page.getByText("两次输入的密码不一致")).toBeVisible()
  })

  test("Current password and new password are the same", async ({ page }) => {
    await page.getByTestId("current-password-input").fill(password)
    await page.getByTestId("new-password-input").fill(password)
    await page.getByTestId("confirm-password-input").fill(password)
    await page.getByRole("button", { name: "更新密码" }).click()

    await expect(page.getByText("新密码不能与当前密码相同")).toBeVisible()
  })
})

test("Appearance settings are available from the user menu", async ({
  page,
}) => {
  await page.goto("/settings")

  await expect(page.getByTestId("theme-button")).not.toBeVisible()
  await page.getByTestId("user-menu").click()
  await expect(page.getByTestId("theme-button")).toBeVisible()
})

test("User can switch between theme modes", async ({ page }) => {
  await page.goto("/settings")

  await openAppearanceMenu(page)
  await page.locator('[data-testid="dark-mode"]:visible').click()
  await expect(page.locator("html")).toHaveClass(/dark/)

  await expect(page.getByTestId("dark-mode")).not.toBeVisible()

  await openAppearanceMenu(page)
  await page.locator('[data-testid="light-mode"]:visible').click()
  await expect(page.locator("html")).toHaveClass(/light/)
})

test("Appearance controls stay usable on a narrow screen", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto("/settings")

  await openAppearanceMenu(page)
  const options = page.locator('[data-testid="appearance-options"]:visible')
  const bounds = await options.boundingBox()

  expect(bounds).not.toBeNull()
  expect(bounds?.x ?? -1).toBeGreaterThanOrEqual(0)
  expect((bounds?.x ?? 0) + (bounds?.width ?? 0)).toBeLessThanOrEqual(390)
  await expect(page.locator('[data-testid="dark-mode"]:visible')).toHaveCount(1)
  await page.locator('[data-testid="dark-mode"]:visible').click()
  await expect(page.locator("html")).toHaveClass(/dark/)

  await openAppearanceMenu(page)
  await page.locator('[data-testid="light-mode"]:visible').click()
  await expect(page.locator("html")).toHaveClass(/light/)
})

test("Selected mode is preserved across sessions", async ({ page }) => {
  await page.goto("/settings")

  await openAppearanceMenu(page)
  if (
    await page.evaluate(() =>
      document.documentElement.classList.contains("dark"),
    )
  ) {
    await page.locator('[data-testid="light-mode"]:visible').click()
  }

  const isLightMode = await page.evaluate(() =>
    document.documentElement.classList.contains("light"),
  )
  expect(isLightMode).toBe(true)

  await openAppearanceMenu(page)
  await page.locator('[data-testid="dark-mode"]:visible').click()
  let isDarkMode = await page.evaluate(() =>
    document.documentElement.classList.contains("dark"),
  )
  expect(isDarkMode).toBe(true)

  await logOutUser(page)
  await logInUser(page, firstSuperuser, firstSuperuserPassword)

  isDarkMode = await page.evaluate(() =>
    document.documentElement.classList.contains("dark"),
  )
  expect(isDarkMode).toBe(true)
})
