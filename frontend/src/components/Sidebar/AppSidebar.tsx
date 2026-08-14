import {
  BookOpen,
  Film,
  LayoutDashboard,
  ListFilter,
  MessageCircle,
  MessagesSquare,
  MonitorPlay,
  Music2,
  ShieldCheck,
  Tags,
  Target,
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
import { Main, type NavGroup } from "./Main"
import { User } from "./User"

export function AppSidebar() {
  const { user: currentUser } = useAuth()

  const groups: NavGroup[] = [
    {
      label: "概览",
      items: [{ icon: LayoutDashboard, title: "工作台", path: "/" }],
    },
    {
      id: "collection",
      label: "采集",
      description: "任务与策略",
      items: [
        { icon: Music2, title: "抖音任务", path: "/douyin" },
        { icon: Target, title: "赛道管理", path: "/douyin-tracks" },
        { icon: ListFilter, title: "关键词管理", path: "/douyin-keywords" },
      ],
    },
    {
      id: "content",
      label: "内容",
      description: "资产与数据",
      items: [
        { icon: Film, title: "视频资源库", path: "/douyin-library" },
        { icon: MessageCircle, title: "评论管理", path: "/douyin-comments" },
        { icon: Tags, title: "标签管理", path: "/douyin-tags" },
      ],
    },
    {
      label: "运营与风控",
      items: [
        {
          icon: MessagesSquare,
          title: "互动任务",
          path: "/douyin-interactions",
        },
        { icon: ShieldCheck, title: "账号池", path: "/douyin-accounts" },
        {
          icon: MonitorPlay,
          title: "浏览器监控",
          path: "/douyin-browsers",
        },
      ],
    },
    {
      label: "系统",
      items: [
        { icon: BookOpen, title: "开发者中心", path: "/developer-tools" },
        ...(currentUser?.is_superuser
          ? [{ icon: Users, title: "用户管理", path: "/admin" }]
          : []),
      ],
    },
  ]

  return (
    <Sidebar collapsible="icon" className="border-r-0">
      <SidebarHeader className="px-4 pt-5 pb-3 group-data-[collapsible=icon]:items-center group-data-[collapsible=icon]:px-0">
        <Logo variant="responsive" />
      </SidebarHeader>
      <SidebarContent className="px-2">
        <Main groups={groups} />
      </SidebarContent>
      <SidebarFooter className="border-t border-sidebar-border/60 p-2">
        <SidebarAppearance />
        <User user={currentUser} />
      </SidebarFooter>
    </Sidebar>
  )
}

export default AppSidebar
