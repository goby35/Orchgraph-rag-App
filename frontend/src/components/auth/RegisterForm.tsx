"use client"

import { useRouter } from "next/navigation"
import { useState, type FormEvent } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { createClient } from "@/lib/supabase/client"
import { useAuthStore } from "@/store/auth.store"
import { cn } from "@/lib/utils"

type RoleChoice = "organization" | "personnel"

export function RegisterForm() {
  const router = useRouter()
  const setUser = useAuthStore((s) => s.setUser)
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [fullName, setFullName] = useState("")
  const [role, setRole] = useState<RoleChoice>("personnel")
  const [loading, setLoading] = useState(false)

  function formatRegisterError(payload: unknown): string {
    if (typeof payload !== "object" || payload === null || !("detail" in payload))
      return "Đăng ký thất bại"
    const detail = (payload as { detail: unknown }).detail
    if (typeof detail === "string") return detail
    try {
      return JSON.stringify(detail)
    } catch {
      return "Đăng ký thất bại"
    }
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setLoading(true)
    const base = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? ""
    const res = await fetch(`${base}/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email,
        password,
        full_name: fullName,
        role,
      }),
    })
    const payload: unknown = await res.json().catch(() => ({}))
    if (!res.ok) {
      setLoading(false)
      toast.error(formatRegisterError(payload))
      return
    }

    const supabase = createClient()
    const { data, error } = await supabase.auth.signInWithPassword({
      email,
      password,
    })
    setLoading(false)
    if (error) {
      toast.error(error.message)
      return
    }
    if (data.user) {
      setUser(data.user)
      if (role === "organization") router.replace("/search")
      else router.replace("/profile")
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex w-full max-w-sm flex-col gap-4">
      <div className="flex flex-col gap-2">
        <Label htmlFor="fullName">Họ và tên</Label>
        <Input
          id="fullName"
          autoComplete="name"
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
          required
        />
      </div>
      <div className="flex flex-col gap-2">
        <Label htmlFor="email">Email</Label>
        <Input
          id="email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
      </div>
      <div className="flex flex-col gap-2">
        <Label htmlFor="password">Mật khẩu (tối thiểu 8 ký tự)</Label>
        <Input
          id="password"
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          minLength={8}
        />
      </div>
      <div className="flex flex-col gap-2">
        <span className="text-sm font-medium">Vai trò</span>
        <div className="flex flex-col gap-2 sm:flex-row">
          <button
            type="button"
            onClick={() => setRole("organization")}
            className={cn(
              "rounded-lg border px-3 py-2 text-left text-sm transition-colors",
              role === "organization"
                ? "border-primary bg-primary/10"
                : "border-border hover:bg-muted",
            )}
          >
            Nhà tuyển dụng
          </button>
          <button
            type="button"
            onClick={() => setRole("personnel")}
            className={cn(
              "rounded-lg border px-3 py-2 text-left text-sm transition-colors",
              role === "personnel"
                ? "border-primary bg-primary/10"
                : "border-border hover:bg-muted",
            )}
          >
            Ứng viên
          </button>
        </div>
      </div>
      <Button type="submit" disabled={loading} className="w-full">
        {loading ? "Đang tạo tài khoản…" : "Đăng ký"}
      </Button>
    </form>
  )
}
