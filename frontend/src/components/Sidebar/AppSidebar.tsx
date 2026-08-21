import { Logo } from "@/components/Common/Logo"
import { getNavigationModules } from "@/components/Navigation/navigation"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
} from "@/components/ui/sidebar"
import useAuth from "@/hooks/useAuth"
import { Main, type NavGroup } from "./Main"
import { User } from "./User"

export function AppSidebar() {
  const { user: currentUser } = useAuth()

  const groups: NavGroup[] = getNavigationModules(
    Boolean(currentUser?.is_superuser),
  )

  return (
    <Sidebar collapsible="icon" className="border-r-0">
      <SidebarHeader className="px-4 pt-5 pb-3 group-data-[collapsible=icon]:items-center group-data-[collapsible=icon]:px-0">
        <Logo variant="responsive" />
      </SidebarHeader>
      <SidebarContent className="px-2">
        <Main groups={groups} />
      </SidebarContent>
      <SidebarFooter className="border-t border-sidebar-border/60 p-2">
        <User user={currentUser} />
      </SidebarFooter>
    </Sidebar>
  )
}

export default AppSidebar
