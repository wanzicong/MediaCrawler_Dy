/**
 * 筛选状态 ↔ URL 查询参数的辅助（报告 O4）。
 *
 * 背景：改造前 12 个带筛选的列表**没有一个**把筛选写进 URL ——
 * 刷新丢筛选、后退丢筛选、链接分享给别人也丢筛选。
 * 而 TanStack Router 本身是 URL-first 的，能力一直摆在那里没人用。
 *
 * 这里只提供两个纯函数，路由的 validateSearch 仍由各页自己声明（类型最准）。
 */

/**
 * 去掉「等于默认值」的键，让 URL 保持干净。
 * 未筛选时地址栏就是 `/douyin-tasks`，而不是 `/douyin-tasks?status=all&track=all&q=`。
 *
 * 返回类型刻意保留为入参的 T（而不是 Record<string, unknown>）：
 * TanStack Router 的 navigate({ search }) 要求 search 对象与路由声明的形状匹配，
 * 返回 Record 会被判为「缺少 status/track/... 属性」而编译不过。
 * 运行时返回的对象只含非默认值的键，缺失的键等同于 undefined，行为正确。
 */
export function compactSearch<T extends Record<string, unknown>>(
  values: T,
  defaults: Partial<Record<keyof T, unknown>> = {},
): T {
  const result: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(values)) {
    if (value === undefined || value === null || value === "") continue
    if (key in defaults && value === defaults[key as keyof T]) continue
    result[key] = value
  }
  return result as T
}

/**
 * 从 URL 查询参数里安全地取一个字符串。
 * 路由的 validateSearch 里用，避免把 `?q=abc` 当成数组或对象。
 */
export function readStringParam(
  search: Record<string, unknown>,
  key: string,
): string | undefined {
  const value = search[key]
  return typeof value === "string" && value !== "" ? value : undefined
}

/**
 * 从 URL 查询参数里取一个枚举值，不在白名单内就返回 undefined。
 * 挡住手改 URL 传进来的脏值。
 */
export function readEnumParam<T extends string>(
  search: Record<string, unknown>,
  key: string,
  allowed: readonly T[],
): T | undefined {
  const value = readStringParam(search, key)
  return value !== undefined && (allowed as readonly string[]).includes(value)
    ? (value as T)
    : undefined
}
