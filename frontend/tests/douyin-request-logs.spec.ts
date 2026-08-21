import { expect, test } from "@playwright/test"

const LOGS = [
  {
    id: "log-1",
    task_id: "task-1",
    method: "GET",
    path: "/aweme/v1/web/general/search/single/",
    url: "https://www.douyin.com/aweme/v1/web/general/search/single/?keyword=%E9%9C%B2%E8%90%A5",
    query_params: { keyword: "露营" },
    request_headers: {
      Cookie: "[REDACTED]",
      "User-Agent": "Mozilla/5.0",
      Referer: "https://www.douyin.com/",
    },
    request_body: null,
    response_status: 200,
    duration_ms: 30,
    error: null,
    failure_detail: null,
    created_at: "2026-08-20T10:00:00+08:00",
  },
  {
    id: "log-2",
    task_id: "task-1",
    method: "POST",
    path: "/aweme/v1/web/aweme/listcollection/",
    url: "https://www.douyin.com/aweme/v1/web/aweme/listcollection/",
    query_params: { aid: "6383" },
    request_headers: { Cookie: "[REDACTED]" },
    request_body: { count: 10 },
    response_status: 403,
    duration_ms: 50,
    error: "blocked",
    failure_detail: {
      http_status: 403,
      body: {
        status_code: 4,
        status_msg: "请求过于频繁",
        search_nil_info: { search_nil_type: "verify_check" },
      },
    },
    created_at: "2026-08-20T09:59:00+08:00",
  },
  {
    id: "log-3",
    task_id: null,
    method: "GET",
    path: "/aweme/v1/web/aweme/detail/",
    url: "https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id=1",
    query_params: { aweme_id: "1" },
    request_headers: { Cookie: "[REDACTED]" },
    request_body: null,
    response_status: null,
    duration_ms: 120,
    error: "ConnectError",
    failure_detail: {
      kind: "transport_error",
      exception_type: "ConnectError",
      message: "网络请求未收到 HTTP 响应",
    },
    created_at: "2026-08-20T09:58:00+08:00",
  },
]

test("request logs page lists entries, filters and shows full request details", async ({
  page,
}) => {
  let lastQuery: URLSearchParams | null = null
  await page.route("**/api/v1/douyin/tasks**", async (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    await route.fulfill({
      json: {
        count: 1,
        data: [
          {
            id: "task-1",
            owner_id: "owner",
            track_id: "track-1",
            track_name: "私域增长",
            track_is_default: false,
            account_id: null,
            account_pool_id: null,
            account_strategy: "auto",
            crawl_type: "search",
            status: "succeeded",
            request: { crawl_type: "search" },
            display_title: "搜索：露营",
            display_author: null,
            display_aweme_id: null,
            aweme_count: 0,
            comment_count: 0,
            action_count: 0,
            checkpoint_phase: "completed",
            resume_count: 0,
            can_resume_crawl: false,
            can_resume_media: false,
            error: null,
            has_qrcode: false,
            created_at: "2026-08-20T08:00:00+08:00",
            updated_at: "2026-08-20T08:30:00+08:00",
          },
        ],
      },
    })
  })
  await page.route("**/api/v1/douyin/request-logs**", async (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    lastQuery = new URL(route.request().url()).searchParams
    await route.fulfill({
      json: { count: LOGS.length, data: LOGS },
    })
  })

  await page.goto("/douyin-request-logs")
  await expect(page.getByRole("heading", { name: "请求日志" })).toBeVisible()

  // 侧边栏入口直达
  await expect(page.getByRole("link", { name: "请求日志" })).toHaveAttribute(
    "href",
    "/douyin-request-logs",
  )

  // 表格展示：方法、路径、状态、耗时与任务名（从任务列表解析）
  await expect(
    page.getByText("/aweme/v1/web/general/search/single/"),
  ).toBeVisible()
  await expect(
    page.getByText("/aweme/v1/web/aweme/listcollection/"),
  ).toBeVisible()
  const taskLinks = page.locator('a[href="/douyin/task-1"]')
  await expect(taskLinks).toHaveCount(2)
  await expect(taskLinks.first()).toHaveText("搜索：露营")
  await expect(page.getByText("30 ms")).toBeVisible()
  await expect(page.getByText("blocked")).toBeVisible()
  await expect(page.getByText("请求过于频繁")).toBeVisible()
  await expect(page.getByText("ConnectError")).toBeVisible()
  await expect(taskLinks.first()).toHaveAttribute("href", "/douyin/task-1")

  await page.getByRole("button", { name: "横条" }).click()
  await expect(page.getByText("返回：请求过于频繁")).toBeVisible()
  await page.getByRole("button", { name: "卡片" }).click()
  await expect(page.getByText("30 ms")).toBeVisible()
  await page.getByRole("button", { name: "表格" }).click()

  // 无任务关联的记录显示占位符
  await expect(page.getByRole("row", { name: /ConnectError/ })).toContainText(
    "—",
  )

  // 路径包含筛选把 path 参数带给后端
  await page.getByPlaceholder("如 aweme/detail").fill("listcollection")
  await page.getByRole("button", { name: "查询" }).click()
  await expect.poll(() => lastQuery?.get("path")).toBe("listcollection")

  // 状态码筛选转数字
  await page.getByPlaceholder("如 403").fill("403")
  await page.getByRole("button", { name: "查询" }).click()
  await expect.poll(() => lastQuery?.get("response_status")).toBe("403")

  // 方法筛选
  await page.getByLabel("请求方法").click()
  await page.getByRole("option", { name: "GET" }).click()
  await page.getByRole("button", { name: "查询" }).click()
  await expect.poll(() => lastQuery?.get("method")).toBe("GET")

  // 详情弹窗：URL、查询参数、请求头与请求体
  await page.getByLabel("查看请求详情").first().click()
  await expect(
    page.getByRole("heading", { name: "抖音接口请求详情" }),
  ).toBeVisible()
  await expect(
    page.getByText(
      "https://www.douyin.com/aweme/v1/web/general/search/single/",
    ),
  ).toBeVisible()
  await expect(page.getByText('"keyword": "露营"')).toBeVisible()
  await expect(page.getByText('"Cookie": "[REDACTED]"')).toBeVisible()
  await page.getByRole("button", { name: "关闭" }).click()
  await expect(
    page.getByRole("heading", { name: "抖音接口请求详情" }),
  ).toBeHidden()

  // 请求体仅在 POST 记录上出现
  await page.getByLabel("查看请求详情").nth(1).click()
  await expect(page.getByText("请求体")).toBeVisible()
  await expect(page.getByText('"count": 10')).toBeVisible()
  await expect(page.getByText("失败返回信息（已脱敏）")).toBeVisible()
  await expect(page.getByText('"status_msg": "请求过于频繁"')).toBeVisible()
  await expect(
    page.getByText('"search_nil_type": "verify_check"'),
  ).toBeVisible()
  await page.getByRole("button", { name: "关闭" }).click()

  // 总条数与分页状态
  await expect(page.getByText("共 3 条记录")).toBeVisible()
  await expect(page.getByRole("button", { name: "下一页" })).toBeDisabled()
  await expect(page.getByRole("button", { name: "上一页" })).toBeDisabled()
})
