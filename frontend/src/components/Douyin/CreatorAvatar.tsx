import { Avatar, AvatarFallback } from "@/components/ui/avatar"

const avatarTones = [
  "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300",
  "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
  "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
  "bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-300",
  "bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-300",
  "bg-cyan-100 text-cyan-700 dark:bg-cyan-950 dark:text-cyan-300",
]

export function CreatorAvatar({
  name,
  seed,
  className = "size-8",
  initialClassName = "text-xs",
}: {
  name: string
  seed: string
  className?: string
  initialClassName?: string
}) {
  let hash = 0
  for (const ch of seed) hash = (hash * 31 + (ch.codePointAt(0) ?? 0)) % 997
  const tone = avatarTones[hash % avatarTones.length]
  const initial = (name.trim()[0] ?? "匿").toUpperCase()
  return (
    <Avatar className={`${className} border`}>
      <AvatarFallback className={`${tone} ${initialClassName} font-semibold`}>
        {initial}
      </AvatarFallback>
    </Avatar>
  )
}
