import { readStorage, removeStorage, writeStorage } from "@/lib/storage"

/**
 * 访问令牌的唯一读写入口。
 *
 * 背景：改造前有 11 处直接调 `localStorage.getItem("access_token")`，
 * 散落在 8 个文件里（含二维码、视频预览、媒体下载、导出等手动 fetch 的场景）。
 * 问题有两个：一是隐私模式 / 禁用存储时会直接抛错，二是没有单一改动点，
 * 将来换存储方式（如内存 + refresh token）要改 8 个地方。
 *
 * 新代码请一律用这里，不要再直接碰 localStorage 的 access_token。
 */

const ACCESS_TOKEN_KEY = "access_token"

/** 取令牌；不存在或存储不可用时返回空串（可直接拼进 Authorization 头）。 */
export function getAccessToken(): string {
  return readStorage(ACCESS_TOKEN_KEY) ?? ""
}

/** 令牌是否存在（不做有效性校验，有效性见 useAuth 的 isLoggedIn）。 */
export function hasAccessToken(): boolean {
  return readStorage(ACCESS_TOKEN_KEY) !== null
}

export function setAccessToken(token: string): void {
  writeStorage(ACCESS_TOKEN_KEY, token)
}

export function clearAccessToken(): void {
  removeStorage(ACCESS_TOKEN_KEY)
}
