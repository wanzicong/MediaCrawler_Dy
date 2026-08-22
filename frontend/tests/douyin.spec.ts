import { readFileSync } from "node:fs"

import { expect, test } from "@playwright/test"

const emptyMigrationSummary = {
  local_downloaded: 0,
  minio_downloaded: 0,
  migration_queued: 0,
  migration_running: 0,
  migration_cleanup_pending: 0,
  migration_completed: 0,
  migration_failed: 0,
}

const idleMediaMigration = {
  migration_status: "idle",
  migration_progress: 0,
  migration_attempt_count: 0,
  migration_error: null,
  migration_started_at: null,
  migration_finished_at: null,
}

function emptyMediaSummary() {
  return {
    total: 0,
    queued: 0,
    downloading: 0,
    downloaded: 0,
    download_failed: 0,
    subtitle_pending: 0,
    subtitle_running: 0,
    subtitle_completed: 0,
    subtitle_failed: 0,
    local_downloaded: 0,
    minio_downloaded: 0,
    migration_queued: 0,
    migration_running: 0,
    migration_cleanup_pending: 0,
    migration_completed: 0,
    migration_failed: 0,
  }
}

test("filters, selects and exports comments from the comment workspace", async ({
  page,
}) => {
  const taskId = "296fc305-09ad-4a55-9550-d56547ab7965"
  const commentId = "16a8148c-c8b6-4c6c-b7c4-93580d687388"
  const now = new Date().toISOString()
  let commentQuery = new URLSearchParams()
  let exportedIds: string[] = []

  await page.route("**/api/v1/douyin/tasks?**", async (route) => {
    await route.fulfill({
      json: {
        count: 1,
        data: [
          {
            id: taskId,
            owner_id: "c7e0bb1c-891a-4b4a-8f12-26c1ddd8239d",
            account_id: null,
            account_pool_id: null,
            account_strategy: "least_loaded",
            crawl_type: "search",
            status: "succeeded",
            request: { keywords: ["露营"] },
            aweme_count: 1,
            comment_count: 1,
            action_count: 0,
            checkpoint_phase: "completed",
            resume_count: 0,
            can_resume_crawl: false,
            can_resume_media: false,
            error: null,
            has_qrcode: false,
            created_at: now,
            started_at: now,
            finished_at: now,
            last_resumed_at: null,
          },
        ],
      },
    })
  })
  await page.route("**/api/v1/douyin/comments?**", async (route) => {
    commentQuery = new URL(route.request().url()).searchParams
    await route.fulfill({
      json: {
        count: 1,
        summary: {
          matched_count: 1,
          top_level_count: 1,
          reply_count: 0,
          picture_count: 1,
          total_like_count: 28,
        },
        data: [
          {
            comment: {
              id: commentId,
              task_id: taskId,
              comment_id: "7671284134611116154",
              aweme_id: "7642649124428320036",
              parent_comment_id: "0",
              content: "这个帐篷真的很好用",
              create_time: 1710000100,
              creator_hash: "commenter-hash",
              sec_uid: "masked-sec-uid",
              nickname: "户外玩家",
              sub_comment_count: 2,
              like_count: 28,
              pictures: "https://example.invalid/comment.jpg",
              fetched_at: now,
            },
            aweme: {
              id: "26a8148c-c8b6-4c6c-b7c4-93580d687388",
              task_id: taskId,
              aweme_id: "7642649124428320036",
              aweme_type: "video",
              title: "海边露营攻略",
              description: "露营装备分享",
              create_time: 1710000000,
              creator_hash: "creator-hash",
              sec_uid: "masked-creator",
              nickname: "露营作者",
              liked_count: 100,
              collected_count: 20,
              comment_count: 30,
              share_count: 5,
              aweme_url: "",
              cover_url: "",
              video_download_url: "",
              music_download_url: "",
              note_download_url: "",
              source_keyword: "露营",
              fetched_at: now,
            },
            task_status: "succeeded",
            task_created_at: now,
            track_id: "00d5dae3-5481-4a36-ac38-e91a7abcee51",
            track_name: "默认赛道",
            task_title: "露营作品评论",
          },
        ],
      },
    })
  })
  await page.route("**/api/v1/douyin/comments/export", async (route) => {
    exportedIds = (route.request().postDataJSON() as { comment_ids: string[] })
      .comment_ids
    await route.fulfill({
      status: 200,
      contentType: "text/plain; charset=utf-8",
      headers: {
        "Content-Disposition":
          "attachment; filename=douyin-selected-comments.txt",
      },
      body: "抖音评论精选导出",
    })
  })

  await page.goto("/douyin-comments")
  await expect(page.getByRole("heading", { name: "评论管理" })).toBeVisible()
  await expect(page.getByText("这个帐篷真的很好用")).toBeVisible()

  await page.getByRole("button", { name: "横条" }).click()
  await expect(page.getByText("海边露营攻略")).toBeVisible()
  await page.getByRole("button", { name: "卡片" }).click()
  await expect(page.getByLabel("复制评论内容")).toBeVisible()
  await page.getByRole("button", { name: "表格" }).click()

  // 评论表只保留赛道/任务来源、视频、评论和时间等核心信息。
  const headers = page.getByRole("columnheader")
  await expect(headers.nth(1)).toHaveText("赛道 / 来源")
  await expect(headers.nth(2)).toHaveText("视频标题")
  await expect(headers.nth(3)).toHaveText("评论内容")
  await expect(headers.nth(4)).toHaveText("评论时间")
  await expect(page.locator("td").getByText("默认赛道")).toBeVisible()
  await expect(
    page.locator("td").getByText("[关键词] 露营", { exact: true }),
  ).toBeVisible()
  await expect(page.locator("td").getByText("海边露营攻略")).toBeVisible()

  // 评论内容悬浮展示完整文本，并支持一键复制
  await page.locator("td").getByText("这个帐篷真的很好用").hover()
  await expect(page.getByRole("tooltip")).toContainText("这个帐篷真的很好用")
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"])
  await page.getByLabel("复制评论内容").click()
  await expect(page.getByText("评论内容已复制")).toBeVisible()
  const copied = await page.evaluate(() => navigator.clipboard.readText())
  expect(copied).toBe("这个帐篷真的很好用")
  await page.getByPlaceholder("搜索评论内容").fill("帐篷真的")
  await page.getByRole("button", { name: /更多筛选/ }).click()
  await page
    .getByPlaceholder("评论内容、评论人、评论号、视频标题或作品号")
    .fill("帐篷")
  await page.getByPlaceholder("输入作者昵称").fill("露营作者")
  await page.getByPlaceholder("任务命中的关键词").fill("露营")
  await page.getByRole("button", { name: "查询评论" }).click()
  await expect.poll(() => commentQuery.get("comment_content")).toBe("帐篷真的")
  await expect.poll(() => commentQuery.get("search")).toBe("帐篷")
  expect(commentQuery.get("video_creator")).toBe("露营作者")
  expect(commentQuery.get("source_keyword")).toBe("露营")

  // 筛选导出：按当前全部筛选条件生成精简 TXT，不再让用户选择冗余字段
  await page.getByRole("button", { name: "导出筛选结果" }).click()
  const exportDialog = page.getByRole("dialog")
  await expect(exportDialog.getByText("导出筛选结果")).toBeVisible()
  const txtDownload = page.waitForEvent("download")
  await exportDialog.getByRole("button", { name: "确认导出 TXT" }).click()
  const txtFile = await txtDownload
  expect(txtFile.suggestedFilename()).toMatch(/douyin-comments-.*\.txt/)
  await expect(page.getByText(/已按筛选条件导出 1 条评论/)).toBeVisible()
  const txtPath = await txtFile.path()
  const txtContent = readFileSync(txtPath, "utf-8")
  expect(txtContent).toContain("评论内容")
  expect(txtContent).toContain("视频标题")
  expect(txtContent).not.toContain("评论图片")
  expect(txtContent).toContain("这个帐篷真的很好用")

  await page.getByLabel("选择评论 7671284134611116154").click()
  const download = page.waitForEvent("download")
  await page.getByRole("button", { name: "导出已选（1）" }).click()
  await download
  expect(exportedIds).toEqual([commentId])
})

test("shows live browser slots inside the browser monitor", async ({
  page,
}) => {
  await page.route("**/api/v1/douyin/accounts/browser-slots", async (route) => {
    await route.fulfill({
      json: {
        count: 1,
        data: [
          {
            name: null,
            label: "Docker 默认槽位",
            is_default: true,
            available: false,
            configured: true,
            viewer_available: true,
            viewer_url: "http://127.0.0.1:6081/vnc.html?autoconnect=1",
            cdp_healthy: true,
            page_count: 1,
            active_page_title: "抖音首页",
            active_page_url: "https://www.douyin.com/",
            latency_ms: 42,
            checked_at: new Date().toISOString(),
            occupied_account_id: "c7e0bb1c-891a-4b4a-8f12-26c1ddd8239d",
            occupied_account_name: "大号",
          },
        ],
      },
    })
  })
  await page.route("http://127.0.0.1:6081/**", async (route) => {
    await route.fulfill({ contentType: "text/html", body: "<p>noVNC</p>" })
  })

  await page.goto("/douyin-browsers")
  await expect(
    page.getByRole("heading", { name: "浏览器监控中心" }),
  ).toBeVisible()
  await expect(page.getByText("浏览器在线")).toBeVisible()
  await expect(page.getByText("大号").first()).toBeVisible()
  await expect(
    page.locator('iframe[title="云端默认槽位 实时浏览器"]'),
  ).toBeVisible()
})

