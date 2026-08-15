import { expect, type Page, test } from "@playwright/test"
import { firstSuperuser, firstSuperuserPassword } from "./config.ts"
import { randomPassword } from "./utils/random.ts"

test.use({ storageState: { cookies: [], origins: [] } })

const fillForm = async (page: Page, email: string, password: string) => {
  await page.getByTestId("email-input").fill(email)
  await page.getByTestId("password-input").fill(password)
}

const verifyInput = async (page: Page, testId: string) => {
  const input = page.getByTestId(testId)
  await expect(input).toBeVisible()
  await expect(input).toHaveText("")
  await expect(input).toBeEditable()
}

test("Inputs are visible, empty and editable", async ({ page }) => {
  await page.goto("/login")

  await verifyInput(page, "email-input")
  await verifyInput(page, "password-input")
})

test("Log In button is visible", async ({ page }) => {
  await page.goto("/login")

  await expect(page.getByRole("button", { name: "登录" })).toBeVisible()
})

test("Forgot Password link is visible", async ({ page }) => {
  await page.goto("/login")

  await expect(page.getByRole("link", { name: "忘记密码？" })).toBeVisible()
})

test("Log in with valid email and password ", async ({ page }) => {
  await page.goto("/login")

  await fillForm(page, firstSuperuser, firstSuperuserPassword)
  await page.getByRole("button", { name: "登录" }).click()

  await page.waitForURL("/")

  await expect(
    page.getByRole("heading", { name: /欢迎回来|你好，/ }),
  ).toBeVisible()
})

test("Log in with invalid email", async ({ page }) => {
  await page.goto("/login")

  await fillForm(page, "invalidemail", firstSuperuserPassword)
  await page.getByRole("button", { name: "登录" }).click()

  await expect(page.getByText("请输入有效的邮箱地址")).toBeVisible()
})

test("Log in with invalid password", async ({ page }) => {
  const password = randomPassword()

  await page.goto("/login")
  await fillForm(page, firstSuperuser, password)
  await page.getByRole("button", { name: "登录" }).click()

  await expect(page.getByText("邮箱或密码错误")).toBeVisible()
  await expect(page.getByText("操作失败", { exact: true })).toBeVisible()

  const toaster = page.locator("[data-sonner-toaster]")
  const errorToast = page.locator('[data-sonner-toast][data-type="error"]')
  await expect(toaster).toHaveAttribute("data-x-position", "right")
  await expect(toaster).toHaveAttribute("data-y-position", "top")
  await expect(toaster).toHaveCSS("pointer-events", "none")
  await expect(errorToast).toHaveCSS("pointer-events", "auto")

  await errorToast.getByRole("button", { name: "关闭通知" }).click()
  await expect(errorToast).not.toBeVisible()
})

test("Successful log out", async ({ page }) => {
  await page.goto("/login")

  await fillForm(page, firstSuperuser, firstSuperuserPassword)
  await page.getByRole("button", { name: "登录" }).click()

  await page.waitForURL("/")

  await expect(
    page.getByRole("heading", { name: /欢迎回来|你好，/ }),
  ).toBeVisible()

  await page.getByTestId("user-menu").click()
  await page.getByRole("menuitem", { name: "退出登录" }).click()
  await page.waitForURL("/login")
})

test("Logged-out user cannot access protected routes", async ({ page }) => {
  await page.goto("/login")

  await fillForm(page, firstSuperuser, firstSuperuserPassword)
  await page.getByRole("button", { name: "登录" }).click()

  await page.waitForURL("/")

  await expect(
    page.getByRole("heading", { name: /欢迎回来|你好，/ }),
  ).toBeVisible()

  await page.getByTestId("user-menu").click()
  await page.getByRole("menuitem", { name: "退出登录" }).click()
  await page.waitForURL("/login")

  await page.goto("/settings")
  await page.waitForURL("/login")
})

test("Redirects to /login when token is wrong", async ({ page }) => {
  await page.goto("/settings")
  await page.evaluate(() => {
    localStorage.setItem("access_token", "invalid_token")
  })
  await page.goto("/settings")
  await page.waitForURL("/login")
  await expect(page).toHaveURL("/login")
})
