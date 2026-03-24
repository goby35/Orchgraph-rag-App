// src/components/ingest/IngestStatusBadge.tsx
// Không cần "use client" — pure display

import { cn } from '@/lib/utils'

interface IngestStatusBadgeProps {
  status:   'processing' | 'done' | 'failed'
  onRetry?: () => void
}

export default function IngestStatusBadge({ status, onRetry }: IngestStatusBadgeProps) {
  return (
    <div className={cn(
      "inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium",
      status === 'processing' && "bg-amber-100 text-amber-800",
      status === 'done'       && "bg-green-100 text-green-800",
      status === 'failed'     && "bg-red-100 text-red-800",
    )}>
      {status === 'processing' && (
        <>
          {/* Spinner */}
          <span className="h-3 w-3 rounded-full border-2 border-amber-400 border-t-transparent animate-spin" />
          Đang xử lý...
        </>
      )}
      {status === 'done' && (
        <>
          <span>✓</span>
          Hoàn thành
        </>
      )}
      {status === 'failed' && (
        <>
          <span>✕</span>
          Lỗi xử lý
          {onRetry && (
            <button
              onClick={onRetry}
              className="ml-1 underline hover:no-underline"
            >
              Thử lại
            </button>
          )}
        </>
      )}
    </div>
  )
}