test("creates a track brief from the track workspace", async ({ page }) => {
  let createdBody: Record<string, unknown> = {}
  await page.route("**/api/v1/douyin/tracks**", async (route) => {
    const request = route.request()
    if (request.method() === "POST") {
      createdBody = request.postDataJSON()
      await route.fulfill({
        status: 201,
        json: {
          id: "16a8148c-c8b6-4c6c-b7c4-93580d687388",
          name: "户外露营",
          description: "寻找装备兴趣用户",
          enabled: true,
          keyword_count: 2,
          enabled_keyword_count: 2,
          task_count: 0,
          active_task_count: 0,
          aweme_count: 0,
          comment_count: 0,
          last_task_id: null,
          last_task_status: null,
          last_run_at: null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      })
      return
    }
    await route.fulfill({ json: { count: 0, data: [] } })
  })
  await page.route("**/api/v1/douyin/keywords/**", async (route) => {
    const now = new Date().toISOString()
    await route.fulfill({
      json: {
        count: 1,
        data: [
          {
            id: "26a8148c-c8b6-4c6c-b7c4-93580d687388",
            keyword: "已有露营词",
            enabled: true,
            notes: "关键词库资产",
            status: "crawled",
            task_count: 3,
            active_task_count: 0,
            success_task_count: 3,
            failed_task_count: 0,
            aweme_count: 120,
            last_task_id: null,
            last_task_status: null,
            last_crawled_at: now,
            created_at: now,
            updated_at: now,
          },
        ],
      },
    })
  })

  await page.goto("/douyin-tracks")
  await expect(page.getByRole("heading", { name: "赛道管理" })).toBeVisible()
  await page.getByRole("button", { name: "创建赛道" }).click()
  await page.getByLabel("赛道名称").fill("户外露营")
  await page.getByLabel("目标与人群").fill("寻找装备兴趣用户")
  await page.getByLabel("创建新关键词").fill("帐篷\n露营炉具")
  await page.getByLabel("选择关键词 已有露营词").click()
  page.once("dialog", (dialog) => dialog.accept())
  await page
    .getByRole("button", { name: "创建赛道", exact: true })
    .last()
    .click()
  await expect(page.getByText("赛道已创建，关键词已归入新赛道")).toBeVisible()
  expect(createdBody).toMatchObject({
    name: "户外露营",
    keywords: ["帐篷", "露营炉具", "已有露营词"],
  })
})

test("track workspace lists bound keywords without the removed move panel", async ({
  page,
}) => {
  const trackId = "36a8148c-c8b6-4c6c-b7c4-93580d687388"
  const linkedKeywordId = "46a8148c-c8b6-4c6c-b7c4-93580d687388"
  const existingKeywordId = "56a8148c-c8b6-4c6c-b7c4-93580d687388"
  const now = new Date().toISOString()
  const keyword = (id: string, value: string) => ({
    id,
    keyword: value,
    enabled: true,
    notes: "",
    status: "crawled",
    task_count: 2,
    active_task_count: 0,
    success_task_count: 2,
    failed_task_count: 0,
    aweme_count: 40,
    last_task_id: null,
    last_task_status: null,
    last_crawled_at: now,
    created_at: now,
    updated_at: now,
  })
  const track = {
    id: trackId,
    name: "私域运营",
    description: "验证现有关键词复用",
    enabled: true,
    keyword_count: 1,
    enabled_keyword_count: 1,
    task_count: 0,
    active_task_count: 0,
    aweme_count: 0,
    comment_count: 0,
    last_task_id: null,
    last_task_status: null,
    last_run_at: null,
    created_at: now,
    updated_at: now,
  }

  await page.route("**/api/v1/douyin/tracks**", async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    // 运营工作区会读取赛道达人；固定空名单避免脏数据
    if (url.pathname.endsWith("/creators")) {
      await route.fulfill({ json: { count: 0, data: [] } })
      return
    }
    if (url.pathname.endsWith(`/${trackId}/keywords`)) {
      if (request.method() === "POST") {
        await route.fulfill({
          json: {
            count: 2,
            data: [
              keyword(linkedKeywordId, "已绑定词"),
              keyword(existingKeywordId, "关键词库现有词"),
            ],
          },
        })
        return
      }
      await route.fulfill({
        json: {
          count: 1,
          data: [keyword(linkedKeywordId, "已绑定词")],
        },
      })
      return
    }
    await route.fulfill({ json: { count: 1, data: [track] } })
  })
  await page.route("**/api/v1/douyin/keywords/**", async (route) => {
    await route.fulfill({
      json: {
        count: 2,
        data: [
          keyword(linkedKeywordId, "已绑定词"),
          keyword(existingKeywordId, "关键词库现有词"),
        ],
      },
    })
  })
  await page.route("**/api/v1/douyin/accounts**", async (route) => {
    await route.fulfill({ json: { count: 0, data: [] } })
  })

  await page.goto("/douyin-tracks")
  await page.getByRole("button", { name: "横条" }).click()
  await expect(page.getByText("配置：启用", { exact: true })).toBeVisible()
  await expect(page.getByText("最近采集", { exact: true })).toBeVisible()
  await expect(page.getByText("尚未运行", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: "运营这个赛道" }).click()
  // 运营工作区只提供本赛道已绑定关键词的选择，移动他赛道关键词的入口已按需求移除。
  await expect(page.getByLabel("选择采集关键词 已绑定词")).toBeVisible()
  await expect(page.getByText("关键词库现有词")).toHaveCount(0)
  await expect(page.getByLabel("搜索现有关键词")).toHaveCount(0)
  await expect(
    page.getByRole("button", { name: /移动已选关键词/ }),
  ).toHaveCount(0)
})

