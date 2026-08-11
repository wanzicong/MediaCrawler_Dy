export function Footer() {
  const currentYear = new Date().getFullYear()

  return (
    <footer className="border-t border-border/60 px-4 py-4 text-center text-xs text-muted-foreground">
      © {currentYear} 灵感采集台 · 内容运营工作台
    </footer>
  )
}
