import { useMutation, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  Film,
  FolderPlus,
  FolderTree,
  Pencil,
  Plus,
  Trash2,
  UserRound,
} from "lucide-react"
import { useState } from "react"

import { type DouyinCategoryPublic, DouyinService } from "@/client"
import { confirmDialog } from "@/components/Common/confirm-dialog"
import { EmptyState } from "@/components/Common/EmptyState"
import { PageHero } from "@/components/Common/PageShell"
import { QueryErrorState } from "@/components/Common/QueryErrorState"
import {
  buildCategoryTree,
  useCategoryCatalog,
} from "@/components/Douyin/CategorySelect"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

export const Route = createFileRoute("/_layout/douyin-categories")({
  component: DouyinCategoryManagement,
  head: () => ({ meta: [{ title: "内容分类 - 灵感采集台" }] }),
})

/** 编辑器状态：新建（可带父分类）或重命名已有分类，两者共用同一个弹窗。 */
type EditorState =
  | { mode: "create"; parent: DouyinCategoryPublic | null }
  | { mode: "edit"; target: DouyinCategoryPublic }

function DouyinCategoryManagement() {
  const queryClient = useQueryClient()
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const categoriesQuery = useCategoryCatalog()
  const [editor, setEditor] = useState<EditorState | null>(null)

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["douyin-category-options"] })

  const removeCategory = useMutation({
    mutationFn: (categoryId: string) =>
      DouyinService.deleteCategoryRoute({ categoryId }),
    onSuccess: async () => {
      showSuccessToast("分类已删除，作品与达人本身不受影响")
      await invalidate()
    },
    onError: handleError.bind(showErrorToast),
  })

  const nodes = buildCategoryTree(categoriesQuery.data?.data ?? [])
  const totalVideos = (categoriesQuery.data?.data ?? []).reduce(
    (sum, item) => sum + item.video_count,
    0,
  )
  const totalCreators = (categoriesQuery.data?.data ?? []).reduce(
    (sum, item) => sum + item.creator_count,
    0,
  )

  return (
    <div className="flex flex-col gap-4">
      <PageHero
        eyebrow="内容资产"
        icon={FolderTree}
        title="内容分类"
        description="按运营视角把视频与达人归类，最多两级：选大类会自动带出它全部子类的数据。分类是账号私有资产，只会出现在你自己的筛选里。"
        actions={
          <Button onClick={() => setEditor({ mode: "create", parent: null })}>
            <FolderPlus />
            新建大类
          </Button>
        }
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="secondary" className="font-normal">
            大类 {nodes.length} 个
          </Badge>
          <Badge variant="secondary" className="font-normal">
            子类 {nodes.reduce((sum, node) => sum + node.children.length, 0)} 个
          </Badge>
          <Badge variant="secondary" className="gap-1 font-normal">
            <Film className="size-3" />
            已归类视频 {totalVideos}
          </Badge>
          <Badge variant="secondary" className="gap-1 font-normal">
            <UserRound className="size-3" />
            已归类达人 {totalCreators}
          </Badge>
          <span className="text-xs text-muted-foreground">
            归类入口在
            <Link className="mx-1 underline" to="/douyin-library">
              视频资源库
            </Link>
            与
            <Link className="mx-1 underline" to="/douyin-creators">
              达人列表
            </Link>
            的筛选栏
          </span>
        </div>
      </PageHero>

      <Card>
        <CardContent className="pt-6">
          {categoriesQuery.isError ? (
            <QueryErrorState
              title="分类加载失败"
              description="请检查后端服务是否可用，然后重试。"
              onRetry={() => void categoriesQuery.refetch()}
            />
          ) : categoriesQuery.isLoading ? (
            <div className="flex flex-col gap-2" aria-busy="true">
              {[0, 1, 2].map((index) => (
                <Skeleton key={index} className="h-14 w-full" />
              ))}
            </div>
          ) : nodes.length === 0 ? (
            <EmptyState
              icon={FolderTree}
              title="还没有内容分类"
              description="先建一个大类（例如「选题方向」），再在大类下面建子类。归好类后就能在作品库和达人列表里按分类筛选。"
              action={
                <Button
                  onClick={() => setEditor({ mode: "create", parent: null })}
                >
                  <FolderPlus />
                  新建大类
                </Button>
              }
            />
          ) : (
            <ul className="flex flex-col gap-3">
              {nodes.map((node) => (
                <li
                  key={node.parent.id}
                  className="rounded-xl border bg-card/60 p-3"
                >
                  <CategoryRow
                    category={node.parent}
                    isChild={false}
                    onAddChild={() =>
                      setEditor({ mode: "create", parent: node.parent })
                    }
                    onEdit={() =>
                      setEditor({ mode: "edit", target: node.parent })
                    }
                    onDelete={async () => {
                      const ok = await confirmDialog({
                        title: `删除分类「${node.parent.name}」？`,
                        description: node.children.length
                          ? `它下面的 ${node.children.length} 个子分类会一并删除；作品与达人本身不会受影响。`
                          : "归类关系会一并删除；作品与达人本身不会受影响。",
                        confirmText: "删除",
                        variant: "destructive",
                      })
                      if (!ok) return
                      removeCategory.mutate(node.parent.id)
                    }}
                  />
                  {node.children.length > 0 && (
                    <ul className="mt-2 flex flex-col gap-2 border-l border-dashed pl-3">
                      {node.children.map((child) => (
                        <li key={child.id}>
                          <CategoryRow
                            category={child}
                            isChild
                            onEdit={() =>
                              setEditor({ mode: "edit", target: child })
                            }
                            onDelete={async () => {
                              const ok = await confirmDialog({
                                title: `删除子分类「${child.name}」？`,
                                description:
                                  "归类关系会一并删除；作品与达人本身不会受影响。",
                                confirmText: "删除",
                                variant: "destructive",
                              })
                              if (!ok) return
                              removeCategory.mutate(child.id)
                            }}
                          />
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {editor && (
        <CategoryEditorDialog
          key={
            editor.mode === "create"
              ? `create-${editor.parent?.id ?? "root"}`
              : `edit-${editor.target.id}`
          }
          state={editor}
          onClose={() => setEditor(null)}
          onSaved={async (message) => {
            showSuccessToast(message)
            setEditor(null)
            await invalidate()
          }}
          onError={showErrorToast}
        />
      )}
    </div>
  )
}

/** 分类行：名称 + 描述 + 归类计数 + 操作按钮。 */
function CategoryRow({
  category,
  isChild,
  onAddChild,
  onEdit,
  onDelete,
}: {
  category: DouyinCategoryPublic
  isChild: boolean
  onAddChild?: () => void
  onEdit: () => void
  onDelete: () => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          <span
            className={
              isChild
                ? "truncate text-sm font-medium"
                : "truncate text-sm font-semibold"
            }
            title={category.name}
          >
            {category.name}
          </span>
          {!isChild && (
            <Badge variant="outline" className="font-normal">
              大类
            </Badge>
          )}
        </div>
        {category.description && (
          <p className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">
            {category.description}
          </p>
        )}
      </div>
      <Badge variant="secondary" className="gap-1 font-normal">
        <Film className="size-3" />
        {category.video_count}
      </Badge>
      <Badge variant="secondary" className="gap-1 font-normal">
        <UserRound className="size-3" />
        {category.creator_count}
      </Badge>
      <div className="flex items-center gap-1">
        {onAddChild && (
          <Button size="sm" variant="outline" onClick={onAddChild}>
            <Plus />
            子类
          </Button>
        )}
        <Button
          size="icon"
          variant="ghost"
          aria-label={`重命名分类 ${category.name}`}
          onClick={onEdit}
        >
          <Pencil />
        </Button>
        <Button
          size="icon"
          variant="ghost"
          aria-label={`删除分类 ${category.name}`}
          className="text-destructive hover:text-destructive"
          onClick={onDelete}
        >
          <Trash2 />
        </Button>
      </div>
    </div>
  )
}

/** 新建 / 重命名分类弹窗：名称必填，同级下不允许重名（后端返回 409）。 */
function CategoryEditorDialog({
  state,
  onClose,
  onSaved,
  onError,
}: {
  state: EditorState
  onClose: () => void
  onSaved: (message: string) => void
  onError: (message: string) => void
}) {
  const editing = state.mode === "edit" ? state.target : null
  const parent = state.mode === "create" ? state.parent : null
  const [name, setName] = useState(editing?.name ?? "")
  const [description, setDescription] = useState(editing?.description ?? "")
  const [sortOrder, setSortOrder] = useState(
    String(editing?.sort_order ?? parent?.sort_order ?? 0),
  )

  const save = useMutation({
    mutationFn: () => {
      const sort = Number.parseInt(sortOrder, 10)
      const normalizedSort = Number.isFinite(sort) ? sort : 0
      if (editing) {
        return DouyinService.updateCategoryRoute({
          categoryId: editing.id,
          requestBody: {
            name: name.trim(),
            description,
            sort_order: normalizedSort,
          },
        })
      }
      return DouyinService.createCategoryRoute({
        requestBody: {
          name: name.trim(),
          parent_id: parent?.id ?? null,
          description,
          sort_order: normalizedSort,
        },
      })
    },
    onSuccess: () =>
      onSaved(
        editing
          ? `分类「${name.trim()}」已更新`
          : `分类「${name.trim()}」已创建`,
      ),
    onError: handleError.bind(onError),
  })

  const title = editing
    ? "重命名分类"
    : parent
      ? `在「${parent.name}」下新建子类`
      : "新建大类"

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {editing
              ? "改名不会影响已归类的作品与达人。"
              : "分类最多两级：大类下可以建子类，子类下不能再建。"}
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="category-name">分类名称</Label>
            <Input
              id="category-name"
              value={name}
              maxLength={100}
              autoFocus
              placeholder="例如：选题方向 / 达人合作"
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="category-description">描述（可选）</Label>
            <Textarea
              id="category-description"
              value={description}
              maxLength={500}
              rows={2}
              placeholder="备注这个分类用来收什么内容"
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="category-sort">排序权重（越小越靠前）</Label>
            <Input
              id="category-sort"
              type="number"
              value={sortOrder}
              onChange={(event) => setSortOrder(event.target.value)}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button
            disabled={!name.trim() || save.isPending}
            onClick={() => save.mutate()}
          >
            {editing ? "保存" : "创建"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
