import { Link as RouterLink } from "@tanstack/react-router"
import { LogOut, Settings, UserRound } from "lucide-react"

import { UserMenuAppearance } from "@/components/Common/Appearance"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import useAuth from "@/hooks/useAuth"
import { getInitials } from "@/utils"

export function HeaderUserMenu() {
  const { logout, user } = useAuth()

  if (!user) return null

  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label="打开账户菜单"
          className="rounded-full"
        >
          <Avatar className="size-8">
            <AvatarFallback className="bg-zinc-600 text-xs text-white">
              {getInitials(user.full_name || "User")}
            </AvatarFallback>
          </Avatar>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" sideOffset={8} className="min-w-60">
        <DropdownMenuLabel className="font-normal">
          <div className="flex items-center gap-2.5">
            <UserRound className="size-4 shrink-0 text-muted-foreground" />
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{user.full_name}</p>
              <p className="truncate text-xs text-muted-foreground">
                {user.email}
              </p>
            </div>
          </div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <UserMenuAppearance />
        <RouterLink to="/settings">
          <DropdownMenuItem>
            <Settings />
            个人设置
          </DropdownMenuItem>
        </RouterLink>
        <DropdownMenuItem onClick={logout}>
          <LogOut />
          退出登录
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
