import { AlertTriangle, Bell, CheckCircle2, Info, Trash2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  clearNotifications,
  markAllRead,
  type NotificationKind,
  useNotifications,
  useUnreadNotificationCount,
} from "@/lib/notification-store"
import { formatRelativeTime } from "@/lib/time"
import { cn } from "@/lib/utils"

/**
 * 通知中心（铃铛 + 未读角标 + 最近 50 条）。
 *
 * 背景：操作结果此前只靠 toast 传达，错过就没有了。这里把失败/成功事件留存下来。
 *
 * 注意：Radix 的 DropdownMenu 要求菜单项是 DropdownMenuItem / DropdownMenuLabel，
 * 不能用 div 包一层（会破坏方向键导航），所以下面每条通知都是 DropdownMenuItem。
 */

const KIND_STYLES: Record<
  NotificationKind,
  { icon: string; Icon: typeof Info }
> = {
  error: { icon: "bg-destructive/10 text-destructive", Icon: AlertTriangle },
  success: {
    icon: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
    Icon: CheckCircle2,
  },
  info: { icon: "bg-muted text-muted-foreground", Icon: Info },
}

export function NotificationCenter() {
  const items = useNotifications()
  const unreadCount = useUnreadNotificationCount()

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="relative size-9"
          aria-label={
            unreadCount > 0 ? `通知，${unreadCount} 条未读` : "通知，无未读"
          }
        >
          <Bell className="size-4" />
          {unreadCount > 0 && (
            <span className="absolute -top-0.5 -right-0.5 flex min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[10px] font-semibold leading-4 text-destructive-foreground">
              {unreadCount > 99 ? "99+" : unreadCount}
            </span>
          )}
        </Button>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="end" className="w-80 p-0">
        <DropdownMenuLabel className="flex items-center justify-between px-3 py-2">
          <span>通知</span>
          {items.length > 0 && (
            <span className="text-xs font-normal text-muted-foreground">
              共 {items.length} 条
            </span>
          )}
        </DropdownMenuLabel>
        <DropdownMenuSeparator className="my-0" />

        {items.length === 0 ? (
          <DropdownMenuItem disabled className="px-3 py-6 text-center text-sm">
            暂无通知
          </DropdownMenuItem>
        ) : (
          <>
            <div className="max-h-80 overflow-y-auto">
              {items.map((item) => {
                const { icon, Icon } = KIND_STYLES[item.kind]
                return (
                  <DropdownMenuItem
                    key={item.id}
                    className="items-start gap-2.5 px-3 py-2.5"
                  >
                    <span
                      className={cn(
                        "mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md",
                        icon,
                      )}
                    >
                      <Icon className="size-3.5" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span
                        className={cn(
                          "block truncate text-sm",
                          !item.read && "font-medium",
                        )}
                      >
                        {item.title}
                      </span>
                      {item.description && (
                        <span className="mt-0.5 block text-xs leading-5 text-muted-foreground">
                          {item.description}
                        </span>
                      )}
                      <span className="mt-1 block text-[10px] text-muted-foreground/80">
                        {formatRelativeTime(item.createdAt)}
                      </span>
                    </span>
                    {!item.read && (
                      <span className="mt-1.5 size-2 shrink-0 rounded-full bg-primary" />
                    )}
                  </DropdownMenuItem>
                )
              })}
            </div>
            <DropdownMenuSeparator className="my-0" />
            <DropdownMenuItem
              className="justify-center gap-1.5 text-sm"
              onSelect={() => markAllRead()}
            >
              全部标为已读
            </DropdownMenuItem>
            <DropdownMenuItem
              className="justify-center gap-1.5 text-sm text-destructive focus:text-destructive"
              onSelect={() => clearNotifications()}
            >
              <Trash2 className="size-3.5" />
              清空通知
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
