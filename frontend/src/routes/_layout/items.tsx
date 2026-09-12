import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { Search } from "lucide-react"
import { useState } from "react"

import { ItemsService } from "@/client"
import { DataTable } from "@/components/Common/DataTable"
import { EmptyState } from "@/components/Common/EmptyState"
import { PageHero } from "@/components/Common/PageShell"
import AddItem from "@/components/Items/AddItem"
import { columns } from "@/components/Items/columns"

const DEFAULT_PAGE_SIZE = 20

function getItemsQueryOptions(page: number, pageSize: number) {
  return {
    // 分页参数进入 queryKey，翻页才会发起新请求；后端返回 { data, count }
    queryFn: () =>
      ItemsService.readItems({ skip: page * pageSize, limit: pageSize }),
    queryKey: ["items", page, pageSize],
    // 翻页时保留上一页数据，避免表格闪成空态
    placeholderData: keepPreviousData,
  }
}

export const Route = createFileRoute("/_layout/items")({
  component: Items,
  head: () => ({
    meta: [
      {
        title: "通用条目 - 灵感采集台",
      },
    ],
  }),
})

function ItemsTable() {
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)
  const itemsQuery = useQuery(getItemsQueryOptions(page, pageSize))

  return (
    <DataTable
      columns={columns}
      data={itemsQuery.data?.data ?? []}
      loading={itemsQuery.isPending}
      // 请求失败时给出错误态与重试入口，而不是伪装成「暂无条目」
      error={
        itemsQuery.isError
          ? {
              title: "条目列表加载失败",
              description: "无法获取条目数据，请检查网络或后端服务后重试。",
              onRetry: () => void itemsQuery.refetch(),
              retrying: itemsQuery.isFetching,
            }
          : null
      }
      emptyState={
        <EmptyState
          icon={Search}
          title="暂时没有条目"
          description="新增一条内容后即可开始管理"
        />
      }
      serverPagination={{
        page,
        pageSize,
        total: itemsQuery.data?.count ?? 0,
        onPageChange: setPage,
        onPageSizeChange: (size) => {
          // 改变每页条数后原页码可能越界，一并重置回第一页
          setPageSize(size)
          setPage(0)
        },
        className: "rounded-xl border bg-muted/20 p-4",
      }}
    />
  )
}

function Items() {
  return (
    <div className="page-stack">
      <PageHero
        eyebrow="通用内容"
        icon={Search}
        title="条目管理"
        description="创建和管理通用内容条目。"
        actions={<AddItem />}
      />
      <ItemsTable />
    </div>
  )
}
