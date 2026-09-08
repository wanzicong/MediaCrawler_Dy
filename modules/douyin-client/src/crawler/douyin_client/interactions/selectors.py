# Portions adapted from MediaCrawler, NON-COMMERCIAL LEARNING LICENSE 1.1.

"""互动页面选择器、文案与就绪脚本常量（唯一出处）。

原先散落在 ``DouyinInteractionExecutor`` 类属性中的 DOM 选择器与页面文案提示集中于此，
各协作类按需导入；``executor`` 仅保留主站地址与自动化标签页标记两个流程标识常量。
"""

# 评论/回复输入框候选选择器（兼容多种页面版本）
COMMENT_EDITOR_SELECTORS = (
    '#comment-input-container [contenteditable="true"][role="combobox"]',
    '#comment-input-container .public-DraftEditor-content[contenteditable="true"]',
    '.comment-input-container [contenteditable="true"][role="combobox"]',
    '.comment-input-container .public-DraftEditor-content[contenteditable="true"]',
    '.comment-input-inner-container [contenteditable="true"]',
    '[data-e2e="comment-input"] [contenteditable="true"]',
    '[data-e2e="comment-input"] textarea',
    'div[contenteditable="true"][data-placeholder*="评论"]',
    'div[contenteditable="true"][aria-label*="评论"]',
    'textarea[placeholder*="评论"]',
    'div[contenteditable="true"][data-placeholder*="回复"]',
    'textarea[placeholder*="回复"]',
)
# 评论区入口容器选择器
COMMENT_ENTRY_SELECTORS = (
    ".comment-input-inner-container",
    "#comment-input-container",
)
# 评论标签按钮选择器
COMMENT_TAB_SELECTORS = (
    (
        "xpath=//*[self::div or self::span][not(*) and "
        "(normalize-space(.)='评论' or "
        "starts-with(normalize-space(.), '评论('))]"
    ),
    '[data-e2e="feed-comment-icon"]',
    '[data-e2e="comment-icon"]',
    '[aria-label*="评论"]',
    'button:has-text("评论")',
    # 针对旧版图文详情页的兜底选择器。上面的语义化选择器必须放在前面，
    # 因为这个自动生成的类名也会出现在无关的推荐控件上。
    "div.X9EiuBV4:nth-of-type(2)",
)
# 评论列表容器选择器
COMMENT_LIST_SELECTORS = ('[data-e2e="comment-list"]',)
# 单条评论节点选择器
COMMENT_ITEM_SELECTORS = ('[data-e2e="comment-item"]',)
# 评论发送按钮候选选择器
COMMENT_SUBMIT_SELECTORS = (
    '#comment-input-container .commentInput-right-ct span:has(path[fill="#fff"])',
    "#comment-input-container .commentInput-right-ct > div > span:last-child",
    '.comment-input-container .commentInput-right-ct span:has(path[fill="#fff"])',
    ".comment-input-container .commentInput-right-ct > div > span:last-child",
    ".comment-input-inner-container .commentInput-right-ct > div > span:last-child",
    '#comment-input-container [data-e2e="comment-submit"]',
)
# 评论失败的页面提示文案
COMMENT_FAILURE_MESSAGES = (
    "发布评论失败",
    "评论发布失败",
    "评论发送失败",
    "操作频繁",
    "请求太频繁",
)
# 评论成功的页面提示文案
COMMENT_SUCCESS_MESSAGES = (
    "已发布",
    "评论成功",
    "发布成功",
)
# 触发风控/安全验证的页面提示文案
COMMENT_RISK_MESSAGES = (
    "接收短信验证码",
    "为确保是本人操作抖音账号",
    "使用原设备扫码",
    "安全验证",
)
# 私信输入框候选选择器
MESSAGE_EDITOR_SELECTORS = (
    '[data-e2e="im-input"] [contenteditable="true"]',
    '[data-e2e="message-input"] [contenteditable="true"]',
    'div[contenteditable="true"][data-placeholder*="消息"]',
    'div[contenteditable="true"][aria-label*="消息"]',
    'div[contenteditable="true"][role="textbox"]',
    'textarea[placeholder*="消息"]',
    'textarea[placeholder*="发送"]',
)
# 私信发送按钮候选选择器
MESSAGE_SUBMIT_SELECTORS = (
    "svg.e2e-send-msg-btn",
    "svg.messageMsgInputpublishRedBtn",
    ".messageMsgInputpublishRedBtn.e2e-send-msg-btn",
)
# 作者主页加载完成的标志元素选择器
CREATOR_PROFILE_READY_SELECTORS = (
    '[data-e2e="user-detail"]',
    '[data-e2e="user-info"]',
)
# 私信发送响应的 URL 匹配标记（发送后跳入会话页时用于识别响应）
MESSAGE_RESPONSE_MARKERS = ("/im/", "/message/")
# 视频页就绪检测脚本：页面不再处于“视频数据加载中”，且存在 video 元素或互动 UI
VIDEO_PAGE_READY_SCRIPT = """() => {
    const bodyText = document.body?.innerText || '';
    const stillLoading = bodyText.includes('视频数据加载中');
    const hasVideo = document.querySelectorAll('video').length > 0;
    const hasInteractionUi = Boolean(document.querySelector(
        '#comment-input-container, .comment-input-inner-container, '
        + '[data-e2e="feed-comment-icon"], [data-e2e="comment-icon"]'
    ));
    return !stillLoading
        && (hasVideo || hasInteractionUi);
}"""
