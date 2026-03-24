import { AlertTriangle } from "lucide-react"

import { buttonVariants } from "@/lib/variants"
import { cn } from "@/lib/utils"

interface ErrorStateProps {
  title?: string
  message?: string
  onRetry?: () => void
}

export function ErrorState({
  title = "Đã xảy ra lỗi",
  message,
  onRetry,
}: ErrorStateProps) {
  return (
    <div
      data-slot="error-state"
      className="flex min-h-[200px] flex-col items-center justify-center gap-4 rounded-lg border border-destructive/30 bg-destructive/5 px-6 py-10 text-center"
    >
      <AlertTriangle
        className="text-destructive size-10 shrink-0"
        aria-hidden
      />
      <div className="space-y-1">
        <h2 className="text-sm font-semibold">{title}</h2>
        {message ? (
          <p className="text-muted-foreground max-w-md text-sm">{message}</p>
        ) : null}
      </div>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className={cn(buttonVariants({ variant: "default", size: "default" }))}
        >
          Thử lại
        </button>
      ) : null}
    </div>
  )
}
