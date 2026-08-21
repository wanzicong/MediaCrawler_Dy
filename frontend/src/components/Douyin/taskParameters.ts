import type {
  DouyinRequestDelayLevel,
  MediaProcessingMode,
  MediaStorageBackend,
} from "@/client"

/**
 * “创建任务”和“赛道启动任务”共用的运行参数基线。
 * 两个入口必须从这里取默认值，避免相同字段出现不同的初始行为。
 */
export const DOUYIN_TASK_PARAMETER_DEFAULTS = {
  startPage: 1,
  maxAwemes: 10,
  fetchComments: true,
  fetchSubComments: false,
  maxComments: 10,
  concurrency: 1,
  delayLevel: "steady" as DouyinRequestDelayLevel,
  requestInterval: 1,
  publishTime: 0,
  downloadMedia: false,
  translateSubtitles: false,
  mediaProcessingMode: "immediate" as Exclude<MediaProcessingMode, "none">,
  mediaStorage: "minio" as MediaStorageBackend | "default",
  transcriptionLanguage: "auto",
} as const