test("manages a track prompt and keyword associations from its detail page", async ({
  page,
}) => {
  const trackId = "66a8148c-c8b6-4c6c-b7c4-93580d687388"
  const linkedKeywordId = "76a8148c-c8b6-4c6c-b7c4-93580d687388"
  const candidateKeywordId = "86a8148c-c8b6-4c6c-b7c4-93580d687388"
  const now = new Date().toISOString()
  const keyword = (id: string, value: string, notes = "") => ({
    id,
    keyword: value,
    enabled: true,
    notes,
    status: "crawled",
    task_count: 0,
    active_task_count: 0,
    success_task_count: 0,
    failed_task_count: 0,
    aweme_count: 12,
    last_task_id: null,
    last_task_status: null,
    last_crawled_at: now,
    created_at: now,
    updated_at: now,
  })
  let linkedKeywords = [keyword(linkedKeywordId, "同城探店", "原备注")]
  const candidate = keyword(candidateKeywordId, "本地生活")
  let track = {
    id: trackId,
    name: "本地获客",
    description: "面向同城商家的内容赛道",
    prompt: "分析用户的到店需求与购买阻力",
    reply_templates: [],
    keyword_categories: [],
    default_task_config: {},
    enabled: true,
    keyword_count: 1,
    enabled_keyword_count: 1,
    task_count: 2,
    active_task_count: 0,
    aweme_count: 42,
    comment_count: 180,
    last_task_id: null,
    last_task_status: null,
    last_run_at: null,
    created_at: now,
    updated_at: now,
  }
  let patchedTrackBody: Record<string, unknown> = {}
  let appendedBody: Record<string, unknown> = {}
  let editedKeywordBody: Record<string, unknown> = {}
  let removedKeywordId = ""

  await page.route("**/api/v1/douyin/tracks/**", async (route) => {
    const request = route.request()
    const pathname = new URL(request.url()).pathname
    if (pathname.endsWith(`/${trackId}/keywords/${linkedKeywordId}`)) {
      expect(request.method()).toBe("DELETE")
      removedKeywordId = linkedKeywordId
      linkedKeywords = linkedKeywords.filter(
        (item) => item.id !== linkedKeywordId,
      )
      track = {
        ...track,
        keyword_count: linkedKeywords.length,
        enabled_keyword_count: linkedKeywords.length,
        updated_at: new Date(Date.now() + 3000).toISOString(),
      }
      await route.fulfill({ json: { message: "关键词已从赛道移除" } })
      return
    }
    if (pathname.endsWith(`/${trackId}/keywords`)) {
      if (request.method() === "POST") {
        appendedBody = request.postDataJSON()
        linkedKeywords = [...linkedKeywords, candidate]
        track = {
          ...track,
          keyword_count: linkedKeywords.length,
          enabled_keyword_count: linkedKeywords.length,
          updated_at: new Date(Date.now() + 2000).toISOString(),
        }
      } else {
        expect(request.method()).toBe("GET")
      }
      await route.fulfill({
        json: { data: linkedKeywords, count: linkedKeywords.length },
      })
      return
    }
    if (pathname.endsWith(`/${trackId}`)) {
      if (request.method() === "PATCH") {
        patchedTrackBody = request.postDataJSON()
        track = {
          ...track,
          ...patchedTrackBody,
          name:
            typeof patchedTrackBody.name === "string"
              ? patchedTrackBody.name.trim()
              : track.name,
          description:
            typeof patchedTrackBody.description === "string"
              ? patchedTrackBody.description.trim()
              : track.description,
          prompt:
            typeof patchedTrackBody.prompt === "string"
              ? patchedTrackBody.prompt.trim()
              : track.prompt,
          updated_at: new Date(Date.now() + 1000).toISOString(),
        }
      } else {
        expect(request.method()).toBe("GET")
      }
      await route.fulfill({ json: track })
      return
    }
    if (pathname.endsWith(`/${trackId}/creators`)) {
      await route.fulfill({ json: { data: [], count: 0 } })
      return
    }
    throw new Error(`未处理的赛道请求：${request.method()} ${pathname}`)
  })
  await page.route("**/api/v1/douyin/keywords/**", async (route) => {
    const request = route.request()
    if (request.method() === "PATCH") {
      editedKeywordBody = request.postDataJSON()
      linkedKeywords = linkedKeywords.map((item) =>
        item.id === linkedKeywordId ? { ...item, ...editedKeywordBody } : item,
      )
      await route.fulfill({ json: linkedKeywords[0] })
      return
    }
    await route.fulfill({ json: { data: [candidate], count: 1 } })
  })

  await page.goto(`/douyin-tracks/${trackId}`)
  await expect(page.getByRole("heading", { name: "本地获客" })).toBeVisible()
  await expect(page.getByText("配置：启用", { exact: true })).toBeVisible()
  const lastRun = page.getByText("最近一次采集", { exact: true }).locator("..")
  await expect(lastRun).toContainText("尚未运行")
  await page.getByRole("tab", { name: "赛道设置" }).click()
  await expect(page.getByLabel("赛道提示词")).toHaveValue(
    "分析用户的到店需求与购买阻力",
  )
  await page.getByLabel("赛道提示词").fill(" 提炼评论中的需求、异议和线索 ")
  await page.getByRole("button", { name: "保存修改" }).click()
  await expect(page.getByText("赛道信息与提示词已保存")).toBeVisible()
  expect(patchedTrackBody).toMatchObject({
    name: "本地获客",
    prompt: " 提炼评论中的需求、异议和线索 ",
  })
  await expect(page.getByLabel("赛道提示词")).toHaveValue(
    "提炼评论中的需求、异议和线索",
  )
  await expect(page.getByRole("button", { name: "保存修改" })).toBeDisabled()

  await page.getByLabel("赛道提示词").fill("尚未保存的赛道分析草稿")
  await page.getByRole("tab", { name: /关键词（/ }).click()
  await page.getByRole("button", { name: "添加或移动关键词" }).click()
  await page.getByRole("tab", { name: "移动已有关键词" }).click()
  await page.getByLabel("选择关键词 本地生活").click()
  page.once("dialog", (dialog) => dialog.accept())
  await page.getByRole("button", { name: "移动已选关键词" }).click()
  await expect(page.getByText("关键词已归入当前赛道")).toBeVisible()
  expect(appendedBody).toEqual({ keywords: ["本地生活"] })
  await page.getByRole("tab", { name: "赛道设置" }).click()
  await expect(page.getByLabel("赛道提示词")).toHaveValue(
    "尚未保存的赛道分析草稿",
  )

  await page.getByRole("tab", { name: /关键词（/ }).click()
  const linkedRow = page.getByRole("row").filter({ hasText: "同城探店" })
  await linkedRow.getByRole("button", { name: "编辑关键词 同城探店" }).click()
  const editKeywordDialog = page.getByRole("dialog")
  await editKeywordDialog.getByLabel("备注").fill("赛道详情修改后的备注")
  await editKeywordDialog.getByRole("button", { name: "保存修改" }).click()
  await expect(page.getByText("关键词信息已更新")).toBeVisible()
  expect(editedKeywordBody).toMatchObject({
    notes: "赛道详情修改后的备注",
    enabled: true,
  })

  await linkedRow.getByRole("button", { name: "移除关键词 同城探店" }).click()
  await expect(
    page.getByRole("heading", { name: /从当前赛道移除/ }),
  ).toBeVisible()
  await page.getByRole("button", { name: "确认移除" }).click()
  await expect(
    page.getByText("关键词已移回默认赛道，历史任务与内容数据已保留"),
  ).toBeVisible()
  expect(removedKeywordId).toBe(linkedKeywordId)
  await page.getByRole("tab", { name: "赛道设置" }).click()
  await expect(page.getByLabel("赛道提示词")).toHaveValue(
    "尚未保存的赛道分析草稿",
  )

  await page.route("**/api/v1/douyin/tracks", async (route) => {
    expect(route.request().method()).toBe("GET")
    await route.fulfill({ json: { data: [], count: 101 } })
  })
  await page.route("**/api/v1/douyin/accounts**", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })
  await page.getByRole("button", { name: "清空提示词" }).click()
  await expect(page.getByLabel("赛道提示词")).toHaveValue("")
  const finalSave = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/douyin/tracks/${trackId}`) &&
      response.request().method() === "PATCH",
  )
  await page.getByRole("button", { name: "保存修改" }).click()
  await finalSave
  await page.reload()
  await page.getByRole("tab", { name: "赛道设置" }).click()
  await expect(page.getByLabel("赛道提示词")).toHaveValue("")
  await page.getByRole("link", { name: "启动赛道采集" }).click()
  await expect(
    page.getByRole("heading", { name: "本地获客 · 运营工作区" }),
  ).toBeVisible()
  await expect(page).toHaveURL(new RegExp(`/douyin-tracks\\?run=${trackId}$`))
  await page.keyboard.press("Escape")
  await expect(page).toHaveURL(/\/douyin-tracks$/)
  await page.goBack()
  await expect(page).toHaveURL(new RegExp(`/douyin-tracks/${trackId}$`))

  const missingTrackId = "99999999-9999-4999-8999-999999999999"
  await page.route(
    `**/api/v1/douyin/tracks/${missingTrackId}`,
    async (route) => {
      await route.fulfill({ status: 404, json: { detail: "赛道不存在" } })
    },
  )
  await page.goto(`/douyin-tracks?run=${missingTrackId}`)
  await expect(page.getByText("赛道不存在或当前账号无权访问")).toBeVisible()
  await expect(page).toHaveURL(/\/douyin-tracks$/)
})

test("opens the Douyin task page and validates the create form", async ({
  page,
}) => {
  await page.goto("/douyin")

  await expect(
    page.getByRole("heading", { name: "抖音任务管理" }),
  ).toBeVisible()
  await expect(page.getByRole("tab", { name: /采集任务/ })).toHaveAttribute(
    "data-state",
    "active",
  )
  await page.getByRole("button", { name: "创建采集任务" }).click()
  await expect(
    page.getByRole("heading", { name: "创建抖音采集任务" }),
  ).toBeVisible()
  await expect(page.getByLabel("搜索关键词")).toBeVisible()
  await expect(
    page.getByText("云端托管浏览器", { exact: true }).first(),
  ).toBeVisible()
  await page.getByRole("button", { name: "高级设置" }).click()
  await expect(page.getByText("下载与字幕已独立管理")).toBeVisible()
  await expect(page.getByText("稳 · 随机 3–6 秒").first()).toBeVisible()
  await expect(page.getByLabel("下载视频")).toHaveCount(0)

  await page.getByRole("button", { name: "创建并运行" }).click()
  await expect(page.getByText("请填写搜索关键词")).toBeVisible()
})

test("separates collection and media jobs into related management tabs", async ({
  page,
}) => {
  const readyTaskId = "a1111111-1111-4111-8111-111111111111"
  const waitingTaskId = "b2222222-2222-4222-8222-222222222222"
  const now = new Date().toISOString()
  await page.route("**/api/v1/douyin/media-tasks**", async (route) => {
    await route.fulfill({
      json: {
        count: 2,
        data: [
          {
            source_task_id: readyTaskId,
            track_id: "00d5dae3-5481-4a36-ac38-e91a7abcee51",
            track_name: "默认赛道",
            track_is_default: true,
            source_title: "露营装备合集",
            source_author: "露营达人",
            source_creator_names: [],
            crawl_type: "creator",
            crawl_status: "succeeded",
            checkpoint_phase: "completed",
            source_request: { max_awemes: 20 },
            eligible_count: 20,
            dependency_ready: true,
            dependency_message: "来源采集已完成，可处理 20 条作品",
            status: "ready",
            summary: emptyMediaSummary(),
            created_at: now,
            finished_at: now,
          },
          {
            source_task_id: waitingTaskId,
            track_id: "00d5dae3-5481-4a36-ac38-e91a7abcee51",
            track_name: "默认赛道",
            track_is_default: true,
            source_title: null,
            source_author: null,
            source_creator_names: ["新达人"],
            crawl_type: "creator",
            crawl_status: "running",
            checkpoint_phase: "crawl",
            source_request: { max_awemes: 10 },
            eligible_count: 3,
            dependency_ready: false,
            dependency_message: "来源采集正在执行，当前已产出 3 条",
            status: "waiting_source",
            summary: emptyMediaSummary(),
            created_at: now,
            finished_at: null,
          },
        ],
      },
    })
  })

  await page.goto("/douyin")
  await page.getByRole("tab", { name: "下载与字幕" }).click()
  await expect(
    page.getByRole("columnheader", { name: "来源采集任务" }),
  ).toBeVisible()
  await expect(page.getByRole("button", { name: /可创建 1/ })).toBeVisible()
  await expect(page.getByText("来源采集已完成，可处理 20 条作品")).toBeVisible()
  await expect(page.getByRole("button", { name: "创建下载任务" })).toBeVisible()
  await expect(
    page.getByText("等待采集", { exact: true }).first(),
  ).toBeVisible()
  await page.getByRole("button", { name: "横条" }).click()
  await expect(page.getByText("露营装备合集")).toBeVisible()
  await page.getByRole("button", { name: "卡片" }).click()
  await expect(page.getByText("作者：露营达人")).toBeVisible()
})

test("restarts a failed task from the task list", async ({ page }) => {
  const taskId = "9a3f7e2c-1c4d-4a6b-8c9e-0f5a2b3c4d5e"
  const now = new Date().toISOString()
  let restartRequested = false

  await page.route("**/api/v1/douyin/tasks?**", async (route) => {
    await route.fulfill({
      json: {
        count: 1,
        data: [
          {
            id: taskId,
            owner_id: "c7e0bb1c-891a-4b4a-8f12-26c1ddd8239d",
            account_id: null,
            account_pool_id: null,
            account_strategy: "least_loaded",
            crawl_type: "search",
            status: "failed",
            request: { keywords: ["露营"] },
            aweme_count: 0,
            comment_count: 0,
            action_count: 0,
            checkpoint_phase: "crawl",
            resume_count: 0,
            can_resume_crawl: false,
            can_resume_media: false,
            error: "RuntimeError: boom",
            has_qrcode: false,
            created_at: now,
            started_at: now,
            finished_at: now,
            last_resumed_at: null,
          },
        ],
      },
    })
  })
  await page.route(
    `**/api/v1/douyin/tasks/${taskId}/restart`,
    async (route) => {
      restartRequested = true
      await route.fulfill({
        status: 202,
        json: {
          id: taskId,
          owner_id: "c7e0bb1c-891a-4b4a-8f12-26c1ddd8239d",
          account_id: null,
          account_pool_id: null,
          account_strategy: "least_loaded",
          crawl_type: "search",
          status: "queued",
          request: { keywords: ["露营"] },
          aweme_count: 0,
          comment_count: 0,
          action_count: 0,
          checkpoint_phase: "crawl",
          resume_count: 1,
          can_resume_crawl: true,
          can_resume_media: false,
          error: null,
          has_qrcode: false,
          created_at: now,
          started_at: now,
          finished_at: null,
          last_resumed_at: now,
        },
      })
    },
  )
  page.on("dialog", (dialog) => dialog.accept())

  await page.goto("/douyin")

  await page.getByRole("button", { name: "横条" }).click()
  await expect(page.getByText("系统默认", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: "卡片" }).click()
  await expect(page.getByText("作品", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: "表格" }).click()
  await expect(
    page.getByRole("columnheader", { name: "所属赛道" }),
  ).toBeVisible()

  await page.getByRole("button", { name: /管理任务/ }).click()
  const restartButton = page.getByRole("menuitem", { name: "从头重启" })
  await expect(restartButton).toBeVisible()
  await restartButton.click()
  await expect(page.getByText("任务已清空断点并从头重新入队")).toBeVisible()
  expect(restartRequested).toBe(true)
})

test("resumes a failed task with a replacement account", async ({ page }) => {
  const taskId = "9a3f7e2c-1c4d-4a6b-8c9e-0f5a2b3c4d6f"
  const oldAccountId = "11111111-1111-4111-8111-111111111111"
  const replacementAccountId = "22222222-2222-4222-8222-222222222222"
  const now = new Date().toISOString()
  let resumeBody: Record<string, unknown> | null = null
  const taskPayload = {
    id: taskId,
    owner_id: "c7e0bb1c-891a-4b4a-8f12-26c1ddd8239d",
    track_id: "00d5dae3-5481-4a36-ac38-e91a7abcee51",
    track_name: "默认赛道",
    track_is_default: true,
    account_id: oldAccountId,
    account_name: "大号",
    account_pool_id: null,
    account_pool_name: null,
    account_strategy: "least_loaded",
    crawl_type: "creator",
    status: "failed",
    request: {
      crawl_type: "creator",
      login_type: "qrcode",
      creator_ids: ["creator-target"],
    },
    aweme_count: 181,
    comment_count: 0,
    action_count: 0,
    checkpoint_phase: "crawl",
    resume_count: 2,
    can_resume_crawl: true,
    can_resume_media: false,
    error: "原账号异常",
    has_qrcode: false,
    created_at: now,
    started_at: now,
    finished_at: now,
    last_resumed_at: now,
  }

  await page.route("**/api/v1/douyin/accounts?**", async (route) => {
    await route.fulfill({
      json: {
        count: 2,
        data: [
          {
            id: oldAccountId,
            name: "大号",
            status: "unhealthy",
            is_logged_in: true,
          },
          {
            id: replacementAccountId,
            name: "小号",
            status: "ready",
            is_logged_in: true,
          },
        ],
      },
    })
  })
  await page.route(`**/api/v1/douyin/tasks/${taskId}**`, async (route) => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname.endsWith("/resume")) {
      resumeBody = route.request().postDataJSON()
      await route.fulfill({
        status: 202,
        json: {
          ...taskPayload,
          account_id: replacementAccountId,
          account_name: "小号",
          status: "queued",
          error: null,
          resume_count: 3,
        },
      })
      return
    }
    if (pathname.endsWith("/media-summary")) {
      await route.fulfill({
        json: {
          total: 0,
          queued: 0,
          downloading: 0,
          downloaded: 0,
          download_failed: 0,
          subtitle_pending: 0,
          subtitle_running: 0,
          subtitle_completed: 0,
          subtitle_failed: 0,
          ...emptyMigrationSummary,
        },
      })
      return
    }
    if (pathname.endsWith("/shards")) {
      await route.fulfill({ json: { data: [], count: 0 } })
      return
    }
    await route.fulfill({ json: taskPayload })
  })

  await page.goto(`/douyin/${taskId}`)
  await page.getByRole("button", { name: "继续任务" }).click()
  await page.getByLabel("恢复执行账号").click()
  await page.getByRole("option", { name: "改用账号 · 小号" }).click()
  await page.getByRole("button", { name: "确认继续" }).click()

  await expect.poll(() => resumeBody).not.toBeNull()
  expect(resumeBody).toMatchObject({
    resume_crawl: true,
    resume_media: false,
    account_id: replacementAccountId,
  })
  await expect(page.getByText("恢复请求已受理")).toBeVisible()
})

test("clears a stale session when its user no longer exists", async ({
  page,
}) => {
  await page.route("**/api/v1/users/me", async (route) => {
    await route.fulfill({
      status: 404,
      contentType: "application/json",
      json: { detail: "User not found" },
    })
  })

  await page.goto("/douyin")

  await page.waitForURL("/login")
  expect(
    await page.evaluate(() => localStorage.getItem("access_token")),
  ).toBeNull()
})

test("renders a waiting-login task and its protected QR code", async ({
  page,
}) => {
  const taskId = "38a8148c-c8b6-4c6c-b7c4-93580d687388"
  const now = new Date().toISOString()
  const png = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
    "base64",
  )

  await page.route(`**/api/v1/douyin/tasks/${taskId}**`, async (route) => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname.endsWith("/media-summary")) {
      await route.fulfill({
        json: {
          total: 0,
          queued: 0,
          downloading: 0,
          downloaded: 0,
          download_failed: 0,
          subtitle_pending: 0,
          subtitle_running: 0,
          subtitle_completed: 0,
          subtitle_failed: 0,
          ...emptyMigrationSummary,
        },
      })
      return
    }
    if (pathname.endsWith("/media")) {
      await route.fulfill({ json: { data: [], count: 0 } })
      return
    }
    if (pathname.endsWith("/qrcode")) {
      await route.fulfill({ status: 200, contentType: "image/png", body: png })
      return
    }
    if (pathname.endsWith("/awemes")) {
      await route.fulfill({ json: { data: [], count: 0 } })
      return
    }
    await route.fulfill({
      json: {
        id: taskId,
        owner_id: "c7e0bb1c-891a-4b4a-8f12-26c1ddd8239d",
        crawl_type: "search",
        status: "waiting_login",
        request: {
          crawl_type: "search",
          login_type: "qrcode",
          keywords: ["FastAPI"],
          max_awemes: 10,
        },
        aweme_count: 0,
        comment_count: 0,
        action_count: 0,
        error: null,
        has_qrcode: true,
        created_at: now,
        started_at: now,
        finished_at: null,
      },
    })
  })

  await page.goto(`/douyin/${taskId}`)

  await expect(
    page.getByText("等待扫码登录", { exact: true }).last(),
  ).toBeVisible()
  await expect(page.getByAltText("抖音登录二维码")).toBeVisible()
  await page.getByText("任务配置", { exact: true }).click()
  const taskConfig = page.getByRole("group").filter({ hasText: "任务配置" })
  await expect(taskConfig.getByText("FastAPI", { exact: true })).toBeVisible()
})

test("shows an accepted media resume with actionable live progress", async ({
  page,
}) => {
  const taskId = "0dfdf538-0bf9-43f2-94a6-b2757840f81d"
  const assetId = "58a8148c-c8b6-4c6c-b7c4-93580d687300"
  const now = new Date().toISOString()

  await page.route(`**/api/v1/douyin/tasks/${taskId}**`, async (route) => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname.endsWith("/media-summary")) {
      await route.fulfill({
        json: {
          ...emptyMigrationSummary,
          total: 14,
          queued: 4,
          downloading: 3,
          downloaded: 6,
          download_failed: 1,
          subtitle_pending: 0,
          subtitle_running: 0,
          subtitle_completed: 6,
          subtitle_failed: 0,
          local_downloaded: 6,
          minio_downloaded: 0,
        },
      })
      return
    }
    if (pathname.endsWith("/works")) {
      await route.fulfill({
        json: {
          count: 1,
          data: [
            {
              aweme: {
                id: "78a8148c-c8b6-4c6c-b7c4-93580d687300",
                task_id: taskId,
                aweme_id: "7647937915624551281",
                aweme_type: "0",
                title: "恢复中的视频",
                description: "",
                create_time: 1_700_000_000,
                creator_hash: "creator-hash",
                sec_uid: "anonymous-sec-uid",
                nickname: "测**户",
                liked_count: 10,
                collected_count: 2,
                comment_count: 1,
                share_count: 0,
                aweme_url: "",
                cover_url: "",
                video_download_url: "",
                music_download_url: "",
                note_download_url: "",
                source_keyword: "恢复",
                fetched_at: now,
              },
              persisted_comment_count: 0,
              media: {
                id: assetId,
                task_id: taskId,
                aweme_id: "7647937915624551281",
                storage_backend: "local",
                status: "downloading",
                progress: 6,
                attempt_count: 3,
                mime_type: "video/mp4",
                file_size: 0,
                sha256: "",
                error: null,
                download_available: false,
                created_at: now,
                updated_at: now,
                completed_at: null,
                ...idleMediaMigration,
                subtitle: null,
              },
            },
          ],
        },
      })
      return
    }
    if (pathname.endsWith("/media")) {
      await route.fulfill({ json: { data: [], count: 0 } })
      return
    }
    if (pathname.endsWith("/awemes")) {
      await route.fulfill({ json: { data: [], count: 0 } })
      return
    }
    await route.fulfill({
      json: {
        id: taskId,
        owner_id: "c7e0bb1c-891a-4b4a-8f12-26c1ddd8239d",
        crawl_type: "search",
        status: "processing_media",
        request: {
          crawl_type: "search",
          keywords: ["恢复"],
          download_media: true,
          translate_subtitles: true,
        },
        aweme_count: 14,
        comment_count: 91,
        action_count: 0,
        checkpoint_phase: "completed",
        resume_count: 3,
        can_resume_crawl: false,
        can_resume_media: false,
        error: null,
        has_qrcode: false,
        created_at: now,
        started_at: now,
        finished_at: null,
        last_resumed_at: now,
      },
    })
  })

  await page.goto(`/douyin/${taskId}`)

  await expect(page.getByText("已恢复 3 次 · 媒体处理")).toBeVisible()
  await expect(page.getByText("第 3 次恢复正在执行")).toBeVisible()
  await page.getByRole("tab", { name: /^作品数据/ }).click()
  await expect(page.getByText("第 3 次恢复正在处理媒体")).toBeVisible()
  await expect(
    page.getByText("下载中 3 条，排队 4 条，下载失败 1 条", { exact: false }),
  ).toBeVisible()
  await expect(page.getByText("视频完成").locator("..")).toContainText("6 / 14")
  await expect(page.getByText("已尝试 3 次", { exact: false })).toBeVisible()
})

test("shows media progress, persisted subtitle and retranslation action", async ({
  page,
}) => {
  const taskId = "48a8148c-c8b6-4c6c-b7c4-93580d687399"
  const assetId = "58a8148c-c8b6-4c6c-b7c4-93580d687399"
  const secondAssetId = "58a8148c-c8b6-4c6c-b7c4-93580d687398"
  const now = new Date().toISOString()
  let retranslateCalls = 0
  let previewSessionCalls = 0
  let previewStreamCalls = 0
  let previewSessionUrl = ""

  await page.route(`**/api/v1/douyin/tasks/${taskId}**`, async (route) => {
    const url = new URL(route.request().url())
    const pathname = url.pathname
    if (pathname.endsWith(`/media/${assetId}/preview-session`)) {
      previewSessionCalls += 1
      previewSessionUrl = url.toString()
      await route.fulfill({
        status: 201,
        json: { message: "Media preview session created" },
      })
      return
    }
    if (pathname.endsWith(`/media/${assetId}/preview`)) {
      previewStreamCalls += 1
      await route.fulfill({
        status: 206,
        contentType: "video/mp4",
        headers: {
          "Accept-Ranges": "bytes",
          "Content-Range": "bytes 0-3/4",
          "Content-Length": "4",
        },
        body: Buffer.from([0, 0, 0, 0]),
      })
      return
    }
    if (pathname.endsWith(`/media/${secondAssetId}/preview-session`)) {
      await route.fulfill({
        status: 201,
        json: { message: "Media preview session created" },
      })
      return
    }
    if (pathname.endsWith(`/media/${secondAssetId}/preview`)) {
      await route.fulfill({
        status: 206,
        contentType: "video/mp4",
        headers: {
          "Accept-Ranges": "bytes",
          "Content-Range": "bytes 0-3/4",
          "Content-Length": "4",
        },
        body: Buffer.from([0, 0, 0, 0]),
      })
      return
    }
    if (pathname.endsWith(`/media/${assetId}/retranslate`)) {
      retranslateCalls += 1
      await route.fulfill({ json: { message: "Subtitle translation queued" } })
      return
    }
    if (pathname.endsWith("/works")) {
      await route.fulfill({
        json: {
          count: 2,
          data: [
            {
              aweme: {
                id: "78a8148c-c8b6-4c6c-b7c4-93580d687390",
                task_id: taskId,
                aweme_id: "123456",
                aweme_type: "0",
                title: "可预览的视频",
                description: "",
                create_time: 1_700_000_000,
                creator_hash: "creator-hash",
                sec_uid: "anonymous-sec-uid",
                nickname: "测**户",
                liked_count: 10,
                collected_count: 2,
                comment_count: 1,
                share_count: 0,
                aweme_url: "https://www.douyin.com/video/123456",
                cover_url: "",
                video_download_url: "",
                music_download_url: "",
                note_download_url: "",
                source_keyword: "测试",
                fetched_at: now,
              },
              persisted_comment_count: 0,
              media: {
                id: assetId,
                task_id: taskId,
                aweme_id: "123456",
                storage_backend: "local",
                status: "downloaded",
                progress: 100,
                attempt_count: 1,
                mime_type: "video/mp4",
                file_size: 1024,
                sha256: "abc",
                error: null,
                download_available: true,
                created_at: now,
                updated_at: now,
                completed_at: now,
                ...idleMediaMigration,
                subtitle: {
                  id: "68a8148c-c8b6-4c6c-b7c4-93580d687399",
                  asset_id: assetId,
                  task_id: taskId,
                  aweme_id: "123456",
                  status: "completed",
                  progress: 100,
                  attempt_count: 1,
                  requested_backend: "api",
                  actual_backend: "api",
                  model: "whisper-1",
                  language: "zh",
                  duration_seconds: 3,
                  full_text: "这是远程 API 返回的字幕",
                  segments: [],
                  error: null,
                  created_at: now,
                  started_at: now,
                  finished_at: now,
                },
              },
            },
            {
              aweme: {
                id: "78a8148c-c8b6-4c6c-b7c4-93580d687391",
                task_id: taskId,
                aweme_id: "654321",
                aweme_type: "0",
                title: "可滑动切换的视频",
                description: "",
                create_time: 1_699_999_000,
                creator_hash: "creator-hash-2",
                sec_uid: "anonymous-sec-uid-2",
                nickname: "另一个作者",
                liked_count: 8,
                collected_count: 1,
                comment_count: 2,
                share_count: 1,
                aweme_url: "",
                cover_url: "",
                video_download_url: "",
                music_download_url: "",
                note_download_url: "",
                source_keyword: "测试",
                fetched_at: now,
              },
              persisted_comment_count: 1,
              media: {
                id: secondAssetId,
                task_id: taskId,
                aweme_id: "654321",
                storage_backend: "minio",
                status: "downloaded",
                progress: 100,
                attempt_count: 1,
                mime_type: "video/mp4",
                file_size: 2048,
                sha256: "def",
                error: null,
                download_available: true,
                created_at: now,
                updated_at: now,
                completed_at: now,
                ...idleMediaMigration,
                subtitle: null,
              },
            },
          ],
        },
      })
      return
    }
    if (pathname.endsWith("/media-summary")) {
      await route.fulfill({
        json: {
          total: 2,
          queued: 0,
          downloading: 0,
          downloaded: 2,
          download_failed: 0,
          subtitle_pending: 0,
          subtitle_running: 0,
          subtitle_completed: 1,
          subtitle_failed: 0,
          ...emptyMigrationSummary,
        },
      })
      return
    }
    if (pathname.endsWith("/media")) {
      await route.fulfill({
        json: {
          count: 1,
          data: [
            {
              id: assetId,
              task_id: taskId,
              aweme_id: "123456",
              storage_backend: "local",
              status: "downloaded",
              progress: 100,
              attempt_count: 1,
              mime_type: "video/mp4",
              file_size: 1024,
              sha256: "abc",
              error: null,
              download_available: true,
              created_at: now,
              updated_at: now,
              completed_at: now,
              ...idleMediaMigration,
              subtitle: {
                id: "68a8148c-c8b6-4c6c-b7c4-93580d687399",
                asset_id: assetId,
                task_id: taskId,
                aweme_id: "123456",
                status: "completed",
                progress: 100,
                attempt_count: 1,
                requested_backend: "api",
                actual_backend: "api",
                model: "whisper-1",
                language: "zh",
                duration_seconds: 3,
                full_text: "这是远程 API 返回的字幕",
                segments: [],
                error: null,
                created_at: now,
                started_at: now,
                finished_at: now,
              },
            },
          ],
        },
      })
      return
    }
    if (pathname.endsWith("/awemes")) {
      await route.fulfill({ json: { data: [], count: 0 } })
      return
    }
    await route.fulfill({
      json: {
        id: taskId,
        owner_id: "c7e0bb1c-891a-4b4a-8f12-26c1ddd8239d",
        crawl_type: "detail",
        status: "succeeded",
        request: {
          crawl_type: "detail",
          video_ids: ["123456"],
          download_media: true,
          translate_subtitles: true,
        },
        aweme_count: 1,
        comment_count: 0,
        action_count: 0,
        error: null,
        has_qrcode: false,
        created_at: now,
        started_at: now,
        finished_at: now,
      },
    })
  })

  await page.goto(`/douyin/${taskId}`)

  await expect(
    page.getByRole("tab", { name: "任务概览", exact: true }),
  ).toHaveAttribute("aria-selected", "true")
  await page.getByRole("tab", { name: /^作品数据/ }).click()
  await expect(page.getByRole("tab", { name: /^作品数据/ })).toHaveAttribute(
    "aria-selected",
    "true",
  )
  await expect(page.getByRole("tab", { name: /^互动记录/ })).toBeVisible()

  const tableView = page.getByRole("tab", { name: "表格", exact: true })
  const rowView = page.getByRole("tab", { name: "横条", exact: true })
  const cardView = page.getByRole("tab", { name: "卡片", exact: true })
  await expect(tableView).toHaveAttribute("aria-selected", "true")
  await rowView.click()
  await expect(page.getByRole("list", { name: "作品横条列表" })).toBeVisible()
  await expect(page.getByText("可预览的视频", { exact: true })).toBeVisible()
  await cardView.click()
  await expect(page.getByRole("list", { name: "作品卡片列表" })).toBeVisible()
  await tableView.click()
  await expect(tableView).toHaveAttribute("aria-selected", "true")

  await expect(page.getByText("zh · 已完成", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: "预览视频" }).first().click()
  await expect(page.getByRole("heading", { name: "视频预览" })).toBeVisible()
  await expect(page.locator("video")).toHaveAttribute(
    "src",
    new RegExp(`/media/${assetId}/preview\\?v=`),
  )
  await expect.poll(() => previewSessionCalls).toBe(1)
  expect(new URL(previewSessionUrl).origin).toBe(new URL(page.url()).origin)
  await expect.poll(() => previewStreamCalls).toBeGreaterThan(0)
  await page.getByRole("button", { name: "关闭" }).click()
  const workMenu = page.getByRole("button", {
    name: /更多作品操作：可预览的视频/,
  })
  await workMenu.click()
  await page.getByRole("menuitem", { name: "重新翻译" }).click()
  await expect.poll(() => retranslateCalls).toBe(1)
  await workMenu.click()
  await expect(
    page.getByRole("menuitem", { name: "在抖音中打开视频" }),
  ).toHaveAttribute("href", "https://www.douyin.com/video/123456")

  await page.getByRole("menuitem", { name: "沉浸播放" }).click()
  await expect(page).toHaveURL(new RegExp(`/douyin/${taskId}/feed`))
  await expect(page.getByText("1 / 2", { exact: true })).toBeVisible()
  await page.keyboard.press("ArrowDown")
  await expect(page.getByText("2 / 2", { exact: true })).toBeVisible()
  await expect(
    page.getByText("可滑动切换的视频", { exact: true }).first(),
  ).toBeVisible()
})

test("shows per-video comments and creates follow-up crawl tasks", async ({
  page,
}) => {
  const taskId = "78a8148c-c8b6-4c6c-b7c4-93580d687399"
  const childTaskId = "88a8148c-c8b6-4c6c-b7c4-93580d687399"
  const awemeId = "7390000000000000001"
  const now = new Date().toISOString()
  let recrawlCalls = 0

  const taskPayload = (id: string, crawlType = "search") => ({
    id,
    owner_id: "c7e0bb1c-891a-4b4a-8f12-26c1ddd8239d",
    crawl_type: crawlType,
    status: "succeeded",
    request:
      crawlType === "detail"
        ? { crawl_type: "detail", video_ids: [awemeId] }
        : { crawl_type: "search", keywords: ["作品操作"] },
    aweme_count: id === taskId ? 1 : 0,
    comment_count: id === taskId ? 1 : 0,
    action_count: 0,
    checkpoint_phase: "completed",
    resume_count: 0,
    can_resume_crawl: false,
    can_resume_media: false,
    error: null,
    has_qrcode: false,
    created_at: now,
    started_at: now,
    finished_at: now,
    last_resumed_at: null,
  })

  await page.route("**/api/v1/douyin/tasks/**", async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const pathname = url.pathname
    if (pathname.endsWith(`/awemes/${awemeId}/comments/recrawl`)) {
      const body = request.postDataJSON()
      expect(body.max_comments_per_aweme).toBe(12)
      expect(body.fetch_sub_comments).toBe(true)
      recrawlCalls += 1
      await route.fulfill({ json: taskPayload(childTaskId, "detail") })
      return
    }
    if (pathname.endsWith("/works")) {
      await route.fulfill({
        json: pathname.includes(taskId)
          ? {
              count: 1,
              data: [
                {
                  aweme: {
                    id: "98a8148c-c8b6-4c6c-b7c4-93580d687399",
                    task_id: taskId,
                    aweme_id: awemeId,
                    aweme_type: "0",
                    title: "可操作的视频",
                    description: "",
                    create_time: 1_700_000_000,
                    creator_hash: "creator-hash",
                    sec_uid: "anonymous-sec-uid",
                    nickname: "测**户",
                    liked_count: 10,
                    collected_count: 2,
                    comment_count: 1,
                    share_count: 0,
                    aweme_url: `https://www.douyin.com/video/${awemeId}`,
                    cover_url: "",
                    video_download_url: "",
                    music_download_url: "",
                    note_download_url: "",
                    source_keyword: "作品操作",
                    fetched_at: now,
                  },
                  persisted_comment_count: 1,
                  media: null,
                },
              ],
            }
          : { data: [], count: 0 },
      })
      return
    }
    if (pathname.endsWith("/media-summary")) {
      await route.fulfill({
        json: {
          total: 0,
          queued: 0,
          downloading: 0,
          downloaded: 0,
          download_failed: 0,
          subtitle_pending: 0,
          subtitle_running: 0,
          subtitle_completed: 0,
          subtitle_failed: 0,
          ...emptyMigrationSummary,
        },
      })
      return
    }
    if (pathname.endsWith("/media")) {
      await route.fulfill({ json: { data: [], count: 0 } })
      return
    }
    if (pathname.endsWith("/awemes")) {
      await route.fulfill({
        json: pathname.includes(taskId)
          ? {
              count: 1,
              data: [
                {
                  id: "98a8148c-c8b6-4c6c-b7c4-93580d687399",
                  task_id: taskId,
                  aweme_id: awemeId,
                  aweme_type: "0",
                  title: "可操作的视频",
                  description: "",
                  create_time: null,
                  creator_hash: "creator-hash",
                  sec_uid: "anonymous-sec-uid",
                  nickname: "测***户",
                  liked_count: 10,
                  collected_count: 2,
                  comment_count: 1,
                  share_count: 0,
                  aweme_url: `https://www.douyin.com/video/${awemeId}`,
                  cover_url: "",
                  video_download_url: "",
                  music_download_url: "",
                  note_download_url: "",
                  source_keyword: "作品操作",
                  fetched_at: now,
                },
              ],
            }
          : { data: [], count: 0 },
      })
      return
    }
    if (pathname.endsWith("/comments")) {
      expect(url.searchParams.get("aweme_id")).toBe(awemeId)
      await route.fulfill({
        json: {
          count: 1,
          data: [
            {
              id: "a8a8148c-c8b6-4c6c-b7c4-93580d687399",
              task_id: taskId,
              comment_id: "comment-1",
              aweme_id: awemeId,
              parent_comment_id: "0",
              content: "这是这个视频的评论",
              create_time: 1_700_000_000,
              creator_hash: "commenter-hash",
              sec_uid: "anonymous-commenter",
              nickname: "评***户",
              sub_comment_count: 2,
              like_count: 3,
              pictures: "",
              fetched_at: now,
            },
          ],
        },
      })
      return
    }
    await route.fulfill({
      json: pathname.includes(childTaskId)
        ? taskPayload(childTaskId, "detail")
        : taskPayload(taskId),
    })
  })

  await page.goto(`/douyin/${taskId}`)
  await page.getByRole("tab", { name: /^作品数据/ }).click()
  await expect(page.getByText("可操作的视频")).toBeVisible()

  const actionsMenu = page.getByRole("button", {
    name: /更多作品操作：可操作的视频/,
  })
  await actionsMenu.click()
  await page.getByRole("menuitem", { name: "查看评论" }).click()
  await expect(page.getByText("这是这个视频的评论")).toBeVisible()
  await page.keyboard.press("Escape")

  await actionsMenu.click()
  await page.getByRole("menuitem", { name: "作者作品" }).click()
  await expect(page.getByText("最大作者作品数")).toBeVisible()
  await expect(page.getByText("同时抓取每个作品的评论")).toBeVisible()
  await page.keyboard.press("Escape")

  await actionsMenu.click()
  await page.getByRole("menuitem", { name: "重爬评论" }).click()
  await page.getByLabel("每个视频最大评论数").fill("12")
  await page.getByText("抓取子评论", { exact: true }).click()
  await page.getByRole("button", { name: "创建并进入任务" }).click()

  await expect.poll(() => recrawlCalls).toBe(1)
  await page.waitForURL(`/douyin/${childTaskId}`)
})

