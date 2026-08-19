import { expect, test } from "@playwright/test"

const idleMediaMigration = {
  migration_status: "idle",
  migration_progress: 0,
  migration_attempt_count: 0,
  migration_error: null,
  migration_started_at: null,
  migration_finished_at: null,
}

test("video library lists undownloaded works with three switchable layouts", async ({
  page,
}) => {
  const libTaskId = "7a6b5c4d-3e2f-4a1b-9c8d-7e6f5a4b3c2d"
  const now = new Date().toISOString()
  const longTitle =
    "这是一条很长很长的视频标题用来验证表格视图里长标题截断之后悬浮展示完整内容的效果长度一定要足够长"
  const awemeBase = {
    task_id: libTaskId,
    aweme_type: "video",
    description: "",
    create_time: 1735689600,
    creator_hash: "creator-1",
    sec_uid: "sec-1",
    aweme_url: "",
    cover_url: "",
    video_download_url: "",
    music_download_url: "",
    note_download_url: "",
    fetched_at: now,
  }
  const downloadedWork = {
    aweme: {
      ...awemeBase,
      id: "w-1",
      aweme_id: "7300000000000000001",
      title: "已下载的露营视频",
      nickname: "露营达人",
      liked_count: 1200,
      collected_count: 300,
      comment_count: 88,
      share_count: 12,
      source_keyword: "露营",
    },
    persisted_comment_count: 66,
    media: {
      id: "m-1",
      task_id: libTaskId,
      aweme_id: "7300000000000000001",
      storage_backend: "local",
      status: "downloaded",
      progress: 100,
      attempt_count: 1,
      mime_type: "video/mp4",
      file_size: 2048,
      sha256: "x",
      error: null,
      download_available: true,
      created_at: now,
      updated_at: now,
      completed_at: now,
      ...idleMediaMigration,
      subtitle: null,
    },
    tags: [],
  }
  const pendingWork = {
    aweme: {
      ...awemeBase,
      id: "w-2",
      aweme_id: "7300000000000000002",
      title: longTitle,
      nickname: "户外玩家",
      liked_count: 34,
      collected_count: 5,
      comment_count: 2,
      share_count: 0,
      source_keyword: "户外",
    },
    persisted_comment_count: 0,
    media: null,
    tags: [],
  }
  let requestedDownloadStatus = "unset"
  await page.route("**/api/v1/douyin/tracks**", async (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    await route.fulfill({ json: { data: [], count: 0 } })
  })
  await page.route("**/api/v1/douyin/library/works**", async (route) => {
    requestedDownloadStatus =
      new URL(route.request().url()).searchParams.get("download_status") ?? ""
    await route.fulfill({
      json: { data: [downloadedWork, pendingWork], count: 2 },
    })
  })
  await page.route("**/api/v1/douyin/library/creators**", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })
  await page.route("**/api/v1/douyin/tags/**", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })
  await page.route("**/api/v1/douyin/tasks**", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })

  await page.goto("/douyin-library")
  await expect.poll(() => requestedDownloadStatus).toBe("all")
  await expect(page.getByText("已下载的露营视频")).toBeVisible()
  await expect(page.getByText("未下载", { exact: true }).first()).toBeVisible()
  await expect(page.getByText("本地", { exact: true }).first()).toBeVisible()

  await page.getByLabel("按下载状态筛选").click()
  await page.getByRole("option", { name: "已下载" }).click()
  await expect.poll(() => requestedDownloadStatus).toBe("downloaded")
  await page.getByLabel("按下载状态筛选").click()
  await page.getByRole("option", { name: "全部状态" }).click()
  await expect.poll(() => requestedDownloadStatus).toBe("all")

  await page.getByRole("button", { name: "横条" }).click()
  await expect(page.getByRole("heading", { name: longTitle })).toBeVisible()

  await page.getByRole("button", { name: "表格" }).click()
  const titleText = page.locator("td").getByText(longTitle)
  await titleText.hover()
  await expect(page.getByRole("tooltip")).toContainText("很长很长的视频标题")

  await page.reload()
  await expect(page.getByRole("button", { name: "表格" })).toHaveAttribute(
    "aria-pressed",
    "true",
  )
  await expect(
    page.getByRole("columnheader", { name: "已存评论" }),
  ).toBeVisible()
})
