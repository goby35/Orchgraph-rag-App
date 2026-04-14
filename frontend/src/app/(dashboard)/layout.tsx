import type { ReactNode } from "react"

import AppSidebar from "@/components/shared/AppSidebar"

export default function DashboardLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-transparent">
      <AppSidebar />
      <main className="min-h-screen pt-14 transition-[padding] duration-300 ease-in-out md:pt-0 md:pl-64">
        <div className="p-5 sm:p-6 lg:p-8">{children}</div>
      </main>
    </div>
  )
}