test("uploads local media to MinIO only after explicit confirmation", async ({
  page,
}) => {
  const taskId = "b8a8148c-c8b6-4c6c-b7c4-93580d687399"
  const assetId = "c8a8148c-c8b6-4c6c-b7c4-93580d687399"
  const now = new Date().toISOString()
  let migrationCalls = 0

  await page.route(`**/api/v1/douyin/tasks/${taskId}**`, async (route) => {
    const request = route.request()
    const pathname = new URL(request.url()).pathname
    if (pathname.endsWith("/media/migrate-to-minio")) {
      expect(request.postDataJSON()).toEqual({ asset_ids: [] })
      migrationCalls += 1
      await route.fulfill({
        status: 202,
        json: { queued: 1, skipped: 0, message: "Queued 1 media migrations" },
      })
      return
    }
    if (pathname.endsWith("/media-summary")) {
      await route.fulfill({
        json: {
          total: 1,
          queued: 0,
          downloading: 0,
          downloaded: 1,
          download_failed: 0,
          subtitle_pending: 0,
          subtitle_running: 0,
          subtitle_completed: 0,
          subtitle_failed: 0,
          local_downloaded: 1,
          minio_downloaded: 0,
          migration_queued: 0,
          migration_running: 0,
          migration_cleanup_pending: 0,
          migration_completed: 0,
          migration_failed: 0,
        },
      })
      return
    }
    if (pathname.endsWith("/media")) {
      await route.fulfill({
        json: {
          count: 1,
          data: [
            {
              id: assetId,
              task_id: taskId,
              aweme_id: "7654321",
              storage_backend: "local",
              status: "downloaded",
              progress: 100,
              attempt_count: 1,
              mime_type: "video/mp4",
              file_size: 1024,
              sha256: "abc",
              error: null,
              download_available: true,
              created_at: now,
              updated_at: now,
              completed_at: now,
              migration_status: "idle",
              migration_progress: 0,
              migration_attempt_count: 0,
              migration_error: null,
              migration_started_at: null,
              migration_finished_at: null,
              subtitle: null,
            },
          ],
        },
      })
      return
    }
    if (pathname.endsWith("/awemes")) {
      await route.fulfill({ json: { data: [], count: 0 } })
      return
    }
    await route.fulfill({
      json: {
        id: taskId,
        owner_id: "c7e0bb1c-891a-4b4a-8f12-26c1ddd8239d",
        crawl_type: "detail",
        status: "succeeded",
        request: { crawl_type: "detail", video_ids: ["7654321"] },
        aweme_count: 1,
        comment_count: 0,
        action_count: 0,
        checkpoint_phase: "completed",
        resume_count: 0,
        can_resume_crawl: false,
        can_resume_media: false,
        error: null,
        has_qrcode: false,
        created_at: now,
        started_at: now,
        finished_at: now,
        last_resumed_at: null,
      },
    })
  })

  await page.goto(`/douyin/${taskId}`)
  await page.getByRole("tab", { name: /^作品数据/ }).click()
  await page.getByRole("button", { name: "上传本地视频到云端（1）" }).click()
  await expect(
    page.getByText("完整回读校验通过后才会删除本地文件"),
  ).toBeVisible()
  await page.getByRole("button", { name: "确认上传并迁移" }).click()

  await expect.poll(() => migrationCalls).toBe(1)
  await expect(page.getByText("已提交 1 个视频迁移任务")).toBeVisible()
})

