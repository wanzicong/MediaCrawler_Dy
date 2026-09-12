import { useQuery } from "@tanstack/react-query"
import { Link } from "@tanstack/react-router"
import { CheckCircle2, Circle, X } from "lucide-react"
import { useState } from "react"

import {
  DouyinAccountsService,
  DouyinKeywordsService,
  DouyinService,
  DouyinTracksService,
} from "@/client"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { readStorage, writeStorage } from "@/lib/storage"
import { cn } from "@/lib/utils"

/**
 * 新用户首次引导清单（4 步）。
 *
 * 背景：改造前新用户登录后面对的是一个空 dashboard，没有任何指引 ——
 * 不知道该「先建赛道 → 加关键词 → 登录账号 → 建任务」，直接影响留存。
 *
 * 完成状态直接由各资源的真实数量推导，不额外记录进度，
 * 这样即使用户在别处完成了某步，回到首页也会自动打勾。
 */

const DISMISS_KEY = "onboarding-checklist-dismissed"

type Step = {
  id: string
  title: string
  description: string
  to: string
  done: boolean
}

export function OnboardingChecklist() {
  const [dismissed, setDismissed] = useState(
    () => readStorage(DISMISS_KEY) === "1",
  )

  const tracksQuery = useQuery({
    queryKey: ["onboarding-tracks"],
    queryFn: () => DouyinTracksService.listTracks({ limit: 1 }),
    staleTime: 60_000,
  })
  const keywordsQuery = useQuery({
    queryKey: ["onboarding-keywords"],
    queryFn: () => DouyinKeywordsService.listKeywords({ limit: 1 }),
    staleTime: 60_000,
  })
  const accountsQuery = useQuery({
    queryKey: ["onboarding-accounts"],
    queryFn: () => DouyinAccountsService.listAccounts({ limit: 1 }),
    staleTime: 60_000,
  })
  const tasksQuery = useQuery({
    queryKey: ["onboarding-tasks"],
    queryFn: () => DouyinService.listTasks({ limit: 1 }),
    staleTime: 60_000,
  })

  const steps: Step[] = [
    {
      id: "track",
      title: "创建第一个赛道",
      description: "赛道是数据归属的主线，作品与任务都挂在赛道下。",
      to: "/douyin-tracks",
      done: (tracksQuery.data?.count ?? 0) > 0,
    },
    {
      id: "keyword",
      title: "添加采集关键词",
      description: "关键词决定按什么条件去搜索抖音内容。",
      to: "/douyin-keywords",
      done: (keywordsQuery.data?.count ?? 0) > 0,
    },
    {
      id: "account",
      title: "登录抖音账号",
      description: "采集与互动都需要一个已登录的账号。",
      to: "/douyin-accounts",
      done: (accountsQuery.data?.count ?? 0) > 0,
    },
    {
      id: "task",
      title: "创建并运行首个采集任务",
      description: "配置来源与并发参数，启动第一次采集。",
      to: "/douyin",
      done: (tasksQuery.data?.count ?? 0) > 0,
    },
  ]

  const allDone = steps.every((step) => step.done)
  const doneCount = steps.filter((step) => step.done).length
  const loading =
    tracksQuery.isLoading ||
    keywordsQuery.isLoading ||
    accountsQuery.isLoading ||
    tasksQuery.isLoading

  // 全部完成或用户主动关闭后不再打扰
  if (dismissed || allDone || loading) return null

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle className="text-base">快速上手</CardTitle>
          <p className="mt-1 text-sm text-muted-foreground">
            完成 {doneCount} / {steps.length} 步，即可跑通第一次采集。
          </p>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-7 shrink-0 text-muted-foreground"
          aria-label="不再显示引导"
          onClick={() => {
            writeStorage(DISMISS_KEY, "1")
            setDismissed(true)
          }}
        >
          <X className="size-4" />
        </Button>
      </CardHeader>
      <CardContent className="flex flex-col gap-2 pt-0">
        {steps.map((step) => (
          <Link
            key={step.id}
            to={step.to}
            className={cn(
              "flex items-start gap-3 rounded-xl border p-3 transition-colors hover:bg-muted/50",
              step.done && "opacity-60",
            )}
          >
            {step.done ? (
              <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-500" />
            ) : (
              <Circle className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
            )}
            <span className="min-w-0">
              <span
                className={cn(
                  "block text-sm font-medium",
                  step.done && "line-through",
                )}
              >
                {step.title}
              </span>
              <span className="mt-0.5 block text-xs leading-5 text-muted-foreground">
                {step.description}
              </span>
            </span>
          </Link>
        ))}
      </CardContent>
    </Card>
  )
}
