"use client"

import {
  Bell,
  Calendar,
  Clock,
  LogOut,
  Menu,
  Network,
  Search,
  User,
} from "lucide-react"
import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"
import { useEffect, type ComponentType } from "react"

import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet"
import { createClient } from "@/lib/supabase/client"
import { buttonVariants } from "@/lib/variants"
import { cn } from "@/lib/utils"
import { useAuthStore } from "@/store/auth.store"
import { useUiStore } from "@/store/ui.store"

import { NotificationBell } from "./NotificationBell"

interface SidebarItem {
  label: string
  href: string
  icon: ComponentType<{ className?: string }>
}

const ORG_NAV: SidebarItem[] = [
  { label: "Tìm kiếm", href: "/search", icon: Search },
  { label: "Đồ thị", href: "/graph", icon: Network },
  { label: "Lịch hẹn", href: "/schedule", icon: Calendar },
  { label: "Thông báo", href: "/notifications", icon: Bell },
]

const PERSONNEL_NAV: SidebarItem[] = [
  { label: "Hồ sơ", href: "/profile", icon: User },
  { label: "Lịch rảnh", href: "/availability", icon: Clock },
  { label: "Lịch hẹn", href: "/schedule", icon: Calendar },
  { label: "Thông báo", href: "/notifications", icon: Bell },
]

function navActive(pathname: string, href: string): boolean {
  if (pathname === href) return true
  if (href === "/") return false
  return pathname.startsWith(`${href}/`)
}

function SidebarNav({
  onNavigate,
  className,
}: {
  onNavigate?: () => void
  className?: string
}) {
  const pathname = usePathname()
  const role = useAuthStore((s) => s.role)
  const items =
    role === "organization"
      ? ORG_NAV
      : role === "personnel"
        ? PERSONNEL_NAV
        : []

  return (
    <nav className={cn("flex flex-col gap-1.5 p-3", className)}>
      {items.map(({ label, href, icon: Icon }) => {
        const active = navActive(pathname, href)
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            className={cn(
              buttonVariants({ variant: "ghost", size: "default" }),
              "h-10 w-full justify-start gap-2.5 px-3.5 text-muted-foreground hover:text-foreground",
              active &&
                "border border-primary/20 bg-primary/12 text-primary shadow-sm hover:bg-primary/15",
            )}
          >
            <Icon className="size-4 shrink-0" aria-hidden />
            <span>{label}</span>
          </Link>
        )
      })}
    </nav>
  )
}

function UserSection() {
  const router = useRouter()
  const user = useAuthStore((s) => s.user)
  const role = useAuthStore((s) => s.role)
  const clear = useAuthStore((s) => s.clear)

  const fullName =
    typeof user?.user_metadata?.full_name === "string"
      ? user.user_metadata.full_name
      : user?.email ?? "Tài khoản"

  const initials = fullName
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("") || "?"

  const roleLabel =
    role === "organization"
      ? "Nhà tuyển dụng"
      : role === "personnel"
        ? "Ứng viên"
        : ""

  async function handleLogout() {
    const supabase = createClient()
    await supabase.auth.signOut()
    clear()
    router.push("/login")
    router.refresh()
  }

  return (
    <div className="border-t border-sidebar-border/80 p-4">
      <div className="mb-4 flex items-center gap-3">
        <Avatar className="size-9">
          <AvatarFallback className="bg-primary/15 text-xs text-primary">{initials}</AvatarFallback>
        </Avatar>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">{fullName}</p>
          {roleLabel ? (
            <p className="text-muted-foreground truncate text-xs">{roleLabel}</p>
          ) : null}
        </div>
      </div>
      <button
        type="button"
        onClick={() => void handleLogout()}
        className={cn(
          buttonVariants({ variant: "outline", size: "default" }),
          "w-full gap-2",
        )}
      >
        <LogOut className="size-4" aria-hidden />
        Đăng xuất
      </button>
    </div>
  )
}

function SidebarChrome({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <div className="flex h-full flex-col bg-sidebar/95">
      <div className="flex items-center justify-between gap-2 border-b border-sidebar-border/80 bg-linear-to-r from-primary/10 via-transparent to-transparent px-4 py-3.5">
        <span className="truncate text-sm font-bold tracking-tight">
          ORCHGRAPH-RAG
        </span>
        <NotificationBell />
      </div>
      <div className="flex-1 overflow-y-auto">
        <SidebarNav onNavigate={onNavigate} />
      </div>
      <UserSection />
    </div>
  )
}

export default function AppSidebar() {
  const setUser = useAuthStore((s) => s.setUser)
  const sidebarOpen = useUiStore((s) => s.sidebarOpen)
  const setSidebarOpen = useUiStore((s) => s.setSidebarOpen)

  useEffect(() => {
    const supabase = createClient()
    void supabase.auth.getSession().then(({ data: { session } }) => {
      if (session?.user) setUser(session.user)
    })
  }, [setUser])

  return (
    <>
      <header className="fixed top-0 right-0 left-0 z-40 flex h-14 items-center justify-between gap-2 border-b border-border/70 bg-background/90 px-3 backdrop-blur-sm md:hidden">
        <Sheet open={sidebarOpen} onOpenChange={setSidebarOpen}>
          <SheetTrigger
            type="button"
            className={cn(
              buttonVariants({ variant: "ghost", size: "icon" }),
              "shrink-0",
            )}
            aria-label="Mở menu"
          >
            <Menu className="size-5" />
          </SheetTrigger>
          <SheetContent side="left" className="w-[min(100%,300px)] p-0">
            <SheetHeader className="sr-only">
              <SheetTitle>Menu điều hướng</SheetTitle>
            </SheetHeader>
            <SidebarChrome
              onNavigate={() => {
                setSidebarOpen(false)
              }}
            />
          </SheetContent>
        </Sheet>
        <div className="flex flex-1 items-center justify-end gap-2">
          <NotificationBell />
        </div>
      </header>

      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col border-r border-sidebar-border/80 bg-sidebar/90 transition-[width,transform] duration-300 ease-in-out md:flex">
        <SidebarChrome />
      </aside>
    </>
  )
}