test("filters the cross-task video library and shows publish metadata", async ({
  page,
}) => {
  const taskId = "d8a8148c-c8b6-4c6c-b7c4-93580d687399"
  const assetId = "e8a8148c-c8b6-4c6c-b7c4-93580d687399"
  const now = new Date().toISOString()
  let observedSearch = ""
  let observedTag = ""
  let observedLimit = ""
  let migrationCalls = 0
  const tagId = "a8a8148c-c8b6-4c6c-b7c4-93580d687399"

  await page.route("**/api/v1/douyin/tags/**", async (route) => {
    await route.fulfill({
      json: {
        count: 1,
        data: [
          {
            id: tagId,
            name: "运营标签",
            aweme_count: 1,
            task_count: 1,
            last_seen_at: now,
            created_at: now,
          },
        ],
      },
    })
  })

  await page.route("**/api/v1/douyin/library/**", async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (
      request.method() === "POST" &&
      url.pathname.endsWith("/media/migrate-to-minio")
    ) {
      migrationCalls += 1
      expect(request.postDataJSON()).toEqual({ subtitle_status: "all" })
      await route.fulfill({
        status: 202,
        json: {
          queued: 1,
          skipped: 0,
          message: "已将 1 个本地视频加入 MinIO 迁移队列",
        },
      })
      return
    }
    if (url.pathname.endsWith("/creators")) {
      await route.fulfill({
        json: {
          count: 1,
          data: [
            {
              creator_hash: "creator-library",
              nickname: "资源库作者",
              work_count: 1,
            },
          ],
        },
      })
      return
    }
    observedSearch = url.searchParams.get("search") || ""
    observedTag = url.searchParams.get("tag_id") || ""
    observedLimit = url.searchParams.get("limit") || ""
    await route.fulfill({
      json: {
        count: 1,
        data: [
          {
            aweme: {
              id: "f8a8148c-c8b6-4c6c-b7c4-93580d687399",
              task_id: taskId,
              aweme_id: "7650000000000000001",
              aweme_type: "0",
              title: "资源库中的视频",
              description: "用于验证全局检索",
              create_time: 1_700_000_000,
              creator_hash: "creator-library",
              sec_uid: "anonymous-sec-uid",
              nickname: "资源库作者",
              liked_count: 1200,
              collected_count: 88,
              comment_count: 36,
              share_count: 9,
              aweme_url: "https://www.douyin.com/video/7650000000000000001",
              cover_url: "",
              video_download_url: "",
              music_download_url: "",
              note_download_url: "",
              source_keyword: "资源库",
              fetched_at: now,
            },
            persisted_comment_count: 10,
            tags: [{ id: tagId, name: "运营标签" }],
            media: {
              id: assetId,
              task_id: taskId,
              aweme_id: "7650000000000000001",
              storage_backend: "local",
              status: "downloaded",
              progress: 100,
              attempt_count: 1,
              mime_type: "video/mp4",
              file_size: 1048576,
              sha256: "abc",
              error: null,
              download_available: true,
              created_at: now,
              updated_at: now,
              completed_at: now,
              ...idleMediaMigration,
              subtitle: null,
            },
          },
        ],
      },
    })
  })
  await page.route("**/api/v1/douyin/tasks?**", async (route) => {
    await route.fulfill({ json: { data: [], count: 0 } })
  })

  await page.goto("/douyin-library")
  await page.getByRole("button", { name: "卡片" }).click()
  await expect(page.getByRole("heading", { name: "视频资源库" })).toBeVisible()
  await expect(page.getByText("资源库中的视频")).toBeVisible()
  await expect(page.getByText("资源库作者").first()).toBeVisible()
  await expect(page.getByText("#运营标签", { exact: true })).toBeVisible()
  await expect(page.getByText("10").first()).toBeVisible()
  await expect(page.getByText("来源 资源库", { exact: true })).toBeVisible()
  await expect(page.getByText("本地", { exact: true }).first()).toBeVisible()
  await expect(page.getByText("无字幕").first()).toBeVisible()
  await expect(page.locator('span[title="分享"]')).toBeVisible()
  expect(observedLimit).toBe("32")
  await expect(
    page.getByRole("link", { name: "在抖音中打开视频" }),
  ).toHaveAttribute("href", "https://www.douyin.com/video/7650000000000000001")
  const immersiveLinks = page.getByRole("link", { name: "沉浸播放" })
  await expect(immersiveLinks).toHaveCount(2)
  await expect(immersiveLinks.last()).toHaveAttribute(
    "href",
    /\/douyin-library\/feed\?.*start=video-7650000000000000001/,
  )

  page.once("dialog", (dialog) => dialog.accept())
  await page.getByRole("button", { name: "本地视频转云端" }).click()
  await expect.poll(() => migrationCalls).toBe(1)

  await page.getByPlaceholder("搜索标题、描述、创作者或作品号").fill("全局检索")
  await expect.poll(() => observedSearch).toBe("全局检索")
  await page.getByText("全部标签", { exact: true }).click()
  await page.getByRole("option", { name: "#运营标签（1）" }).click()
  await expect.poll(() => observedTag).toBe(tagId)

  await immersiveLinks.first().click()
  await expect(page).toHaveURL(/\/douyin-library\/feed/)
  await expect(page.getByText("1 / 1", { exact: true })).toBeVisible()
})

