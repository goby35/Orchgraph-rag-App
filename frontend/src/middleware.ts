import { createServerClient } from "@supabase/ssr"
import { type NextRequest, NextResponse } from "next/server"

type AppRole = "organization" | "personnel"

function roleFromUser(user: {
  user_metadata?: Record<string, unknown>
} | null): AppRole | null {
  const raw = user?.user_metadata?.role
  if (typeof raw !== "string") return null
  const u = raw.toUpperCase()
  if (u === "ORGANIZATION") return "organization"
  if (u === "PERSONNEL") return "personnel"
  return null
}

function isOrgOnlyPath(path: string): boolean {
  if (path === "/search" || path.startsWith("/search/")) return true
  if (path === "/graph" || path.startsWith("/graph/")) return true
  if (path === "/interview" || path.startsWith("/interview/")) return true
  return false
}

function isPersonnelOnlyPath(path: string): boolean {
  if (path === "/profile" || path.startsWith("/profile/")) return true
  if (path === "/availability" || path.startsWith("/availability/")) return true
  return false
}

function homeForRole(role: AppRole): string {
  return role === "organization" ? "/search" : "/profile"
}

export async function middleware(request: NextRequest) {
  let supabaseResponse = NextResponse.next({ request })

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll()
        },
        setAll(cookiesToSet) {
          cookiesToSet.forEach(({ name, value }) =>
            request.cookies.set(name, value),
          )
          supabaseResponse = NextResponse.next({ request })
          cookiesToSet.forEach(({ name, value, options }) =>
            supabaseResponse.cookies.set(name, value, options),
          )
        },
      },
    },
  )

  const {
    data: { user },
  } = await supabase.auth.getUser()

  const path = request.nextUrl.pathname
  const role = roleFromUser(user)

  if (user && (path === "/login" || path === "/register")) {
    return NextResponse.redirect(
      new URL(role ? homeForRole(role) : "/search", request.url),
    )
  }

  if (user && path === "/") {
    return NextResponse.redirect(
      new URL(role ? homeForRole(role) : "/search", request.url),
    )
  }

  const isProtected =
    path.startsWith("/search") ||
    path.startsWith("/graph") ||
    path.startsWith("/interview") ||
    path.startsWith("/schedule") ||
    path.startsWith("/notifications") ||
    path.startsWith("/profile") ||
    path.startsWith("/availability")

  if (!user && isProtected) {
    return NextResponse.redirect(new URL("/login", request.url))
  }

  if (user && role) {
    if (role === "organization" && isPersonnelOnlyPath(path)) {
      return NextResponse.redirect(new URL("/search", request.url))
    }
    if (role === "personnel" && isOrgOnlyPath(path)) {
      return NextResponse.redirect(new URL("/profile", request.url))
    }
  }

  return supabaseResponse
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
}
