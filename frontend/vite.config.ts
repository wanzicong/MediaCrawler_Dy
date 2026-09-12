import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import { tanstackRouter } from "@tanstack/router-plugin/vite"
import react from "@vitejs/plugin-react-swc"
import { defineConfig, loadEnv } from "vite"

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const apiTarget =
    loadEnv(mode, __dirname, "VITE_").VITE_API_URL || "http://localhost:8000"

  return {
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
    },
    server: {
      proxy: {
        "/api": {
          target: apiTarget,
          changeOrigin: true,
        },
      },
    },
    plugins: [
      tanstackRouter({
        target: "react",
        autoCodeSplitting: true,
      }),
      react(),
      tailwindcss(),
    ],
    build: {
      rollupOptions: {
        output: {
          // 把体积大、更新频率低的依赖单独分包：
          // 业务代码发版时这些包的 hash 不变，用户可命中缓存，减小首屏下载量。
          manualChunks: {
            react: ["react", "react-dom"],
            tanstack: [
              "@tanstack/react-query",
              "@tanstack/react-router",
              "@tanstack/react-table",
            ],
            radix: [
              "@radix-ui/react-dialog",
              "@radix-ui/react-dropdown-menu",
              "@radix-ui/react-select",
              "@radix-ui/react-tabs",
              "@radix-ui/react-tooltip",
            ],
          },
        },
      },
    },
  }
})
