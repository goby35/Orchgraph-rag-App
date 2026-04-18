import Link from "next/link"

const linkPrimary =
  "inline-flex h-9 min-w-[140px] shrink-0 items-center justify-center gap-1.5 rounded-lg border border-transparent bg-primary px-2.5 text-sm font-medium whitespace-nowrap text-primary-foreground transition-all outline-none select-none hover:bg-primary/80 focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 active:translate-y-px"

const linkOutline =
  "inline-flex h-9 min-w-[140px] shrink-0 items-center justify-center gap-1.5 rounded-lg border border-border bg-background px-2.5 text-sm font-medium whitespace-nowrap transition-all outline-none select-none hover:bg-muted hover:text-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 active:translate-y-px dark:border-input dark:bg-input/30 dark:hover:bg-input/50"

export default function HomePage() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-8 px-4 py-16">
      <div className="max-w-lg text-center">
        <h1 className="text-3xl font-semibold tracking-tight">
          Orchgraph-rag
        </h1>
        <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
          Đăng nhập để tiếp tục, hoặc tạo tài khoản mới.
        </p>
      </div>
      <div className="flex flex-col gap-3 sm:flex-row">
        <Link href="/login" className={linkPrimary}>
          Đăng nhập
        </Link>
        <Link href="/register" className={linkOutline}>
          Đăng ký
        </Link>
      </div>
    </div>
  )
}