test("manages extracted tags and synchronizes historical works", async ({
  page,
}) => {
  const tagId = "b8a8148c-c8b6-4c6c-b7c4-93580d687399"
  const now = new Date().toISOString()
  let syncCalls = 0
  await page.route("**/api/v1/douyin/tags/**", async (route) => {
    if (route.request().method() === "POST") {
      syncCalls += 1
      await route.fulfill({
        json: {
          aweme_count: 14,
          tag_count: 6,
          created_count: 2,
          binding_count: 8,
        },
      })
      return
    }
    await route.fulfill({
      json: {
        count: 1,
        data: [
          {
            id: tagId,
            name: "FastAPI",
            aweme_count: 5,
            task_count: 2,
            last_seen_at: now,
            created_at: now,
          },
        ],
      },
    })
  })

  await page.goto("/douyin-tags")
  await expect(page.getByRole("heading", { name: "标签管理" })).toBeVisible()
  await expect(page.getByText("#FastAPI", { exact: true })).toBeVisible()
  await expect(page.getByRole("link", { name: "查看视频" })).toHaveAttribute(
    "href",
    `/douyin-library?tag=${tagId}`,
  )
  await page.getByRole("button", { name: "同步历史标签" }).click()
  await expect.poll(() => syncCalls).toBe(1)
  await expect(page.getByText(/已扫描 14 个作品/)).toBeVisible()
})

test("manages keywords, syncs history and prepares batch task selection", async ({
  page,
}) => {
  const keywordId = "118a8148-c8b6-4c6c-b7c4-93580d687399"
  const now = new Date().toISOString()
  let bulkCreateCalls = 0
  let historySyncCalls = 0

  await page.route("**/api/v1/douyin/keywords/**", async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.pathname.endsWith("/bulk")) {
      bulkCreateCalls += 1
      expect(request.postDataJSON().keywords).toEqual(["新关键词"])
      await route.fulfill({
        status: 201,
        json: { data: [], created_count: 1, existing_count: 0 },
      })
      return
    }
    if (url.pathname.endsWith("/sync/history")) {
      historySyncCalls += 1
      await route.fulfill({
        json: {
          task_count: 2,
          keyword_count: 3,
          created_count: 1,
          binding_count: 2,
        },
      })
      return
    }
    if (url.pathname.endsWith(`/by-id/${keywordId}/tasks`)) {
      await route.fulfill({ json: [] })
      return
    }
    await route.fulfill({
      json: {
        count: 1,
        data: [
          {
            id: keywordId,
            keyword: "FastAPI 爬虫",
            enabled: true,
            notes: "技术内容方向",
            status: "crawled",
            task_count: 2,
            active_task_count: 0,
            success_task_count: 2,
            failed_task_count: 0,
            aweme_count: 18,
            last_task_id: null,
            last_task_status: "succeeded",
            last_crawled_at: now,
            created_at: now,
            updated_at: now,
          },
        ],
      },
    })
  })

  await page.goto("/douyin-keywords")
  await expect(page.getByRole("heading", { name: "关键词管理" })).toBeVisible()
  await expect(page.getByText("FastAPI 爬虫")).toBeVisible()
  await expect(
    page.getByRole("table").getByText("已爬取", { exact: true }),
  ).toBeVisible()
  await expect(page.getByText("18", { exact: true }).first()).toBeVisible()

  await page.getByRole("button", { name: "添加关键词" }).click()
  await page
    .getByRole("textbox", { name: "关键词", exact: true })
    .fill("新关键词")
  await page.getByRole("button", { name: "保存关键词" }).click()
  await expect.poll(() => bulkCreateCalls).toBe(1)

  await page.getByRole("button", { name: "同步历史任务" }).click()
  await expect.poll(() => historySyncCalls).toBe(1)

  await page.getByRole("checkbox").last().click()
  await expect(page.getByRole("button", { name: "批量创建任务" })).toBeEnabled()
})

test("shows live API documentation and MCP tool catalog", async ({ page }) => {
  await page.route("**/api/v1/system/integrations/", async (route) => {
    await route.fulfill({
      json: {
        api_title: "Douyin Crawler API",
        api_version: "0.1.0",
        api_openapi_url: "http://127.0.0.1:8000/api/v1/openapi.json",
        api_swagger_url: "http://127.0.0.1:8000/docs",
        api_operation_count: 1,
        api_operations: [
          {
            method: "POST",
            path: "/api/v1/douyin/tasks",
            summary: "创建抖音任务",
            description: "通过 CDP 创建爬取任务。",
            operation_id: "douyin-create_task",
            tags: ["douyin"],
            auth_required: true,
            parameters: [],
            request_body: {
              content: {
                "application/json": {
                  schema: { $ref: "#/components/schemas/CrawlTaskCreate" },
                },
              },
            },
            response_codes: ["202", "422"],
          },
        ],
        mcp_server_name: "Douyin Crawler API",
        mcp_streamable_http_url: "http://127.0.0.1:8766/mcp",
        mcp_health_url: "http://127.0.0.1:8766/health",
        mcp_stdio_command: "uv run python -m app.mcp_server",
        mcp_http_command:
          "uv run python -m app.mcp_server --transport streamable-http --host 127.0.0.1 --port 8766",
        mcp_tool_count: 1,
        mcp_tools: [
          {
            name: "create_douyin_task",
            title: null,
            description: "创建抖音任务，可使用托管账号或账号池。",
            input_schema: {
              type: "object",
              required: ["crawl_type"],
              properties: {
                crawl_type: {
                  type: "string",
                  enum: ["search", "detail"],
                },
              },
            },
            output_schema: { type: "object" },
          },
        ],
      },
    })
  })

  await page.goto("/developer-tools")
  await expect(page.getByRole("heading", { name: "开发者中心" })).toBeVisible()
  await expect(page.getByText("/api/v1/douyin/tasks")).toBeVisible()
  await expect(page.getByText("创建抖音任务", { exact: true })).toBeVisible()

  await page.getByRole("tab", { name: "MCP 工具" }).click()
  await expect(page.getByText("create_douyin_task")).toBeVisible()
  await page.getByText("create_douyin_task").click()
  await expect(page.getByText("crawl_type")).toBeVisible()
  await expect(page.getByText("search / detail")).toBeVisible()
})

