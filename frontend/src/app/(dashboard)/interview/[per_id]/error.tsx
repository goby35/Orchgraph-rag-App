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
      <div className="text-center space-y-4">
        <div className="h-12 w-12 rounded-full bg-destructive/10 flex items-center justify-center mx-auto">
          <span className="text-destructive text-xl">!</span>
        </div>
        <div className="space-y-1">
          <p className="font-semibold">Không thể tải trang phỏng vấn</p>
          <p className="text-sm text-muted-foreground">{error.message}</p>
        </div>
        <button
          onClick={reset}
          className="text-sm px-4 py-2 border rounded-md hover:bg-muted transition-colors"
        >
          Thử lại
        </button>
      </div>
    </div>
  )
}