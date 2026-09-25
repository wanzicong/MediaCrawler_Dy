import type {
  CrawlTaskPublic,
  DouyinMediaProcessRequest,
  MediaStorageBackend,
} from "@/client"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"

export type StorageChoice = MediaStorageBackend | "default"

/**
 * 「下载视频与生成字幕」的全部配置项。
 *
 * 单任务弹窗与多任务批量弹窗共用这一份状态与表单，保证两处配置口径完全一致。
 */
export type MediaProcessConfig = {
  storage: StorageChoice
  translate: boolean
  subtitleOnly: boolean
  forceRetranslate: boolean
  language: string
  cookies: string
}

/** 媒体处理只依赖来源任务的这几个字段（单任务 / 批量两个入口都从这里取默认值） */
export type MediaProcessSource = Pick<
  CrawlTaskPublic,
  "id" | "track_id" | "aweme_count" | "request"
>

export function taskStorage(task: MediaProcessSource): StorageChoice {
  const value = task.request.media_storage
  return value === "local" || value === "minio" ? value : "default"
}

export function taskLanguage(task: MediaProcessSource): string {
  const value = task.request.transcription_language
  return typeof value === "string" && value.trim() ? value : "auto"
}

/** 按来源任务构造一份默认配置（沿用该任务上次的存储位置与转写语言） */
export function createMediaProcessConfig(
  task: MediaProcessSource,
): MediaProcessConfig {
  return {
    storage: taskStorage(task),
    translate: false,
    subtitleOnly: false,
    forceRetranslate: false,
    language: taskLanguage(task),
    cookies: "",
  }
}

/** 仅字幕 / 强制重译都隐含「生成字幕」，勾选它们时自动打开字幕开关 */
export function subtitlesRequested(config: MediaProcessConfig): boolean {
  return config.translate || config.subtitleOnly || config.forceRetranslate
}

/** 把配置转成接口请求体（单任务与批量共用同一套字段语义） */
export function mediaProcessRequestBody(
  config: MediaProcessConfig,
): DouyinMediaProcessRequest {
  const wantsSubtitles = subtitlesRequested(config)
  return {
    media_storage: config.storage === "default" ? undefined : config.storage,
    translate_subtitles: wantsSubtitles,
    subtitle_only: config.subtitleOnly,
    force_retranslate: wantsSubtitles && config.forceRetranslate,
    transcription_language: config.language.trim() || "auto",
    cookies: config.cookies.trim() || undefined,
  }
}

/**
 * 「下载视频与生成字幕」的配置表单。
 *
 * 受控组件：状态由调用方持有，单任务弹窗与批量弹窗因此渲染完全相同的字段与联动。
 */
export function MediaProcessFields({
  config,
  onChange,
}: {
  config: MediaProcessConfig
  onChange: (next: MediaProcessConfig) => void
}) {
  const wantsSubtitles = subtitlesRequested(config)
  return (
    <div className="space-y-5 py-2">
      <div className="space-y-2">
        <Label>新视频存储位置</Label>
        <Select
          value={config.storage}
          disabled={config.subtitleOnly}
          onValueChange={(value) =>
            onChange({ ...config, storage: value as StorageChoice })
          }
        >
          <SelectTrigger className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="default">跟随服务配置</SelectItem>
            <SelectItem value="local">本地服务器</SelectItem>
            <SelectItem value="minio">云端存储</SelectItem>
          </SelectContent>
        </Select>
        <p className="text-xs text-muted-foreground">
          {config.subtitleOnly
            ? "仅字幕模式不会上传或保留新下载的视频。"
            : "已下载文件保留原位置；未下载或失败的记录按本次选择存储。"}
        </p>
      </div>

      <CheckField
        id="post-process-translate"
        checked={config.translate}
        label="调用远程 API 生成字幕"
        description="没有本地视频时会先下载视频，再提交远程字幕服务。"
        onChange={(checked) =>
          onChange(
            checked
              ? { ...config, translate: true }
              : {
                  ...config,
                  translate: false,
                  subtitleOnly: false,
                  forceRetranslate: false,
                },
          )
        }
      />
      <CheckField
        id="post-process-subtitle-only"
        checked={config.subtitleOnly}
        label="仅生成字幕，不保留视频"
        description="勾选后自动开启字幕生成：已有下载文件直接使用；没有下载文件时临时下载，转写完成后自动删除视频，不上传本地或云端存储。"
        onChange={(checked) =>
          onChange(
            checked
              ? {
                  ...config,
                  subtitleOnly: true,
                  translate: true,
                  forceRetranslate: false,
                }
              : { ...config, subtitleOnly: false },
          )
        }
      />
      <CheckField
        id="post-process-force-translate"
        checked={config.forceRetranslate}
        label="强制重新翻译已有字幕"
        description="已完成字幕也会重新提交；未勾选时只处理缺失或失败的字幕。"
        onChange={(checked) =>
          onChange(
            checked
              ? { ...config, forceRetranslate: true, translate: true }
              : { ...config, forceRetranslate: false },
          )
        }
      />

      {wantsSubtitles && (
        <div className="space-y-2">
          <Label htmlFor="post-process-language">视频语言</Label>
          <Input
            id="post-process-language"
            value={config.language}
            placeholder="auto、zh、en"
            onChange={(event) =>
              onChange({ ...config, language: event.target.value })
            }
          />
        </div>
      )}

      <div className="space-y-2">
        <Label htmlFor="post-process-cookies">临时登录凭据（可选）</Label>
        <Textarea
          id="post-process-cookies"
          value={config.cookies}
          autoComplete="off"
          placeholder="sessionid=...；视频地址无需鉴权时可留空"
          onChange={(event) =>
            onChange({ ...config, cookies: event.target.value })
          }
        />
        <p className="text-xs text-muted-foreground">
          登录凭据只用于本次下载，任务受理后自动清除。
        </p>
      </div>
    </div>
  )
}

function CheckField({
  id,
  checked,
  disabled,
  label,
  description,
  onChange,
}: {
  id: string
  checked: boolean
  disabled?: boolean
  label: string
  description: string
  onChange: (checked: boolean) => void
}) {
  return (
    <div className="flex items-start gap-3 rounded-lg border p-3">
      <Checkbox
        id={id}
        checked={checked}
        disabled={disabled}
        onCheckedChange={(value) => onChange(value === true)}
      />
      <div className="space-y-1">
        <Label htmlFor={id}>{label}</Label>
        <p className="text-xs text-muted-foreground">{description}</p>
      </div>
    </div>
  )
}
