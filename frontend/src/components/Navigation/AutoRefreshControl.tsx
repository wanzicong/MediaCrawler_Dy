import { RefreshCw, Timer, ZapOff } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  AUTO_REFRESH_INTERVALS,
  formatAutoRefreshInterval,
  setAutoRefreshSettings,
  useAutoRefreshSettings,
} from "@/lib/auto-refresh"
import { cn } from "@/lib/utils"

/**
 * 顶栏「自动刷新」控制：一个开关 + 一个间隔下拉。
 *
 * 之前刷新节奏写死在代码里（多数是 10 秒），用户既不能整体关掉、也不能调快调慢。
 * 这里把偏好下发到全站轮询（useSmartPolling 与各处 refetchInterval 都读它）。
 * 注意「无变化退避」仍然保留：数据一直没变时会自动拉长间隔，最长 30~60 秒，
 * 一旦有变化立刻回到用户选择的间隔。
 */
export function AutoRefreshControl() {
  const { enabled, intervalMs } = useAutoRefreshSettings()
  const label = enabled
    ? `自动刷新：每 ${formatAutoRefreshInterval(intervalMs)}`
    : "自动刷新已关闭"

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          aria-label={`自动刷新设置（${label}）`}
          title={label}
          className={cn(
            "h-8 gap-1.5 px-2 text-xs shadow-sm",
            enabled
              ? "text-muted-foreground"
              : "border-dashed text-muted-foreground/80",
          )}
        >
          {enabled ? (
            <Timer className="size-3.5" aria-hidden="true" />
          ) : (
            <ZapOff className="size-3.5" aria-hidden="true" />
          )}
          <span className="hidden md:inline">
            {enabled ? formatAutoRefreshInterval(intervalMs) : "已关闭"}
          </span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel>自动刷新</DropdownMenuLabel>
        <DropdownMenuCheckboxItem
          checked={enabled}
          // 勾选后保持菜单打开，方便接着调间隔
          onSelect={(event) => event.preventDefault()}
          onCheckedChange={(checked) =>
            setAutoRefreshSettings({ enabled: checked === true })
          }
        >
          启用自动刷新
        </DropdownMenuCheckboxItem>
        <DropdownMenuSeparator />
        <DropdownMenuLabel>刷新间隔</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={String(intervalMs)}
          onValueChange={(value) => {
            setAutoRefreshSettings({ intervalMs: Number(value) })
            // 选间隔通常意味着想立刻恢复刷新，顺手把开关打开
            setAutoRefreshSettings({ enabled: true })
          }}
        >
          {AUTO_REFRESH_INTERVALS.map((option) => (
            <DropdownMenuRadioItem
              key={option}
              value={String(option)}
              disabled={!enabled}
            >
              {formatAutoRefreshInterval(option)}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <p className="px-2 py-1.5 text-xs leading-5 text-muted-foreground">
          只在页面可见、且仍有排队 /
          执行中的任务时刷新；数据一直没变化会自动退避。
          <span className="mt-1 flex items-center gap-1">
            <RefreshCw className="size-3" aria-hidden="true" />
            关闭后仅保留页面上的手动刷新。
          </span>
        </p>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