test("discovers remote browser slots and auto-assigns an available slot", async ({
  page,
}) => {
  const accountId = "318a8148-c8b6-4c6c-b7c4-93580d687300"
  const now = new Date().toISOString()
  let createCalls = 0

  await page.route("**/api/v1/douyin/accounts**", async (route) => {
    const request = route.request()
    const pathname = new URL(request.url()).pathname
    if (pathname.endsWith("/browser-slots")) {
      await route.fulfill({
        json: {
          count: 3,
          data: [
            {
              name: null,
              label: "Docker 默认槽位",
              is_default: true,
              available: false,
              configured: true,
              viewer_available: true,
              occupied_account_id: accountId,
              occupied_account_name: "默认账号",
            },
            {
              name: "pool-1",
              label: "pool-1",
              is_default: false,
              available: true,
              configured: true,
              viewer_available: true,
              occupied_account_id: null,
              occupied_account_name: null,
            },
            {
              name: "pool-2",
              label: "pool-2",
              is_default: false,
              available: false,
              configured: true,
              viewer_available: true,
              occupied_account_id: "418a8148-c8b6-4c6c-b7c4-93580d687300",
              occupied_account_name: "另一个账号",
            },
          ],
        },
      })
      return
    }
    if (pathname.endsWith("/pools")) {
      await route.fulfill({ json: { data: [], count: 0 } })
      return
    }
    if (request.method() === "POST") {
      expect(request.postDataJSON()).toMatchObject({
        name: "自动槽位账号",
        browser_mode: "remote",
        remote_slot: "pool-1",
      })
      createCalls += 1
      await route.fulfill({
        status: 201,
        json: {
          id: "518a8148-c8b6-4c6c-b7c4-93580d687300",
          name: "自动槽位账号",
          browser_mode: "remote",
          remote_slot: "pool-1",
          status: "login_required",
          is_logged_in: false,
          weight: 1,
          priority: 0,
          concurrency_limit: 1,
          daily_task_limit: 100,
          tasks_today: 0,
          min_request_interval_seconds: 1,
          active_leases: 0,
          failure_streak: 0,
          cooldown_until: null,
          last_verified_at: null,
          last_used_at: null,
          last_error: null,
          enabled: true,
          created_at: now,
          updated_at: now,
        },
      })
      return
    }
    await route.fulfill({
      json: {
        count: 1,
        data: [
          {
            id: accountId,
            name: "默认账号",
            browser_mode: "remote",
            remote_slot: null,
            status: "login_required",
            is_logged_in: false,
            weight: 1,
            priority: 0,
            concurrency_limit: 1,
            daily_task_limit: 100,
            tasks_today: 0,
            min_request_interval_seconds: 1,
            active_leases: 0,
            failure_streak: 0,
            cooldown_until: null,
            last_verified_at: null,
            last_used_at: null,
            last_error: null,
            enabled: true,
            created_at: now,
            updated_at: now,
          },
        ],
      },
    })
  })

  await page.goto("/douyin-accounts")

  await page.getByRole("button", { name: "横条" }).click()
  await expect(page.getByText("今日任务")).toBeVisible()
  await page.getByRole("button", { name: "卡片" }).click()
  await expect(page.getByText("最后验证")).toBeVisible()
  await page.getByRole("button", { name: "表格" }).click()

  await expect(page.getByText("远程槽位可用").locator("..")).toContainText(
    "1 / 3",
  )
  await expect(page.getByText("已绑定：默认账号")).toBeVisible()
  await page.getByRole("button", { name: "添加账号" }).click()
  await page.getByLabel("账号别名").fill("自动槽位账号")
  await expect(
    page.getByRole("combobox", { name: "远程浏览器槽位" }),
  ).toContainText("自动分配（pool-1）")
  await page.getByRole("button", { name: "创建账号" }).click()

  await expect.poll(() => createCalls).toBe(1)
})

test("keeps account login and verify loading states isolated per row", async ({
  page,
}) => {
  const now = new Date().toISOString()
  const firstId = "618a8148-c8b6-4c6c-b7c4-93580d687300"
  const secondId = "718a8148-c8b6-4c6c-b7c4-93580d687300"
  const account = (id: string, name: string, slot: string) => ({
    id,
    name,
    browser_mode: "remote",
    remote_slot: slot,
    status: "ready",
    is_logged_in: true,
    weight: 1,
    priority: 0,
    concurrency_limit: 1,
    daily_task_limit: 100,
    tasks_today: 0,
    min_request_interval_seconds: 1,
    active_leases: 0,
    failure_streak: 0,
    cooldown_until: null,
    last_verified_at: now,
    last_used_at: null,
    last_error: null,
    enabled: true,
    created_at: now,
    updated_at: now,
  })
  await page.route("**/api/v1/douyin/accounts**", async (route) => {
    const request = route.request()
    const pathname = new URL(request.url()).pathname
    if (pathname.endsWith("/browser-slots")) {
      await route.fulfill({ json: { data: [], count: 0 } })
      return
    }
    if (pathname.endsWith("/pools")) {
      await route.fulfill({ json: { data: [], count: 0 } })
      return
    }
    if (pathname.endsWith(`/${firstId}/login`)) {
      await new Promise((resolve) => setTimeout(resolve, 500))
      await route.fulfill({
        status: 202,
        json: {
          account: account(firstId, "账号甲", "pool-1"),
          status: "verifying",
          browser_mode: "remote",
          viewer_url: null,
          expires_at: now,
          message: "浏览器已打开",
        },
      })
      return
    }
    await route.fulfill({
      json: {
        data: [
          account(firstId, "账号甲", "pool-1"),
          account(secondId, "账号乙", "pool-2"),
        ],
        count: 2,
      },
    })
  })

  await page.goto("/douyin-accounts")
  const firstRow = page.getByRole("row").filter({ hasText: "账号甲" })
  const secondRow = page.getByRole("row").filter({ hasText: "账号乙" })
  await firstRow.getByRole("button", { name: "登录" }).click()
  await expect(firstRow.getByRole("button", { name: "登录" })).toBeDisabled()
  await expect(firstRow.getByRole("button", { name: "验证" })).toBeDisabled()
  await expect(secondRow.getByRole("button", { name: "登录" })).toBeEnabled()
  await expect(secondRow.getByRole("button", { name: "验证" })).toBeEnabled()
})

test("prepares and explicitly confirms a video interaction", async ({
  page,
}) => {
  const taskId = "218a8148-c8b6-4c6c-b7c4-93580d687399"
  const accountId = "318a8148-c8b6-4c6c-b7c4-93580d687399"
  const interactionId = "418a8148-c8b6-4c6c-b7c4-93580d687399"
  const awemeId = "7660000000000000001"
  const now = new Date().toISOString()
  let preflightCalls = 0
  let prepareCalls = 0
  let confirmCalls = 0
  let listedInteractionStatus: string | null = null

  await page.route("**/api/v1/douyin/accounts**", async (route) => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname.endsWith("/browser-slots")) {
      await route.fulfill({
        json: {
          count: 1,
          data: [
            {
              name: "account-1",
              label: "互动账号浏览器",
              is_default: true,
              available: false,
              configured: true,
              viewer_available: true,
              viewer_url:
                "http://127.0.0.1:6081/vnc.html?autoconnect=1&resize=scale",
              cdp_healthy: true,
              page_count: 1,
              active_page_title: "目标视频",
              active_page_url: `https://www.douyin.com/video/${awemeId}`,
              latency_ms: 12,
              checked_at: now,
              occupied_account_id: accountId,
              occupied_account_name: "已登录互动账号",
            },
          ],
        },
      })
      return
    }
    await route.fulfill({
      json: {
        count: 1,
        data: [
          {
            id: accountId,
            name: "已登录互动账号",
            browser_mode: "remote",
            remote_slot: "account-1",
            status: "ready",
            is_logged_in: true,
            weight: 1,
            priority: 0,
            concurrency_limit: 1,
            daily_task_limit: 100,
            tasks_today: 1,
            min_request_interval_seconds: 1,
            active_leases: 0,
            failure_streak: 0,
            cooldown_until: null,
            last_verified_at: now,
            last_used_at: null,
            last_error: null,
            enabled: true,
            created_at: now,
            updated_at: now,
          },
        ],
      },
    })
  })
  await page.route("**/api/v1/douyin/interactions**", async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.pathname.endsWith("/quota")) {
      await route.fulfill({
        json: [
          {
            account_id: accountId,
            account_name: "已登录互动账号",
            daily_limit: 50,
            used_today: 1,
            remaining_today: 49,
            min_interval_seconds: 30,
            cooldown_until: null,
            available: true,
          },
        ],
      })
      return
    }
    if (url.pathname.endsWith("/preflight")) {
      expect(request.postDataJSON().content).toBe("人工确认的测试评论")
      preflightCalls += 1
      await route.fulfill({
        json: {
          allowed: true,
          message: "发送前检查通过",
          account_name: "已登录互动账号",
          remaining_daily_quota: 49,
        },
      })
      return
    }
    if (url.pathname.endsWith(`/${interactionId}/confirm`)) {
      confirmCalls += 1
      listedInteractionStatus = "running"
      await route.fulfill({ json: interactionPayload("queued") })
      return
    }
    if (url.pathname.endsWith(`/${interactionId}`)) {
      await route.fulfill({
        json: {
          ...interactionPayload("running"),
          content: "人工确认的测试评论",
          events: [
            {
              id: "518a8148-c8b6-4c6c-b7c4-93580d687398",
              event: "browser_video_opened",
              from_status: "running",
              to_status: "running",
              detail: "已打开目标视频页面",
              attempt_number: 1,
              has_screenshot: false,
              created_at: now,
            },
          ],
        },
      })
      return
    }
    if (request.method() === "POST") {
      prepareCalls += 1
      listedInteractionStatus = "pending_confirmation"
      await route.fulfill({
        status: 201,
        json: interactionPayload("pending_confirmation"),
      })
      return
    }
    const listedInteraction = listedInteractionStatus
      ? [interactionPayload(listedInteractionStatus)]
      : []
    await route.fulfill({
      json: { data: listedInteraction, count: listedInteraction.length },
    })
  })
  await page.route(`**/api/v1/douyin/tasks/${taskId}**`, async (route) => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname.endsWith("/works")) {
      await route.fulfill({
        json: {
          count: 1,
          data: [
            {
              aweme: {
                id: "518a8148-c8b6-4c6c-b7c4-93580d687399",
                task_id: taskId,
                aweme_id: awemeId,
                aweme_type: "0",
                title: "可以发起互动的视频",
                description: "",
                create_time: 1_700_000_000,
                creator_hash: "creator-hash",
                sec_uid: "hashed-sec-uid",
                nickname: "测**者",
                liked_count: 10,
                collected_count: 2,
                comment_count: 1,
                share_count: 0,
                aweme_url: `https://www.douyin.com/video/${awemeId}`,
                cover_url: "",
                video_download_url: "",
                music_download_url: "",
                note_download_url: "",
                source_keyword: "互动",
                fetched_at: now,
              },
              persisted_comment_count: 0,
              media: null,
            },
          ],
        },
      })
      return
    }
    if (pathname.endsWith("/media-summary")) {
      await route.fulfill({
        json: {
          total: 0,
          queued: 0,
          downloading: 0,
          downloaded: 0,
          download_failed: 0,
          subtitle_pending: 0,
          subtitle_running: 0,
          subtitle_completed: 0,
          subtitle_failed: 0,
          ...emptyMigrationSummary,
        },
      })
      return
    }
    if (pathname.endsWith("/media") || pathname.endsWith("/shards")) {
      await route.fulfill({ json: { data: [], count: 0 } })
      return
    }
    await route.fulfill({
      json: {
        id: taskId,
        owner_id: "c7e0bb1c-891a-4b4a-8f12-26c1ddd8239d",
        account_id: accountId,
        account_pool_id: null,
        account_strategy: "least_loaded",
        crawl_type: "detail",
        status: "succeeded",
        request: { crawl_type: "detail", video_ids: [awemeId] },
        aweme_count: 1,
        comment_count: 0,
        action_count: 0,
        checkpoint_phase: "completed",
        resume_count: 0,
        can_resume_crawl: false,
        can_resume_media: false,
        error: null,
        has_qrcode: false,
        created_at: now,
        started_at: now,
        finished_at: now,
        last_resumed_at: null,
      },
    })
  })

  await page.goto(`/douyin/${taskId}`)
  await page.getByRole("tab", { name: /^作品数据/ }).click()
  await expect(page.getByText("可以发起互动的视频")).toBeVisible()
  await page
    .getByRole("button", { name: /更多作品操作：可以发起互动的视频/ })
    .click()
  await expect(
    page.getByRole("menuitem", { name: "私信", exact: true }),
  ).toBeVisible()
  await page.getByRole("menuitem", { name: "评论", exact: true }).click()
  await expect(page.getByRole("heading", { name: "评论视频" })).toBeVisible()
  await page.getByLabel("发送内容").fill("人工确认的测试评论")
  await page.getByRole("button", { name: "发送前检查" }).click()
  await expect(page.getByText("等待最终确认")).toBeVisible()
  await expect.poll(() => preflightCalls).toBe(1)
  await expect.poll(() => prepareCalls).toBe(1)
  expect(confirmCalls).toBe(0)
  await page.route("http://127.0.0.1:6081/**", async (route) => {
    await route.fulfill({
      contentType: "text/html",
      body: "<html><body>noVNC test viewer</body></html>",
    })
  })
  await page.getByRole("button", { name: "发送并查看实时监控" }).click()
  await expect.poll(() => confirmCalls).toBe(1)
  await expect(
    page.getByRole("heading", { name: "评论实时监控" }),
  ).toBeVisible()
  await expect(page.getByText("执行链路", { exact: true })).toBeVisible()
  await expect(page.getByText("打开目标视频", { exact: true })).toBeVisible()
  await expect(
    page.getByRole("link", { name: awemeId, exact: true }),
  ).toHaveAttribute("href", `https://www.douyin.com/video/${awemeId}`)
  await expect(page.getByTitle("已登录互动账号实时浏览器")).toBeVisible()
  await page.setViewportSize({ width: 375, height: 812 })
  const mobileMonitor = await page.getByRole("dialog").boundingBox()
  expect(mobileMonitor?.width).toBeLessThanOrEqual(375)
  await expect(
    page.getByRole("heading", { name: "评论实时监控" }),
  ).toBeVisible()
  await page.setViewportSize({ width: 812, height: 375 })
  await expect(page.getByText("执行链路", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: "关闭", exact: true }).click()
  await page.getByRole("tab", { name: /^互动记录/ }).click()
  const runningInteractionRow = page
    .getByRole("row")
    .filter({ hasText: "人工确认的测试评论" })
  await expect(runningInteractionRow).toBeVisible()
  await expect(
    runningInteractionRow.getByRole("button", {
      name: "重试",
      exact: true,
    }),
  ).toHaveCount(0)

  function interactionPayload(status: string) {
    return {
      id: interactionId,
      task_id: taskId,
      account_id: accountId,
      account_name: "已登录互动账号",
      aweme_id: awemeId,
      target_video_url: `https://www.douyin.com/video/${awemeId}`,
      target_comment_id: null,
      interaction_type: "video_comment",
      content_preview: "人工确认的测试评论",
      status,
      failure_code: null,
      error: null,
      attempt_count: 0,
      result_platform_id: null,
      human_confirmed_at: status === "queued" ? now : null,
      started_at: null,
      finished_at: null,
      created_at: now,
      updated_at: now,
      can_confirm: status === "pending_confirmation",
      can_retry: status !== "succeeded",
      can_cancel: ["pending_confirmation", "queued"].includes(status),
    }
  }
})

