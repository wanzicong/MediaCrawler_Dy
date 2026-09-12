/**
 * 统一的时间格式化工具。
 *
 * 背景：改造前全站有 24 份各自实现的 formatDate / formatUnix / formatDateTimeText，
 * 格式互不一致（有的带年份、有的只到分钟、有的把 null 显示为「从未」、有的显示为「—」）。
 * 新代码请一律使用这里的函数，不要再在页面里本地定义。
 */

type TimeInput = string | number | Date | null | undefined

const FULL_FORMATTER = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
})

const SHORT_FORMATTER = new Intl.DateTimeFormat("zh-CN", {
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
})

const DATE_ONLY_FORMATTER = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
})

const TIME_ONLY_FORMATTER = new Intl.DateTimeFormat("zh-CN", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
})

const DEFAULT_FALLBACK = "—"

/** 把各种输入统一转成 Date；无法解析时返回 null。 */
function toDate(value: TimeInput): Date | null {
  if (value === null || value === undefined || value === "") return null
  const date = value instanceof Date ? value : new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

export type DateTimeFormatOptions = {
  /** 省略年份，只显示 月-日 时:分（表格里更紧凑） */
  short?: boolean
  /** 无法解析时的兜底文案，默认「—」 */
  fallback?: string
}

/** 绝对时间：2026/09/12 18:40。表格与详情页的默认选择。 */
export function formatDateTime(
  value: TimeInput,
  { short = false, fallback = DEFAULT_FALLBACK }: DateTimeFormatOptions = {},
): string {
  const date = toDate(value)
  if (!date) return fallback
  return (short ? SHORT_FORMATTER : FULL_FORMATTER).format(date)
}

/** 只要日期：2026/09/12 */
export function formatDateOnly(
  value: TimeInput,
  fallback = DEFAULT_FALLBACK,
): string {
  const date = toDate(value)
  return date ? DATE_ONLY_FORMATTER.format(date) : fallback
}

/** 只要时间：18:40:02 */
export function formatTimeOnly(
  value: TimeInput,
  fallback = DEFAULT_FALLBACK,
): string {
  const date = toDate(value)
  return date ? TIME_ONLY_FORMATTER.format(date) : fallback
}

/**
 * Unix 秒级时间戳（后端多数时间字段是秒，不是毫秒）。
 * 传毫秒会得到荒谬的年份，请确认单位后再用。
 */
export function formatUnix(
  value: number | null | undefined,
  options: DateTimeFormatOptions = {},
): string {
  if (value === null || value === undefined) {
    return options.fallback ?? DEFAULT_FALLBACK
  }
  return formatDateTime(value * 1000, options)
}

const RELATIVE_UNITS: Array<{ limit: number; divisor: number; unit: string }> =
  [
    { limit: 60, divisor: 1, unit: "秒" },
    { limit: 3600, divisor: 60, unit: "分钟" },
    { limit: 86400, divisor: 3600, unit: "小时" },
    { limit: 2592000, divisor: 86400, unit: "天" },
    { limit: 31536000, divisor: 2592000, unit: "个月" },
  ]

/** 相对时间：「刚刚」「3 分钟前」「2 天前」，超过一年回退为绝对日期。 */
export function formatRelativeTime(
  value: TimeInput,
  fallback = DEFAULT_FALLBACK,
): string {
  const date = toDate(value)
  if (!date) return fallback

  const diffSeconds = (Date.now() - date.getTime()) / 1000
  // 未来时间（时钟偏差）按「刚刚」处理，避免出现「-3 分钟前」
  if (diffSeconds < 30) return "刚刚"

  for (const { limit, divisor, unit } of RELATIVE_UNITS) {
    if (diffSeconds < limit) {
      return `${Math.floor(diffSeconds / divisor)} ${unit}前`
    }
  }
  return formatDateOnly(date)
}

/** 耗时：毫秒 → 「1.2s」/「3m 5s」。用于进度展示。 */
export function formatDuration(
  milliseconds: number | null | undefined,
  fallback = DEFAULT_FALLBACK,
): string {
  if (milliseconds === null || milliseconds === undefined) return fallback
  if (!Number.isFinite(milliseconds) || milliseconds < 0) return fallback

  if (milliseconds < 1000) return `${Math.round(milliseconds)}ms`
  const totalSeconds = milliseconds / 1000
  if (totalSeconds < 60) return `${totalSeconds.toFixed(1)}s`

  const minutes = Math.floor(totalSeconds / 60)
  const seconds = Math.round(totalSeconds % 60)
  if (minutes < 60) return `${minutes}m ${seconds}s`

  const hours = Math.floor(minutes / 60)
  return `${hours}h ${minutes % 60}m`
}

/** 「从未」语义的时间字段（如 last_seen_at）专用，语义比「—」更明确。 */
export function formatNever(
  value: TimeInput,
  neverText = "从未",
  options: DateTimeFormatOptions = {},
): string {
  return formatDateTime(value, { ...options, fallback: neverText })
}
