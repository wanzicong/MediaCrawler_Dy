import { useQuery } from "@tanstack/react-query"
import { createFileRoute, redirect } from "@tanstack/react-router"
import { Users } from "lucide-react"
import { useState } from "react"

import { type UserPublic, UsersService } from "@/client"
import AddUser from "@/components/Admin/AddUser"
import { columns, type UserTableData } from "@/components/Admin/columns"
import { DataTable } from "@/components/Common/DataTable"
import { PageHero } from "@/components/Common/PageShell"
import useAuth from "@/hooks/useAuth"

const PAGE_SIZE_OPTIONS = [20, 50, 100]

function getUsersQueryOptions(page: number, pageSize: number) {
  return {
    // 改为服务端分页：只取当前页，修掉原先硬编码 limit:100 导致第 100 个之后的用户不可见的问题
    queryFn: () =>
      UsersService.readUsers({ skip: page * pageSize, limit: pageSize }),
    // 分页参数必须进 queryKey，否则 page/pageSize 变化不会触发重新请求
    queryKey: ["users", { page, pageSize }],
  }
}

export const Route = createFileRoute("/_layout/admin")({
  component: Admin,
  beforeLoad: async () => {
    const user = await UsersService.readUserMe()
    if (!user.is_superuser) {
      throw redirect({
        to: "/",
      })
    }
  },
  head: () => ({
    meta: [
      {
        title: "用户管理 - 灵感采集台",
      },
    ],
  }),
})

function UsersTableContent() {
  const { user: currentUser } = useAuth()
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(PAGE_SIZE_OPTIONS[0])

  // 由 useSuspenseQuery 改为 useQuery：服务端分页需要显式 loading/错误态，
  // 而 Suspense fallback（PendingUsers）无法覆盖「翻页时保留旧页」的场景
  const {
    data: users,
    isLoading,
    isError,
    isFetching,
    refetch,
  } = useQuery(getUsersQueryOptions(page, pageSize))

  const tableData: UserTableData[] = (users?.data ?? []).map(
    (user: UserPublic) => ({
      ...user,
      isCurrentUser: currentUser?.id === user.id,
    }),
  )

  return (
    <DataTable
      columns={columns}
      data={tableData}
      loading={isLoading}
      error={
        isError
          ? {
              title: "用户列表加载失败",
              description: "请检查网络连接后重试。",
              onRetry: () => refetch(),
              retrying: isFetching,
            }
          : null
      }
      serverPagination={{
        page,
        pageSize,
        total: users?.count ?? 0,
        pageSizeOptions: PAGE_SIZE_OPTIONS,
        onPageChange: setPage,
        // 换每页条数时回到第一页，否则会停在越界页并显示空表
        onPageSizeChange: (size) => {
          setPageSize(size)
          setPage(0)
        },
      }}
    />
  )
}

function Admin() {
  return (
    <div className="page-stack">
      <PageHero
        eyebrow="系统权限"
        icon={Users}
        title="用户管理"
        description="管理平台用户账号、启用状态与超级管理员权限。"
        actions={<AddUser />}
      />
      <UsersTableContent />
    </div>
  )
}
