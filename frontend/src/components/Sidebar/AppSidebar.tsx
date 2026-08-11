import {
  BookOpen,
  Film,
  Home,
  MessagesSquare,
  Music2,
  ShieldCheck,
  Tags,
  Users,
} from "lucide-react"

import { SidebarAppearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
} from "@/components/ui/sidebar"
import useAuth from "@/hooks/useAuth"
import { type Item, Main } from "./Main"
import { User } from "./User"

const baseItems: Item[] = [
  { icon: Home, title: "工作台", path: "/" },
  { icon: Music2, title: "抖音任务", path: "/douyin" },
  { icon: MessagesSquare, title: "互动任务", path: "/douyin-interactions" },
  { icon: Tags, title: "关键词管理", path: "/douyin-keywords" },
  { icon: Tags, title: "标签管理", path: "/douyin-tags" },
  { icon: Film, title: "视频资源库", path: "/douyin-library" },
  { icon: ShieldCheck, title: "账号池", path: "/douyin-accounts" },
  { icon: BookOpen, title: "开发者中心", path: "/developer-tools" },
]

export function AppSidebar() {
  const { user: currentUser } = useAuth()

  const items = currentUser?.is_superuser
    ? [...baseItems, { icon: Users, title: "用户管理", path: "/admin" }]
    : baseItems

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="px-4 py-6 group-data-[collapsible=icon]:px-0 group-data-[collapsible=icon]:items-center">
        <Logo variant="responsive" />
      </SidebarHeader>
      <SidebarContent>
        <Main items={items} />
      </SidebarContent>
      <SidebarFooter>
        <SidebarAppearance />
        <User user={currentUser} />
      </SidebarFooter>
    </Sidebar>
  )
}

export default AppSidebar
