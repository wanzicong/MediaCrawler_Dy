/**
 * 前端 CSV 导出（报告 A12）。
 *
 * 背景：改造前导出去处零散 —— 评论页有 TXT 导出（走 while 全量翻页，会卡死主线程），
 * 字幕导出在资源库，其余列表根本没有导出入口。用户拿不到表格里的数据。
 *
 * 这里只做**当前页 / 已选中**这类小数据量的即时导出（前端拼接、瞬时完成）。
 * 「导出全部」涉及全量数据，必须走后端流式接口（见报告阶段 4，本次未做）。
 */

export type CsvColumn<T> = {
  /** 表头文字 */
  header: string
  /** 取值函数；返回 null/undefined 会被写成空单元格 */
  value: (row: T) => string | number | null | undefined
}

/**
 * CSV 单元格转义：
 * - 含逗号、引号、换行时整体加引号
 * - 内部引号翻倍
 * - 以 = + - @ 开头的内容加前导单引号，避免 Excel 当成公式执行（CSV 注入）
 */
function escapeCell(input: string | number | null | undefined): string {
  if (input === null || input === undefined) return ""
  let text = String(input)

  if (/^[=+\-@\t\r]/.test(text)) {
    text = `'${text}`
  }

  if (/[",\n\r]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`
  }
  return text
}

export function toCsv<T>(rows: T[], columns: CsvColumn<T>[]): string {
  const header = columns.map((column) => escapeCell(column.header)).join(",")
  const body = rows.map((row) =>
    columns.map((column) => escapeCell(column.value(row))).join(","),
  )
  // 前置 BOM，保证 Excel 用 UTF-8 打开中文不乱码
  return `﻿${[header, ...body].join("\r\n")}`
}

/**
 * 触发浏览器下载。
 * 文件名会自动去掉路径分隔符等非法字符。
 */
export function downloadCsv<T>(
  filename: string,
  rows: T[],
  columns: CsvColumn<T>[],
): void {
  const csv = toCsv(rows, columns)
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" })
  const url = URL.createObjectURL(blob)

  const safeName = filename.replace(/[\\/:*?"<>|]/g, "_")
  const link = document.createElement("a")
  link.href = url
  link.download = safeName.endsWith(".csv") ? safeName : `${safeName}.csv`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)

  // 立即 revoke：链接已点击，浏览器已接管下载
  URL.revokeObjectURL(url)
}
