import { ReactQueryDevtools } from "@tanstack/react-query-devtools"
import { createRootRoute, HeadContent, Outlet } from "@tanstack/react-router"
import { TanStackRouterDevtools } from "@tanstack/react-router-devtools"
import ErrorComponent from "@/components/Common/ErrorComponent"
import NotFound from "@/components/Common/NotFound"

const showDevtools =
  import.meta.env.DEV && import.meta.env.VITE_ENABLE_DEVTOOLS === "true"

export const Route = createRootRoute({
  component: () => (
    <>
      <HeadContent />
      <Outlet />
      {showDevtools && (
        <>
          <TanStackRouterDevtools position="bottom-right" />
          <ReactQueryDevtools
            buttonPosition="top-right"
            initialIsOpen={false}
          />
        </>
      )}
    </>
  ),
  notFoundComponent: () => <NotFound />,
  errorComponent: () => <ErrorComponent />,
})
