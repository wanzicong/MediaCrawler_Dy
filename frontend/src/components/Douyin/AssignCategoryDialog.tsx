import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Check, FolderMinus, FolderPlus, FolderTree } from "lucide-react"
import { useState } from "react"

import { DouyinService } from "@/client"
import { EmptyState } from "@/components/Common/EmptyState"
import {
  buildCategoryTree,
  useCategoryCatalog,
} from "@/components/Douyin/CategorySelect"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { handleError } from "@/utils"

/**
 * 批量归类弹窗：把选中的视频 / 达人加入或移出某个分类。
 *
 * 与「内容分类」管理页共用同一份分类缓存（queryKey 相同），
 * 归类成功后同时失效分类缓存，让管理页与筛选下拉的计数立即刷新。
 */
export function AssignCategoryDialog({
  open,
  onOpenChange,
  awemeIds = [],
  creatorIds = [],
  onDone,
  onError,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** 待归类的平台作品号（视频来源） */
  awemeIds?: string[]
  /** 待归类的达人名单 ID（达人来源） */
  creatorIds?: string[]
  onDone: (message: string) => void
  onError: (message: string) => void
}) {
  const queryClient = useQueryClient()
  const categoriesQuery = useCategoryCatalog(open)
  const [selectedId, setSelectedId] = useState("")

  const attach = useMutation({
    mutationFn: (categoryId: string) =>
      DouyinService.assignCategoryItemsRoute({
        categoryId,
        requestBody: { aweme_ids: awemeIds, creator_ids: creatorIds },
      }),
    onSuccess: async (result) => {
      onDone(
        `已加入分类：视频 ${result.video_count} 条 · 达人 ${result.creator_count} 位`,
      )
      await queryClient.invalidateQueries({
        queryKey: ["douyin-category-options"],
      })
      onOpenChange(false)
    },
    onError: handleError.bind(onError),
  })

  const detach = useMutation({
    mutationFn: (categoryId: string) =>
      DouyinService.unassignCategoryItemsRoute({
        categoryId,
        requestBody: { aweme_ids: awemeIds, creator_ids: creatorIds },
      }),
    onSuccess: async (result) => {
      onDone(
        `已移出分类：视频 ${result.video_count} 条 · 达人 ${result.creator_count} 位`,
      )
      await queryClient.invalidateQueries({
        queryKey: ["douyin-category-options"],
      })
      onOpenChange(false)
    },
    onError: handleError.bind(onError),
  })

  const nodes = buildCategoryTree(categoriesQuery.data?.data ?? [])
  const pending = attach.isPending || detach.isPending
  const target = awemeIds.length
    ? `选中的 ${awemeIds.length} 个视频`
    : `选中的 ${creatorIds.length} 位达人`

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>归类到内容分类</DialogTitle>
          <DialogDescription>
            把{target}
            加入或移出某个分类；选大类不会自动带上子类，归类是精确绑定的。
          </DialogDescription>
        </DialogHeader>

        {categoriesQuery.isError ? (
          <div
            role="alert"
            className="rounded-md border border-destructive/35 bg-destructive/5 px-3 py-2 text-sm text-destructive"
          >
            分类加载失败，请稍后重试。
          </div>
        ) : categoriesQuery.isLoading ? (
          <div className="flex flex-col gap-2">
            {[0, 1, 2].map((index) => (
              <Skeleton key={index} className="h-10 w-full" />
            ))}
          </div>
        ) : nodes.length === 0 ? (
          <EmptyState
            icon={FolderTree}
            title="还没有内容分类"
            description="先去「内容分类」页建一个大类，再回来归类。"
          />
        ) : (
          <div
            role="listbox"
            aria-label="选择目标分类"
            className="max-h-72 overflow-y-auto rounded-lg border p-1"
          >
            {nodes.map((node) => (
              <div key={node.parent.id}>
                <CategoryOption
                  category={node.parent}
                  selected={selectedId === node.parent.id}
                  onSelect={() => setSelectedId(node.parent.id)}
                />
                {node.children.map((child) => (
                  <CategoryOption
                    key={child.id}
                    category={child}
                    indent
                    selected={selectedId === child.id}
                    onSelect={() => setSelectedId(child.id)}
                  />
                ))}
              </div>
            ))}
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button
            variant="outline"
            disabled={!selectedId || pending}
            onClick={() => detach.mutate(selectedId)}
          >
            <FolderMinus />
            移出分类
          </Button>
          <Button
            disabled={!selectedId || pending}
            onClick={() => attach.mutate(selectedId)}
          >
            <FolderPlus />
            加入分类
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** 分类可选项（大类 / 子类，子类缩进显示）。 */
function CategoryOption({
  category,
  selected,
  indent = false,
  onSelect,
}: {
  category: {
    id: string
    name: string
    video_count: number
    creator_count: number
  }
  selected: boolean
  indent?: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      role="option"
      aria-selected={selected}
      onClick={onSelect}
      className={cn(
        "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition hover:bg-accent",
        indent && "pl-6",
        selected && "bg-accent",
      )}
    >
      <Check
        className={cn("size-3.5 shrink-0", !selected && "opacity-0")}
        aria-hidden="true"
      />
      <span className="min-w-0 flex-1 truncate">{category.name}</span>
      <Badge variant="secondary" className="font-normal">
        {category.video_count} 视频 · {category.creator_count} 达人
      </Badge>
    </button>
  )
}
