import { createFileRoute } from "@tanstack/react-router"
import { Settings2 } from "lucide-react"

import { PageHero } from "@/components/Common/PageShell"
import ChangePassword from "@/components/UserSettings/ChangePassword"
import DeleteAccount from "@/components/UserSettings/DeleteAccount"
import UserInformation from "@/components/UserSettings/UserInformation"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import useAuth from "@/hooks/useAuth"

const tabsConfig = [
  { value: "my-profile", title: "个人资料", component: UserInformation },
  { value: "password", title: "登录密码", component: ChangePassword },
  { value: "danger-zone", title: "危险操作", component: DeleteAccount },
]

export const Route = createFileRoute("/_layout/settings")({
  component: UserSettings,
  head: () => ({
    meta: [
      {
        title: "个人设置 - 灵感采集台",
      },
    ],
  }),
})

function UserSettings() {
  const { user: currentUser } = useAuth()
  // tabsConfig 恰好 3 项，slice(0, 3) 与原数组等长 —— 原写法两个分支结果相同，
  // 超管判定完全失效。正确语义：超管看全部，普通用户看不到「危险操作」。
  const finalTabs = currentUser?.is_superuser
    ? tabsConfig
    : tabsConfig.slice(0, 2)

  if (!currentUser) {
    return null
  }

  return (
    <div className="page-stack">
      <PageHero
        eyebrow="账号与安全"
        icon={Settings2}
        title="个人设置"
        description="管理个人资料、登录密码与账号安全选项。"
      />

      <Tabs defaultValue="my-profile" className="gap-5">
        <TabsList className="h-auto w-full justify-start overflow-x-auto rounded-xl bg-muted/70 p-1 sm:w-auto">
          {finalTabs.map((tab) => (
            <TabsTrigger key={tab.value} value={tab.value}>
              {tab.title}
            </TabsTrigger>
          ))}
        </TabsList>
        {finalTabs.map((tab) => (
          <TabsContent key={tab.value} value={tab.value}>
            <tab.component />
          </TabsContent>
        ))}
      </Tabs>
    </div>
  )
}
