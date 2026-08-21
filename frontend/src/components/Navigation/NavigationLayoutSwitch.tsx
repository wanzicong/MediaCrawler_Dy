import { PanelLeft, Rows3 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

export type NavigationLayout = "sidebar" | "horizontal"

export const NAVIGATION_LAYOUT_STORAGE_KEY = "media-crawler-navigation-layout"

interface NavigationLayoutSwitchProps {
  value: NavigationLayout
  onChange: (value: NavigationLayout) => void
}

export function NavigationLayoutSwitch({
  value,
  onChange,
}: NavigationLayoutSwitchProps) {
  return (
    <fieldset className="flex min-w-0 items-center rounded-xl border border-border/70 bg-muted/45 p-1">
      <legend className="sr-only">导航布局</legend>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        aria-label="使用侧边导航"
        aria-pressed={value === "sidebar"}
        onClick={() => onChange("sidebar")}
        className={cn(
          "h-8 min-w-8 rounded-lg px-2 text-xs text-muted-foreground shadow-none hover:translate-y-0 sm:px-2.5",
          value === "sidebar" &&
            "bg-background text-foreground shadow-sm hover:bg-background hover:text-foreground",
        )}
      >
        <PanelLeft className="size-3.5" aria-hidden="true" />
        <span className="hidden md:inline">侧边</span>
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        aria-label="使用横向导航"
        aria-pressed={value === "horizontal"}
        onClick={() => onChange("horizontal")}
        className={cn(
          "h-8 min-w-8 rounded-lg px-2 text-xs text-muted-foreground shadow-none hover:translate-y-0 sm:px-2.5",
          value === "horizontal" &&
            "bg-background text-foreground shadow-sm hover:bg-background hover:text-foreground",
        )}
      >
        <Rows3 className="size-3.5" aria-hidden="true" />
        <span className="hidden md:inline">横向</span>
      </Button>
    </fieldset>
  )
}
