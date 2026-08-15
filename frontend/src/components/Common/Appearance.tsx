import { Check, ChevronDown, Monitor, Moon, Palette, Sun } from "lucide-react"
import { useState } from "react"

import { type Theme, useTheme } from "@/components/theme-provider"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

type LucideIcon = React.FC<React.SVGProps<SVGSVGElement>>

const ICON_MAP: Record<Theme, LucideIcon> = {
  system: Monitor,
  light: Sun,
  dark: Moon,
}

export const UserMenuAppearance = () => {
  const { density, preset, setDensity, setPreset, setTheme, theme } = useTheme()
  const [expanded, setExpanded] = useState(false)
  const Icon = ICON_MAP[theme]

  return (
    <>
      <DropdownMenuItem
        aria-expanded={expanded}
        data-testid="theme-button"
        onSelect={(event) => {
          event.preventDefault()
          setExpanded((current) => !current)
        }}
      >
        <Icon className="mr-2 size-4 text-muted-foreground" />
        外观与布局
        <ChevronDown
          className={`ml-auto size-4 transition-transform ${expanded ? "rotate-180" : ""}`}
        />
      </DropdownMenuItem>
      {expanded && (
        <div
          className="max-h-[min(18rem,calc(100vh-11rem))] min-w-0 overflow-y-auto overscroll-contain border-l border-border/70 pl-1"
          data-testid="appearance-options"
        >
          <DropdownMenuLabel className="py-1 text-xs text-muted-foreground">
            明暗模式
          </DropdownMenuLabel>
          <DropdownMenuItem
            className="pl-3"
            data-testid="light-mode"
            onSelect={() => {
              setTheme("light")
            }}
          >
            <Sun className="mr-2 h-4 w-4" />
            浅色
            {theme === "light" && <Check className="ml-auto size-4" />}
          </DropdownMenuItem>
          <DropdownMenuItem
            className="pl-3"
            data-testid="dark-mode"
            onSelect={() => {
              setTheme("dark")
            }}
          >
            <Moon className="mr-2 h-4 w-4" />
            深色
            {theme === "dark" && <Check className="ml-auto size-4" />}
          </DropdownMenuItem>
          <DropdownMenuItem
            className="pl-3"
            onSelect={() => {
              setTheme("system")
            }}
          >
            <Monitor className="mr-2 h-4 w-4" />
            跟随系统
            {theme === "system" && <Check className="ml-auto size-4" />}
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuLabel className="py-1 text-xs text-muted-foreground">
            主题风格
          </DropdownMenuLabel>
          {(
            [
              ["ocean", "清透蓝"],
              ["graphite", "专业灰"],
              ["violet", "跃动紫"],
            ] as const
          ).map(([value, label]) => (
            <DropdownMenuItem
              className="pl-3"
              key={value}
              onSelect={() => {
                setPreset(value)
              }}
            >
              <Palette className="mr-2 h-4 w-4" />
              {label}
              {preset === value && <Check className="ml-auto size-4" />}
            </DropdownMenuItem>
          ))}
          <DropdownMenuSeparator />
          <DropdownMenuLabel className="py-1 text-xs text-muted-foreground">
            信息密度
          </DropdownMenuLabel>
          {(
            [
              ["comfortable", "舒适"],
              ["compact", "紧凑"],
            ] as const
          ).map(([value, label]) => (
            <DropdownMenuItem
              className="pl-3"
              key={value}
              onSelect={() => {
                setDensity(value)
              }}
            >
              {label}
              {density === value && <Check className="ml-auto size-4" />}
            </DropdownMenuItem>
          ))}
        </div>
      )}
    </>
  )
}

export const Appearance = () => {
  const { setTheme } = useTheme()

  return (
    <div className="flex items-center justify-center">
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild>
          <Button data-testid="theme-button" variant="outline" size="icon">
            <Sun className="h-[1.2rem] w-[1.2rem] rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" />
            <Moon className="absolute h-[1.2rem] w-[1.2rem] rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" />
            <span className="sr-only">切换外观</span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem
            data-testid="light-mode"
            onClick={() => setTheme("light")}
          >
            <Sun className="mr-2 h-4 w-4" />
            浅色
          </DropdownMenuItem>
          <DropdownMenuItem
            data-testid="dark-mode"
            onClick={() => setTheme("dark")}
          >
            <Moon className="mr-2 h-4 w-4" />
            深色
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => setTheme("system")}>
            <Monitor className="mr-2 h-4 w-4" />
            跟随系统
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}