test("shows authenticated browser screenshots in the interaction timeline", async ({
  page,
}) => {
  const interactionId = "618a8148-c8b6-4c6c-b7c4-93580d687399"
  const taskId = "718a8148-c8b6-4c6c-b7c4-93580d687399"
  const eventId = "818a8148-c8b6-4c6c-b7c4-93580d687399"
  const now = new Date().toISOString()
  const image = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
    "base64",
  )
  let screenshotCalls = 0
  const interaction = {
    id: interactionId,
    task_id: taskId,
    account_id: "918a8148-c8b6-4c6c-b7c4-93580d687399",
    account_name: "截图测试账号",
    aweme_id: "7660000000000000002",
    target_video_url: "https://www.douyin.com/video/7660000000000000002",
    target_comment_id: null,
    interaction_type: "video_comment",
    content_preview: "截图日志测试评论",
    status: "failed",
    failure_code: "comment_not_available",
    error: "没有找到评论输入框",
    attempt_count: 1,
    result_platform_id: null,
    human_confirmed_at: now,
    started_at: now,
    finished_at: now,
    created_at: now,
    updated_at: now,
    can_confirm: false,
    can_retry: true,
    can_cancel: false,
  }

  await page.route("**/api/v1/douyin/interactions**", async (route) => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname.endsWith("/quota")) {
      await route.fulfill({ json: [] })
      return
    }
    if (pathname.endsWith(`/events/${eventId}/screenshot`)) {
      screenshotCalls += 1
      await route.fulfill({
        status: 200,
        contentType: "image/png",
        body: image,
      })
      return
    }
    if (pathname.endsWith(`/${interactionId}`)) {
      await route.fulfill({
        json: {
          ...interaction,
          content: "截图日志测试评论",
          events: [
            {
              id: eventId,
              event: "browser_video_opened",
              from_status: "running",
              to_status: "running",
              detail: "已打开目标视频页面",
              attempt_number: 1,
              has_screenshot: true,
              created_at: now,
            },
          ],
        },
      })
      return
    }
    await route.fulfill({ json: { data: [interaction], count: 1 } })
  })

  await page.goto("/douyin-interactions")
  await page.getByRole("button", { name: "查看详情" }).click()
  await expect(
    page.getByRole("link", {
      name: "打开抖音视频 7660000000000000002",
    }),
  ).toHaveAttribute("href", "https://www.douyin.com/video/7660000000000000002")
  await expect(page.getByText("浏览器操作日志")).toBeVisible()
  await expect(page.getByText("1 张截图")).toBeVisible()
  await expect(page.getByText("打开目标视频", { exact: true })).toBeVisible()
  await expect(page.getByAltText("打开目标视频操作截图")).toBeVisible()
  await expect.poll(() => screenshotCalls).toBeGreaterThanOrEqual(1)
  await page.getByRole("button", { name: "查看操作截图大图" }).click()
  await expect(
    page.getByRole("heading", { name: "打开目标视频" }),
  ).toBeVisible()
  await expect(page.getByAltText("打开目标视频操作截图大图")).toBeVisible()
})

test("shows the replied comment content in interaction lists and detail", async ({
  page,
}) => {
  const interactionId = "a18a8148-c8b6-4c6c-b7c4-93580d687399"
  const now = new Date().toISOString()
  const interaction = {
    id: interactionId,
    task_id: "b18a8148-c8b6-4c6c-b7c4-93580d687399",
    account_id: "c18a8148-c8b6-4c6c-b7c4-93580d687399",
    account_name: "回复测试账号",
    aweme_id: "7660000000000000010",
    target_video_url: "https://www.douyin.com/video/7660000000000000010",
    target_comment_id: "7661000000000000010",
    target_comment_content: "这是用户发表、等待被回复的原评论",
    interaction_type: "comment_reply",
    content_preview: "这是运营人员发送的回复",
    status: "succeeded",
    failure_code: null,
    error: null,
    attempt_count: 1,
    result_platform_id: "7662000000000000010",
    human_confirmed_at: now,
    started_at: now,
    finished_at: now,
    created_at: now,
    updated_at: now,
    can_confirm: false,
    can_retry: false,
    can_cancel: false,
  }

  await page.route("**/api/v1/douyin/interactions**", async (route) => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname.endsWith("/quota")) {
      await route.fulfill({ json: [] })
      return
    }
    if (pathname.endsWith(`/${interactionId}`)) {
      await route.fulfill({
        json: {
          ...interaction,
          content: "这是运营人员发送的回复",
          events: [],
        },
      })
      return
    }
    await route.fulfill({ json: { data: [interaction], count: 1 } })
  })

  await page.goto("/douyin-interactions")
  const table = page.getByRole("table")
  await expect(table.getByText("被回复的评论")).toBeVisible()
  await expect(
    table.getByText("这是用户发表、等待被回复的原评论"),
  ).toBeVisible()
  await expect(table.getByText("我的回复")).toBeVisible()
  await expect(table.getByText("这是运营人员发送的回复")).toBeVisible()

  await page.getByRole("button", { name: "查看详情" }).click()
  const dialog = page.getByRole("dialog", { name: "互动任务详情" })
  await expect(dialog.getByText("被回复的评论")).toBeVisible()
  await expect(
    dialog.getByText("这是用户发表、等待被回复的原评论"),
  ).toBeVisible()
  await expect(dialog.getByText("这是运营人员发送的回复")).toBeVisible()
})

test("does not show or trigger retry while an interaction is running", async ({
  page,
}) => {
  const now = new Date().toISOString()
  const base = {
    task_id: "718a8148-c8b6-4c6c-b7c4-93580d687399",
    account_id: "918a8148-c8b6-4c6c-b7c4-93580d687399",
    account_name: "批量重试账号",
    target_video_url: "https://www.douyin.com/video/7660000000000000003",
    target_comment_id: null,
    interaction_type: "video_comment",
    failure_code: null,
    error: null,
    attempt_count: 20,
    result_platform_id: null,
    human_confirmed_at: now,
    started_at: now,
    finished_at: now,
    created_at: now,
    updated_at: now,
    can_confirm: false,
    can_cancel: false,
  }
  const interactions = [
    {
      ...base,
      id: "118a8148-c8b6-4c6c-b7c4-93580d687399",
      aweme_id: "7660000000000000003",
      content_preview: "失败任务",
      status: "failed",
      can_retry: true,
    },
    {
      ...base,
      id: "218a8148-c8b6-4c6c-b7c4-93580d687399",
      aweme_id: "7660000000000000004",
      content_preview: "待人工核对任务",
      status: "needs_review",
      can_retry: true,
    },
    {
      ...base,
      id: "318a8148-c8b6-4c6c-b7c4-93580d687399",
      aweme_id: "7660000000000000005",
      content_preview: "成功任务",
      status: "succeeded",
      can_retry: false,
    },
    {
      ...base,
      id: "418a8148-c8b6-4c6c-b7c4-93580d687399",
      aweme_id: "7660000000000000006",
      content_preview: "排队中的任务",
      status: "queued",
      can_retry: true,
    },
    {
      ...base,
      id: "518a8148-c8b6-4c6c-b7c4-93580d687399",
      aweme_id: "7660000000000000007",
      content_preview: "发送中的任务",
      status: "running",
      can_retry: true,
    },
    {
      ...base,
      id: "618a8148-c8b6-4c6c-b7c4-93580d687399",
      aweme_id: "7660000000000000008",
      content_preview: "等待确认的任务",
      status: "pending_confirmation",
      can_retry: true,
      can_confirm: true,
    },
  ]
  const retried: Array<{ id: string; confirmNotSent: boolean }> = []

  await page.route("**/api/v1/douyin/interactions**", async (route) => {
    const request = route.request()
    const pathname = new URL(request.url()).pathname
    if (pathname.endsWith("/quota")) {
      await route.fulfill({ json: [] })
      return
    }
    if (request.method() === "POST" && pathname.endsWith("/retry")) {
      const id = pathname.split("/").slice(-2)[0]!
      const body = request.postDataJSON() as { confirm_not_sent: boolean }
      retried.push({ id, confirmNotSent: body.confirm_not_sent })
      const item = interactions.find((candidate) => candidate.id === id)!
      await route.fulfill({ status: 202, json: { ...item, status: "queued" } })
      return
    }
    await route.fulfill({
      json: { data: interactions, count: interactions.length },
    })
  })

  page.on("dialog", (dialog) => dialog.accept())
  await page.goto("/douyin-interactions")
  const runningRow = page.getByRole("row").filter({ hasText: "发送中的任务" })
  await expect(
    runningRow.getByRole("button", { name: "重试", exact: true }),
  ).toHaveCount(0)
  for (const content of ["排队中的任务", "等待确认的任务"]) {
    const row = page.getByRole("row").filter({ hasText: content })
    await expect(
      row.getByRole("button", { name: "重试", exact: true }),
    ).toBeVisible()
  }
  await page.getByRole("button", { name: "重试全部可重试项" }).click()

  await expect.poll(() => retried.length).toBe(4)
  expect(retried).toEqual(
    expect.arrayContaining([
      {
        id: "118a8148-c8b6-4c6c-b7c4-93580d687399",
        confirmNotSent: false,
      },
      {
        id: "218a8148-c8b6-4c6c-b7c4-93580d687399",
        confirmNotSent: true,
      },
      {
        id: "418a8148-c8b6-4c6c-b7c4-93580d687399",
        confirmNotSent: false,
      },
      {
        id: "618a8148-c8b6-4c6c-b7c4-93580d687399",
        confirmNotSent: false,
      },
    ]),
  )
  expect(retried.some((item) => item.id.startsWith("518a8148"))).toBe(false)
})
