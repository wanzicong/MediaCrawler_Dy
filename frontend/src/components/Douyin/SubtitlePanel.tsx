import { Captions, Copy } from "lucide-react"

import type { DouyinMediaAssetPublic } from "@/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import useCustomToast from "@/hooks/useCustomToast"

export function SubtitleDialog({
  asset,
  title,
}: {
  asset: DouyinMediaAssetPublic
  title?: string
}) {
  const subtitle = asset.subtitle
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="查看字幕"
          disabled={!subtitle}
        >
          <Captions />
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>字幕信息</DialogTitle>
          <DialogDescription>
            {title ? `${title} · ` : ""}作品 {asset.aweme_id}
          </DialogDescription>
        </DialogHeader>
        {subtitle ? (
          <SubtitlePanel asset={asset} />
        ) : (
          <p className="text-sm text-muted-foreground">
            该作品还没有字幕记录。
          </p>
        )}
      </DialogContent>
    </Dialog>
  )
}

export function SubtitlePanel({ asset }: { asset: DouyinMediaAssetPublic }) {
  const { showErrorToast, showSuccessToast } = useCustomToast()
  const subtitle = asset.subtitle
  if (!subtitle) {
    return (
      <p className="text-sm text-muted-foreground">该作品还没有字幕记录。</p>
    )
  }
  const fullText = subtitle.full_text.trim()
  const segments = subtitle.segments
    .map((segment) => segmentParts(segment))
    .filter((segment) => segment.text)
  const copySubtitle = async () => {
    try {
      await navigator.clipboard.writeText(fullText)
      showSuccessToast("字幕内容已复制")
    } catch {
      showErrorToast("复制失败，请手动选择文本复制")
    }
  }
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        <Badge
          variant={subtitle.status === "completed" ? "secondary" : "outline"}
        >
          {subtitleStatusLabel(subtitle.status)}
        </Badge>
        {subtitle.language && (
          <Badge variant="outline">{subtitle.language}</Badge>
        )}
        {subtitle.model && <Badge variant="outline">{subtitle.model}</Badge>}
        {subtitle.actual_backend && (
          <Badge variant="outline">{subtitle.actual_backend}</Badge>
        )}
        {subtitle.duration_seconds > 0 && (
          <Badge variant="outline">
            时长 {formatDuration(subtitle.duration_seconds)}
          </Badge>
        )}
      </div>
      {subtitle.error && (
        <p className="rounded-lg bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {subtitle.error}
        </p>
      )}
      {fullText ? (
        <>
          <div className="max-h-56 overflow-y-auto rounded-lg border bg-muted/40 p-3">
            <p className="whitespace-pre-wrap break-words text-sm leading-6">
              {fullText}
            </p>
          </div>
          <div className="flex justify-end">
            <Button size="sm" variant="outline" onClick={copySubtitle}>
              <Copy />
              复制字幕
            </Button>
          </div>
        </>
      ) : (
        <p className="text-sm text-muted-foreground">字幕全文为空。</p>
      )}
      {segments.length > 0 && (
        <div>
          <p className="mb-1.5 text-xs font-medium text-muted-foreground">
            分段（{segments.length}）
          </p>
          <div className="max-h-48 overflow-y-auto rounded-lg border">
            <table className="w-full text-xs">
              <tbody>
                {segments.map((segment, index) => (
                  <tr
                    key={`${segment.start ?? index}-${index}`}
                    className="border-b last:border-0"
                  >
                    <td className="w-20 whitespace-nowrap px-2 py-1.5 font-mono text-muted-foreground">
                      {segment.start !== null
                        ? formatDuration(segment.start)
                        : "-"}
                    </td>
                    <td className="px-2 py-1.5 leading-5">{segment.text}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

function segmentParts(segment: Record<string, unknown>) {
  const text = typeof segment.text === "string" ? segment.text.trim() : ""
  const start = typeof segment.start === "number" ? segment.start : null
  const end = typeof segment.end === "number" ? segment.end : null
  return { text, start, end }
}

function formatDuration(seconds: number) {
  const total = Math.max(0, Math.round(seconds))
  const minutes = Math.floor(total / 60)
  const rest = total % 60
  return `${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`
}

function subtitleStatusLabel(status: string) {
  return (
    {
      pending: "字幕排队",
      running: "字幕处理中",
      completed: "字幕完成",
      failed: "字幕失败",
    }[status] ?? status
  )
}
