import { useQuery } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  ArrowDownWideNarrow,
  Clapperboard,
  Film,
  RefreshCw,
  Search,
  UserRound,
  Users,
} from "lucide-react"
import { useMemo, useState } from "react"

import { DouyinService } from "@/client"
import { PageHero } from "@/components/Common/PageShell"
import { CreatorAvatar } from "@/components/Douyin/CreatorAvatar"
import { allTracksValue, TrackSelect } from "@/components/Douyin/TrackSelect"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

export const Route = createFileRoute("/_layout/douyin-creators")({
  component: DouyinCreatorDirectory,
  head: () => ({ meta: [{ title: "达人列表 - 灵感采集台" }] }),
})

type SortValue = "work_count:desc" | "work_count:asc" | "nickname"

function DouyinCreatorDirectory() {
  const [trackId, setTrackId] = useState(allTracksValue)
  const [search, setSearch] = useState("")
  const [sort, setSort] = useState<SortValue>("work_count:desc")

  const creatorsQuery = useQuery({
    queryKey: ["douyin-creators", trackId],
    queryFn: () =>
      DouyinService.listLibraryCreators({
        trackId: trackId && trackId !== allTracksValue ? trackId : undefined,
      }),
    staleTime: 30_000,
  })
  const creators = creatorsQuery.data?.data ?? []
  const totalWorks = useMemo(
    () => creators.reduce((sum, creator) => sum + creator.work_count, 0),
    [creators],
  )
  const visibleCreators = useMemo(() => {
    const keyword = search.trim().toLowerCase()
    const filtered = keyword
      ? creators.filter((creator) =>
          (creator.nickname || "").toLowerCase().includes(keyword),
        )
      : creators
    return [...filtered].sort((a, b) => {
      if (sort === "nickname") {
        return (a.nickname || "").localeCompare(b.nickname || "", "zh-CN")
      }
      const diff = a.work_count - b.work_count
      return sort === "work_count:asc" ? diff : -diff
    })
  }, [creators, search, sort])

  return (
    <div className="page-stack">
      <PageHero
        eyebrow="内容资产中心"
        icon={Users}
        title="达人列表"
        description="聚合全部已爬取作品对应的达人，按赛道查看他们的作品规模，并一键进入该达人的视频列表。"
        actions={
          <Button
            variant="outline"
            onClick={() => creatorsQuery.refetch()}
            disabled={creatorsQuery.isFetching}
          >
            <RefreshCw
              className={creatorsQuery.isFetching ? "animate-spin" : ""}
            />
            刷新数据
          </Button>
        }
      >
        <div className="flex flex-wrap gap-2">
          <SummaryPill
            icon={UserRound}
            label="达人"
            value={creatorsQuery.data?.count ?? 0}
          />
          <SummaryPill
            icon={Clapperboard}
            label="累计作品"
            value={totalWorks}
          />
          <SummaryPill
            icon={Search}
            label="当前显示"
            value={visibleCreators.length}
          />
        </div>
      </PageHero>

      <Card>
        <CardContent className="flex flex-col gap-3 p-3 md:p-4 lg:flex-row lg:items-center">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="搜索达人昵称"
              className="pl-9"
            />
          </div>
          <TrackSelect
            value={trackId}
            onValueChange={setTrackId}
            includeAll
            allowDisabled
            className="lg:w-64"
            ariaLabel="按赛道筛选达人"
          />
          <Select
            value={sort}
            onValueChange={(value) => setSort(value as SortValue)}
          >
            <SelectTrigger className="lg:w-44" aria-label="达人排序方式">
              <ArrowDownWideNarrow />
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="work_count:desc">作品最多</SelectItem>
              <SelectItem value="work_count:asc">作品最少</SelectItem>
              <SelectItem value="nickname">昵称 A → Z</SelectItem>
            </SelectContent>
          </Select>
        </CardContent>
      </Card>

      {visibleCreators.length ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
          {visibleCreators.map((creator) => (
            <Card
              key={creator.creator_hash}
              className="transition hover:shadow-md"
            >
              <CardContent className="flex items-center gap-3 p-4">
                <CreatorAvatar
                  name={creator.nickname}
                  seed={creator.creator_hash}
                  className="size-12"
                  initialClassName="text-base"
                />
                <div className="min-w-0 flex-1">
                  <p
                    className="truncate font-medium"
                    title={creator.nickname || "匿名达人"}
                  >
                    {creator.nickname || "匿名达人"}
                  </p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    已爬取 {creator.work_count} 个作品
                  </p>
                </div>
                <Button size="sm" variant="outline" asChild>
                  <Link
                    to="/douyin-library"
                    search={{
                      track: undefined,
                      q: undefined,
                      task: undefined,
                      creator: creator.creator_hash,
                      tag: undefined,
                      storage: undefined,
                      subtitle: undefined,
                      sort: undefined,
                    }}
                    aria-label={`查看 ${creator.nickname || "匿名达人"} 的作品`}
                  >
                    <Film />
                    作品
                  </Link>
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <div className="rounded-3xl border border-dashed py-24 text-center text-muted-foreground">
          <Users className="mx-auto mb-4 size-10 opacity-40" />
          {creatorsQuery.isLoading
            ? "正在加载达人…"
            : search.trim()
              ? "没有昵称匹配的达人"
              : "当前范围内还没有爬取到任何达人"}
        </div>
      )}
    </div>
  )
}

function SummaryPill({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof UserRound
  label: string
  value: number
}) {
  return (
    <div className="flex items-center gap-2 rounded-lg border bg-card/75 px-3 py-1.5 text-xs shadow-sm">
      <Icon className="size-3.5 text-primary" />
      <span className="text-muted-foreground">{label}</span>
      <strong className="text-sm tabular-nums">{value}</strong>
    </div>
  )
}
