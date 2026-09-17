import {
  type QueryKey,
  type UseQueryOptions,
  type UseQueryResult,
  useQuery,
} from "@tanstack/react-query"
import { useEffect, useState } from "react"

/**
 * 智能轮询：按业务状态自动停止 / 降频，并在页面不可见时暂停。
 *
 * 背景：改造前全仓有 34 处手写 `refetchInterval`，其中相当一部分没有终态判断
 * （任务跑完了还在每秒拉）、后台标签页仍在全速轮询
 * （`refetchIntervalInBackground` 全仓出现次数为 0）。
 * 新代码请用这个 hook，不要再手写 refetchInterval。
 *
 * 正确实现本来就散落在少数几处（MediaPipelinePanel / TaskInteractionsPanel /
 * TaskResults），这里把它们统一成一个契约。
 */

/** 页面可见性：切到后台标签页时返回 false。 */
function useDocumentVisible(): boolean {
  const [visible, setVisible] = useState(
    () =>
      typeof document === "undefined" || document.visibilityState !== "hidden",
  )

  useEffect(() => {
    const onChange = () => {
      setVisible(document.visibilityState !== "hidden")
    }
    document.addEventListener("visibilitychange", onChange)
    return () => document.removeEventListener("visibilitychange", onChange)
  }, [])

  return visible
}

export type SmartPollingOptions<T> = {
  /** 返回 true 表示「还有活跃任务」，需要按 activeInterval 继续轮询。 */
  isActive: (data: T) => boolean
  /** 活跃时的轮询间隔（毫秒），默认 2000。 */
  activeInterval?: number
  /**
   * 终态时的轮询间隔。默认 `false` —— 即停止轮询。
   * 只有确实需要「静默保活」的场景才传数字。
   */
  idleInterval?: number | false
  /** 传 false 可整体禁用该 query（如依赖的筛选条件尚未就绪）。 */
  enabled?: boolean
  /** 缓存新鲜度，默认继承 QueryClient 的全局设置。 */
  staleTime?: number
  /** 首次拿到数据前的轮询间隔，默认等同于 activeInterval。 */
  loadingInterval?: number
  /**
   * 透传给 useQuery：翻页 / 换筛选时保留上一份数据，避免列表闪空。
   */
  placeholderData?: UseQueryOptions<T, Error, T, QueryKey>["placeholderData"]
}

/**
 * 用法：
 * ```ts
 * const tasksQuery = useSmartPolling(
 *   ["douyin-tasks", trackId],
 *   () => DouyinService.listTasks({ trackId }),
 *   {
 *     isActive: (data) =>
 *       data.data.some((t) => t.status === "running" || t.status === "queued"),
 *     activeInterval: 3_000,
 *   },
 * )
 * ```
 */
export function useSmartPolling<T>(
  queryKey: QueryKey,
  queryFn: () => Promise<T>,
  options: SmartPollingOptions<T>,
): UseQueryResult<T, Error> {
  const {
    isActive,
    activeInterval = 2_000,
    idleInterval = false,
    enabled = true,
    staleTime,
    loadingInterval,
    placeholderData,
  } = options

  const visible = useDocumentVisible()

  return useQuery<T, Error>({
    queryKey,
    queryFn,
    enabled,
    staleTime,
    placeholderData,
    refetchInterval: (query) => {
      // 后台标签页一律暂停，切回来时 TanStack 会自动补一次刷新
      if (!visible) return false

      const data = query.state.data
      // 还没拿到首屏数据：按活跃频率等，拿到后再判断
      if (data === undefined) return loadingInterval ?? activeInterval

      return isActive(data) ? activeInterval : idleInterval
    },
  })
}

/**
 * 判定一组状态里是否还残留「进行中」的状态。
 * 各列表的终态集合不同，所以做成工具而不是写死。
 */
export function hasActiveStatus<T>(
  items: T[],
  getStatus: (item: T) => string | null | undefined,
  terminalStatuses: readonly string[],
): boolean {
  return items.some((item) => {
    const status = getStatus(item)
    return (
      status !== null &&
      status !== undefined &&
      !terminalStatuses.includes(status)
    )
  })
}
