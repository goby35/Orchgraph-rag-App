import Link from "next/link"

import { RegisterForm } from "@/components/auth/RegisterForm"

export default function RegisterPage() {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold tracking-tight">Đăng ký</h1>
        <p className="text-muted-foreground text-sm">
          Tạo tài khoản nhà tuyển dụng hoặc ứng viên
        </p>
      </div>
      <RegisterForm />
      <p className="text-muted-foreground text-center text-sm">
        Đã có tài khoản?{" "}
        <Link
          href="/login"
          className="text-primary text-sm underline-offset-4 hover:underline"
        >
          Đăng nhập
        </Link>
      </p>
    </div>
  )
}
