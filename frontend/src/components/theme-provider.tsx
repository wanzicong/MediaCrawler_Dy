import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react"

import { readEnumStorage, writeStorage } from "@/lib/storage"

export type Theme = "dark" | "light" | "system"
export type ThemePreset = "ocean" | "graphite" | "violet"
export type Density = "comfortable" | "compact"

// 取值白名单：既用于读取时校验，也供 index.html 的首屏脚本参照
export const THEME_MODES = ["light", "dark", "system"] as const
export const THEME_PRESETS = ["ocean", "graphite", "violet"] as const
export const DENSITIES = ["comfortable", "compact"] as const

type ThemeProviderProps = {
  children: React.ReactNode
  defaultTheme?: Theme
  storageKey?: string
}

type ThemeProviderState = {
  theme: Theme
  resolvedTheme: "dark" | "light"
  setTheme: (theme: Theme) => void
  preset: ThemePreset
  setPreset: (preset: ThemePreset) => void
  density: Density
  setDensity: (density: Density) => void
}

const initialState: ThemeProviderState = {
  theme: "system",
  resolvedTheme: "light",
  setTheme: () => null,
  preset: "violet",
  setPreset: () => null,
  density: "comfortable",
  setDensity: () => null,
}

const ThemeProviderContext = createContext<ThemeProviderState>(initialState)

export function ThemeProvider({
  children,
  defaultTheme = "system",
  storageKey = "vite-ui-theme",
  ...props
}: ThemeProviderProps) {
  // 用带兜底 + 白名单校验的读取：此前是裸 localStorage.getItem + as 断言，
  // 既会在隐私模式下抛错，也会把被手改过的脏值（如 preset="foo"）直接当成合法值。
  const [theme, setTheme] = useState<Theme>(() =>
    readEnumStorage<Theme>(storageKey, THEME_MODES, defaultTheme),
  )
  const [preset, setPresetState] = useState<ThemePreset>(() =>
    readEnumStorage<ThemePreset>(
      `${storageKey}-preset`,
      THEME_PRESETS,
      "violet",
    ),
  )
  const [density, setDensityState] = useState<Density>(() =>
    readEnumStorage<Density>(`${storageKey}-density`, DENSITIES, "comfortable"),
  )

  const getResolvedTheme = useCallback((theme: Theme): "dark" | "light" => {
    if (theme === "system") {
      return window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light"
    }
    return theme
  }, [])

  const [resolvedTheme, setResolvedTheme] = useState<"dark" | "light">(() =>
    getResolvedTheme(theme),
  )

  const updateTheme = useCallback((newTheme: Theme) => {
    const root = window.document.documentElement

    root.classList.remove("light", "dark")

    if (newTheme === "system") {
      const systemTheme = window.matchMedia("(prefers-color-scheme: dark)")
        .matches
        ? "dark"
        : "light"

      root.classList.add(systemTheme)
      return
    }

    root.classList.add(newTheme)
  }, [])

  useEffect(() => {
    updateTheme(theme)
    setResolvedTheme(getResolvedTheme(theme))

    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)")

    const handleChange = () => {
      if (theme === "system") {
        updateTheme("system")
        setResolvedTheme(getResolvedTheme("system"))
      }
    }

    mediaQuery.addEventListener("change", handleChange)

    return () => {
      mediaQuery.removeEventListener("change", handleChange)
    }
  }, [theme, updateTheme, getResolvedTheme])

  useEffect(() => {
    const root = window.document.documentElement
    root.dataset.preset = preset
    root.dataset.density = density
  }, [density, preset])

  const value = {
    theme,
    resolvedTheme,
    setTheme: (theme: Theme) => {
      writeStorage(storageKey, theme)
      setTheme(theme)
    },
    preset,
    setPreset: (value: ThemePreset) => {
      writeStorage(`${storageKey}-preset`, value)
      setPresetState(value)
    },
    density,
    setDensity: (value: Density) => {
      writeStorage(`${storageKey}-density`, value)
      setDensityState(value)
    },
  }

  return (
    <ThemeProviderContext.Provider {...props} value={value}>
      {children}
    </ThemeProviderContext.Provider>
  )
}

export const useTheme = () => {
  const context = useContext(ThemeProviderContext)

  if (context === undefined)
    throw new Error("useTheme must be used within a ThemeProvider")

  return context
}
