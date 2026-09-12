/**
 * 带兜底的 localStorage 读写。
 *
 * 背景：改造前 localStorage 散落在 5+ 处，key 硬编码，且部分调用没有 try-catch
 * （ViewModeToggle、douyin-library 的手写实现）——在隐私模式 / 禁用存储的浏览器里会直接抛错崩溃。
 * 所有新的持久化读写请走这里。
 */

/** 读字符串；不可用时返回 null 而不是抛错。 */
export function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

/** 写字符串；不可用时静默忽略。 */
export function writeStorage(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    // 隐私模式 / 配额超限：忽略，不影响功能
  }
}

export function removeStorage(key: string): void {
  try {
    window.localStorage.removeItem(key)
  } catch {
    // 同上
  }
}

/**
 * 读 JSON 并校验；解析失败或类型不符时返回 fallback。
 * `validate` 用于挡住被手改过的脏数据。
 */
export function readJsonStorage<T>(
  key: string,
  fallback: T,
  validate?: (value: unknown) => value is T,
): T {
  const raw = readStorage(key)
  if (raw === null) return fallback
  try {
    const parsed: unknown = JSON.parse(raw)
    if (validate && !validate(parsed)) return fallback
    return parsed as T
  } catch {
    return fallback
  }
}

export function writeJsonStorage(key: string, value: unknown): void {
  try {
    writeStorage(key, JSON.stringify(value))
  } catch {
    // 循环引用等序列化失败：忽略
  }
}

/**
 * 枚举型偏好的读取：只接受白名单内的值，否则回退。
 * 用于视图模式、主题、密度这类固定取值。
 */
export function readEnumStorage<T extends string>(
  key: string,
  allowed: readonly T[],
  fallback: T,
): T {
  const raw = readStorage(key)
  return raw !== null && (allowed as readonly string[]).includes(raw)
    ? (raw as T)
    : fallback
}
