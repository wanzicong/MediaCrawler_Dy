import { AxiosError } from "axios"
import type { ApiError } from "./client"

const DEFAULT_ERROR_MESSAGE = "请求失败，请稍后重试"

const ERROR_MESSAGE_TRANSLATIONS: Record<string, string> = {
  "Could not validate credentials": "登录状态已失效，请重新登录",
  "Inactive user": "账号已停用",
  "Incorrect email or password": "邮箱或密码错误",
  "Incorrect password": "当前密码错误",
  "Invalid token": "链接已失效，请重新操作",
  "New password cannot be the same as the current one":
    "新密码不能与当前密码相同",
  "Not enough permissions": "权限不足",
  "Something went wrong.": DEFAULT_ERROR_MESSAGE,
  "The user with this email already exists in the system.":
    "该邮箱已注册，请直接登录",
  "The user with this email already exists in the system":
    "该邮箱已注册，请直接登录",
  "User with this email already exists": "该邮箱已注册，请直接登录",
  "User not found": "用户不存在",
}

function localizeErrorMessage(message: unknown): string {
  if (typeof message !== "string" || !message.trim()) {
    return DEFAULT_ERROR_MESSAGE
  }
  const normalized = message.trim()
  return ERROR_MESSAGE_TRANSLATIONS[normalized] ?? normalized
}

function extractErrorMessage(err: ApiError): string {
  if (err instanceof AxiosError) {
    return err.code === "ERR_NETWORK"
      ? "无法连接服务，请检查网络后重试"
      : DEFAULT_ERROR_MESSAGE
  }

  const errDetail = (err.body as any)?.detail
  if (Array.isArray(errDetail) && errDetail.length > 0) {
    return localizeErrorMessage(errDetail[0].msg)
  }
  if (errDetail && typeof errDetail === "object") {
    return localizeErrorMessage(errDetail.message || errDetail.detail)
  }
  return localizeErrorMessage(errDetail)
}

export const handleError = function (
  this: (msg: string) => void,
  err: ApiError,
) {
  const errorMessage = extractErrorMessage(err)
  this(errorMessage)
}

export const getInitials = (name: string): string => {
  return name
    .split(" ")
    .slice(0, 2)
    .map((word) => word[0])
    .join("")
    .toUpperCase()
}

export const getDouyinVideoUrl = (awemeId: string): string =>
  `https://www.douyin.com/video/${encodeURIComponent(awemeId)}`
