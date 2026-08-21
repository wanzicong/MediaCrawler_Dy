import type { LucideIcon } from "lucide-react"
import {
  BookOpen,
  Film,
  LayoutDashboard,
  ListFilter,
  MessageCircle,
  MessagesSquare,
  MonitorPlay,
  Music2,
  ScrollText,
  ShieldCheck,
  Tags,
  Target,
  UserRound,
  Users,
} from "lucide-react"

export type NavigationItem = {
  icon: LucideIcon
  title: string
  path: string
  requiresSuperuser?: boolean
}

export type NavigationModule = {
  id: "overview" | "collection" | "content" | "operations" | "system"
  label: string
  topLabel: string
  description?: string
  items: NavigationItem[]
}

const navigationModules: NavigationModule[] = [
  {
    id: "overview",
    label: "概览",
    topLabel: "工作台",
    items: [{ icon: LayoutDashboard, title: "工作台", path: "/" }],
  },
  {
    id: "collection",
    label: "采集",
    topLabel: "采集中心",
    description: "任务与策略",
    items: [
      { icon: Target, title: "赛道管理", path: "/douyin-tracks" },
      { icon: Music2, title: "抖音任务", path: "/douyin" },
      { icon: ListFilter, title: "关键词管理", path: "/douyin-keywords" },
    ],
  },
  {
    id: "content",
    label: "内容",
    topLabel: "内容资产",
    description: "资产与数据",
    items: [
      { icon: Film, title: "视频资源库", path: "/douyin-library" },
      { icon: MessageCircle, title: "评论管理", path: "/douyin-comments" },
      { icon: UserRound, title: "达人列表", path: "/douyin-creators" },
      { icon: Tags, title: "标签管理", path: "/douyin-tags" },
    ],
  },
  {
    id: "operations",
    label: "运营与风控",
    topLabel: "运营与风控",
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
      {
        icon: ScrollText,
        title: "请求日志",
        path: "/douyin-request-logs",
      },
    ],
  },
  {
    id: "system",
    label: "系统",
    topLabel: "系统管理",
    items: [
      { icon: BookOpen, title: "开发者中心", path: "/developer-tools" },
      {
        icon: Users,
        title: "用户管理",
        path: "/admin",
        requiresSuperuser: true,
      },
    ],
  },
]

export function getNavigationModules(isSuperuser = false): NavigationModule[] {
  return navigationModules.map((module) => ({
    ...module,
    items: module.items.filter(
      (item) => !item.requiresSuperuser || isSuperuser,
    ),
  }))
}

export function isNavigationItemActive(pathname: string, itemPath: string) {
  return (
    pathname === itemPath ||
    (itemPath !== "/" && pathname.startsWith(`${itemPath}/`))
  )
}

export function findActiveNavigation(pathname: string, isSuperuser = false) {
  for (const module of getNavigationModules(isSuperuser)) {
    const item = module.items.find((candidate) =>
      isNavigationItemActive(pathname, candidate.path),
    )
    if (item) {
      return { module, item }
    }
  }
  return undefined
}
