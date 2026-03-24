import type { ReactNode } from "react"

import AppSidebar from "@/components/shared/AppSidebar"

export default function DashboardLayout({ children }: { children: ReactNode }) {
  return (
    <div className="bg-muted/10 min-h-screen">
      <AppSidebar />
      <main className="min-h-screen pt-14 md:pt-0 md:pl-60">
        <div className="p-6">{children}</div>
      </main>
    </div>
  )
}
