import type { QueryKey } from "@tanstack/react-query"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import type { ListLoadMode } from "@/components/Common/LoadModeToggle"
import { useSmartPolling } from "@/hooks/useSmartPolling"

export type ListPage<T> = { data: T[]; count: number }

export type UseListFeedOptions<T> = {
  /** 基础 queryKey：包含全部筛选 / 排序条件，不含页码。 */
  queryKey: QueryKey
  pageSize: number
  /** 加载方式；滚动加载时按需续拉分片，分页时只取当前页。 */
  mode: ListLoadMode
  /** 分页模式下的页码（0 起） */
  page: number
  fetchPage: (skip: number, limit: number) => Promise<ListPage<T>>
  /** 行级稳定键，用于跨分片去重（同一个作品被两页同时返回时只留第一条） */
  getKey: (item: T) => string
  /** 还有进行中的资源时继续轮询首屏，默认不轮询 */
  isActive?: (page: ListPage<T>) => boolean
  activeInterval?: number
}

export type ListFeed<T> = {
  rows: T[]
  total: number
  isLoading: boolean
  isFetching: boolean
  isFetchingMore: boolean
  isError: boolean
  dataUpdatedAt: number
  /** 滚动加载：是否还有下一段 */
  hasMore: boolean
  loadMore: () => void
  /** 清空已加载的分片并重拉首屏（资源变更后调用） */
  refresh: () => void
  refetch: () => void
}

type Chunk<T> = {
  /** 所属的筛选签名：切换筛选后旧分片不会被拼进来，切回去还能直接复用 */
  signature: string
  skip: number
  items: T[]
}

/**
 * 列表数据源：同一份取数逻辑同时支撑「分页」与「滚动加载」两种加载方式。
 *
 * 为什么不用 useInfiniteQuery：v5 的 `refetch` 会把已加载的每一页重拉一遍，
 * 而这个列表是要按「还有没有排队 / 下载中 / 转写中」轮询的——翻到第 10 段后
 * 每 5 秒打 10 个请求不可接受。这里改成：
 * - 首屏走 useSmartPolling（继承既有的可见性暂停 + 终态停轮询）；
 * - 后续分片自己累积，轮询只重拉「内部还含进行中资源」的那几段。
 *
 * 分页模式下首屏按 page 取数，与改造前完全一致。
 */
