import Link from "next/link"

import { LoginForm } from "@/components/auth/LoginForm"

export default function LoginPage() {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold tracking-tight">Đăng nhập</h1>
        <p className="text-muted-foreground text-sm">
          Tài khoản orchgraph-rag
        </p>
      </div>
      <LoginForm />
      <p className="text-muted-foreground text-center text-sm">
        Chưa có tài khoản?{" "}
        <Link
          href="/register"
          className="text-primary text-sm underline-offset-4 hover:underline"
        >
          Đăng ký
        </Link>
      </p>
    </div>
  )
}
