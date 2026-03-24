"use client"

export default function GraphError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  return (
    <div className="max-w-6xl mx-auto py-8 px-4">
      <div className="border rounded-lg h-[600px] flex flex-col items-center justify-center space-y-4">
        <div className="h-12 w-12 rounded-full bg-destructive/10 flex items-center justify-center">
          <span className="text-destructive text-xl">!</span>
        </div>
        <div className="text-center space-y-1">
          <p className="font-semibold">Không thể tải đồ thị</p>
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