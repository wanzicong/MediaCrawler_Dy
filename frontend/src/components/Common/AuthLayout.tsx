import { CheckCircle2, Sparkles, Zap } from "lucide-react"

import { Appearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"
import { Footer } from "./Footer"

interface AuthLayoutProps {
  children: React.ReactNode
}

export function AuthLayout({ children }: AuthLayoutProps) {
  return (
    <div className="grid min-h-svh bg-background lg:grid-cols-[1.08fr_0.92fr]">
      <div className="relative hidden overflow-hidden bg-gradient-to-br from-violet-700 via-primary to-blue-500 p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="absolute -top-24 -right-20 size-80 rounded-full bg-white/15 blur-2xl" />
        <div className="absolute -bottom-32 -left-24 size-96 rounded-full bg-cyan-300/20 blur-3xl" />
        <div className="relative">
          <Logo variant="full" className="text-white" asLink={false} />
        </div>
        <div className="relative max-w-xl">
          <p className="flex items-center gap-2 text-sm font-semibold text-violet-100">
            <Sparkles className="size-4" />
            年轻、高效的内容运营空间
          </p>
          <h2 className="mt-4 text-4xl font-semibold leading-tight tracking-[-0.04em]">
            把采集、管理与内容洞察，放进一个清爽的工作台。
          </h2>
          <div className="mt-8 grid gap-3 text-sm text-white/85 sm:grid-cols-2">
            <p className="flex items-center gap-2">
              <Zap className="size-4 text-amber-300" />
              任务状态实时更新
            </p>
            <p className="flex items-center gap-2">
              <CheckCircle2 className="size-4 text-emerald-300" />
              账号与隐私安全隔离
            </p>
          </div>
        </div>
        <p className="relative text-xs text-white/55">抖音内容运营工作室</p>
      </div>
      <div className="flex flex-col gap-4 p-5 sm:p-8 md:p-10">
        <div className="flex justify-end">
          <Appearance />
        </div>
        <div className="flex flex-1 items-center justify-center">
          <div className="w-full max-w-sm rounded-3xl border bg-card p-6 shadow-[0_24px_60px_-36px_oklch(0.45_0.2_285/0.55)] sm:p-8">
            {children}
          </div>
        </div>
        <Footer />
      </div>
    </div>
  )
}
