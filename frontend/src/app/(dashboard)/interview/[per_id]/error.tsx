"use client"

export default function InterviewError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  return (
    <div className="flex h-[calc(100vh-4rem)] items-center justify-center">
      <div className="space-y-4 rounded-2xl border border-destructive/25 bg-destructive/5 px-8 py-10 text-center">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-destructive/12">
          <span className="text-destructive text-xl">!</span>
        </div>
        <div className="space-y-1">
          <p className="font-semibold tracking-tight">Không thể tải trang phỏng vấn</p>
          <p className="text-sm text-muted-foreground">{error.message}</p>
        </div>
        <button
          onClick={reset}
          className="rounded-xl border border-border/80 px-4 py-2 text-sm font-medium transition-all duration-200 hover:scale-[1.02] hover:bg-muted/60 active:scale-[0.98]"
        >
          Thử lại
        </button>
      </div>
    </div>
  )
}