export function useListFeed<T>({
  queryKey,
  pageSize,
  mode,
  page,
  fetchPage,
  getKey,
  isActive,
  activeInterval = 5_000,
}: UseListFeedOptions<T>): ListFeed<T> {
  // 取数与判定都用 ref 转发：调用方通常写成内联箭头函数，
  // 直接进依赖数组会让 IntersectionObserver / 轮询副作用每渲染重建一次。
  const fetchRef = useRef(fetchPage)
  fetchRef.current = fetchPage
  const isActiveRef = useRef(isActive)
  isActiveRef.current = isActive
  const getKeyRef = useRef(getKey)
  getKeyRef.current = getKey

  const signature = JSON.stringify(queryKey)
  const signatureRef = useRef(signature)
  signatureRef.current = signature

  const pageQuery = useSmartPolling(
    [...queryKey, "paged", page],
    () => fetchRef.current(page * pageSize, pageSize),
    {
      enabled: mode === "paged",
      isActive: (data) => isActiveRef.current?.(data) ?? false,
      activeInterval,
      placeholderData: (previous) => previous,
    },
  )
  const headQuery = useSmartPolling(
    [...queryKey, "head"],
    () => fetchRef.current(0, pageSize),
    {
      enabled: mode === "scroll",
      isActive: (data) => isActiveRef.current?.(data) ?? false,
      activeInterval,
      // 切筛选时保留上一屏，避免列表闪空；切加载方式时同样受益于缓存
      placeholderData: (previous) => previous,
    },
  )

  const [chunks, setChunks] = useState<Chunk<T>[]>([])
  const chunksRef = useRef(chunks)
  chunksRef.current = chunks
  // 已经到底的筛选签名：某一段返回的行数不足 pageSize（含空段）就认为后面没有了。
  // 没有这道闸，后端返回空段但 count 偏大时，哨兵会在原地反复触发续拉。
  const [exhausted, setExhausted] = useState<Record<string, boolean>>({})
  const [isFetchingMore, setFetchingMore] = useState(false)

  const head = headQuery.data?.data ?? []
  const activeChunks = useMemo(
    () => chunks.filter((chunk) => chunk.signature === signature),
    [chunks, signature],
  )

  const rows = useMemo(() => {
    if (mode === "paged") return pageQuery.data?.data ?? []
    const seen = new Set<string>()
    const merged: T[] = []
    for (const item of [
      ...head,
      ...activeChunks.flatMap((chunk) => chunk.items),
    ]) {
      const key = getKeyRef.current(item)
      if (seen.has(key)) continue
      seen.add(key)
      merged.push(item)
    }
    return merged
  }, [mode, pageQuery.data?.data, head, activeChunks])

  // 已拉取的原始行数（未去重）：续拉的 skip 必须按它算，
  // 否则被去重丢掉的行会让后一页永远差几条。
  const loadedRaw =
    head.length +
    activeChunks.reduce((total, chunk) => total + chunk.items.length, 0)
  const lastChunkLength = activeChunks.length
    ? activeChunks[activeChunks.length - 1].items.length
    : head.length
  const total =
    mode === "paged"
      ? (pageQuery.data?.count ?? 0)
      : (headQuery.data?.count ?? 0)
  const hasMore =
    mode === "scroll" &&
    total > 0 &&
    !exhausted[signature] &&
    loadedRaw < total &&
    lastChunkLength > 0

  const loadMore = useCallback(() => {
    if (mode !== "scroll" || isFetchingMore || !hasMore) return
    const skip = loadedRaw
    const chunkSignature = signatureRef.current
    setFetchingMore(true)
    void fetchRef
      .current(skip, pageSize)
      .then((result) => {
        const items = result.data ?? []
        if (items.length < pageSize) {
          setExhausted((current) => ({ ...current, [chunkSignature]: true }))
        }
        if (!items.length) return
        setChunks((current) => [
          ...current,
          { signature: chunkSignature, skip, items },
        ])
      })
      // 失败时不追加分片，按钮留在原地，用户可以再点一次
      .catch(() => undefined)
      .finally(() => setFetchingMore(false))
  }, [mode, isFetchingMore, hasMore, loadedRaw, pageSize])

  // 首屏（含轮询刷新）更新后，只把「内部还有进行中资源」的分片重拉一遍。
  // 依赖里只放首屏时间戳与模式，函数与数据都走 ref，避免每渲染重跑。
  const headUpdatedAt = headQuery.dataUpdatedAt
  const pagedUpdatedAt = pageQuery.dataUpdatedAt
  const lastRefreshedAt = useRef(0)
  useEffect(() => {
    if (mode !== "scroll") return
    if (lastRefreshedAt.current === headUpdatedAt) return
    lastRefreshedAt.current = headUpdatedAt
    const pending = chunksRef.current.filter(
      (chunk) =>
        chunk.signature === signatureRef.current &&
        (isActiveRef.current?.({
          data: chunk.items,
          count: chunk.items.length,
        }) ??
          false),
    )
    if (!pending.length) return
    let cancelled = false
    void (async () => {
      for (const chunk of pending) {
        const refreshed = await fetchRef
          .current(chunk.skip, pageSize)
          .catch(() => null)
        if (cancelled || !refreshed) continue
        setChunks((current) =>
          current.map((item) =>
            item === chunk
              ? { ...item, items: refreshed.data ?? item.items }
              : item,
          ),
        )
      }
    })()
    return () => {
      cancelled = true
    }
  }, [headUpdatedAt, mode, pageSize])

  const refresh = useCallback(() => {
    setChunks([])
    setExhausted({})
    void headQuery.refetch()
    void pageQuery.refetch()
  }, [headQuery.refetch, pageQuery.refetch])

  return {
    rows,
    total,
    isLoading: mode === "paged" ? pageQuery.isLoading : headQuery.isLoading,
    isFetching:
      mode === "paged"
        ? pageQuery.isFetching
        : headQuery.isFetching || isFetchingMore,
    isFetchingMore,
    isError: mode === "paged" ? pageQuery.isError : headQuery.isError,
    dataUpdatedAt: mode === "paged" ? pagedUpdatedAt : headUpdatedAt,
    hasMore,
    loadMore,
    refresh,
    refetch: refresh,
  }
}
