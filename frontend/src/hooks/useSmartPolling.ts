import {
  type QueryKey,
  type UseQueryOptions,
  type UseQueryResult,
  useQuery,
} from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"

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
  /**
   * 数据「结构未变化」时把轮询间隔逐步拉长的上限（毫秒），默认 30 秒。
   *
   * 依赖 TanStack 的 structuralSharing：内容没变时前后两次 data 是同一个对象，
   * 因此可以零成本判断「这次轮询是白跑的」，从而退避到 backoffMaxInterval。
   * 一旦数据真的变了，间隔立刻回到 activeInterval。传 false 关闭退避。
   */
  backoffMaxInterval?: number | false
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
 *     activeInterval: 10_000,
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
    activeInterval = 10_000,
    idleInterval = false,
    enabled = true,
    staleTime,
    loadingInterval,
    placeholderData,
    backoffMaxInterval = 30_000,
  } = options

  const visible = useDocumentVisible()
  // 连续多少次「结构未变化」；引用同一份 data 说明这次轮询没带来新信息
  const unchangedPollRef = useRef(0)
  const lastDataRef = useRef<T | undefined>(undefined)

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

      // 只有「还在进行中」的列表才轮询；终态直接停
      if (!isActive(data)) return idleInterval

      if (lastDataRef.current === data) {
        unchangedPollRef.current += 1
      } else {
        lastDataRef.current = data
        unchangedPollRef.current = 0
      }
      if (backoffMaxInterval === false || !unchangedPollRef.current) {
        return activeInterval
      }
      // 连续无变化 → 5s、10s、20s、30s（封顶）逐级退避，避免长任务下空转
      const steps = Math.min(unchangedPollRef.current, 4)
      return Math.min(activeInterval * 2 ** steps, backoffMaxInterval)
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
