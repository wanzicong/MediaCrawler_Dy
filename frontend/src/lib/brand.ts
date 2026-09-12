/**
 * 品牌常量。
 *
 * 背景：改造前产品名在至少三处不一致 ——
 *   「灵感采集台」（login.tsx / settings.tsx / admin.tsx / 任务详情，出现最多）
 *   「运营工作台」（index.tsx）
 *   「抖音内容运营工作室」（AuthLayout.tsx 页脚）
 * 这里以出现次数最多的「灵感采集台」为准，其余位置统一引用本文件。
 */

export const PRODUCT_NAME = "灵感采集台"

/** 更口语、偏业务场景的别名，用于工作台首页等需要强调「运营」语境的位置。 */
export const PRODUCT_WORKSPACE_NAME = "运营工作台"

export const PRODUCT_TAGLINE = "抖音内容采集与运营工作台"

/** 页面标题统一后缀：`${pageTitle} - ${PRODUCT_NAME}` */
export function pageTitle(title: string): string {
  return `${title} - ${PRODUCT_NAME}`
}
