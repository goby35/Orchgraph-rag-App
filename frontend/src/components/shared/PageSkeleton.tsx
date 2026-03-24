import { Skeleton } from "@/components/ui/skeleton"

interface PageSkeletonProps {
  variant: "card-list" | "graph" | "chat" | "form" | "table"
}

const cardRow = "space-y-2 rounded-lg border p-4"
const line = "h-4 w-full rounded-md"
const shortLine = "h-4 w-2/3 rounded-md"

function CardListSkeleton() {
  return (
    <div className="flex flex-col gap-4">
      {[0, 1, 2].map((i) => (
        <div key={i} className={cardRow}>
          <Skeleton className="h-5 w-1/3" />
          <Skeleton className={line} />
          <Skeleton className={line} />
          <Skeleton className={shortLine} />
          <Skeleton className="mt-4 h-8 w-24 rounded-md" />
        </div>
      ))}
    </div>
  )
}

function GraphSkeleton() {
  return (
    <div className="relative flex h-[min(70vh,420px)] items-center justify-center">
      <div className="flex items-center gap-6">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="size-14 shrink-0 rounded-full" />
        ))}
      </div>
      <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
        <div className="border-muted-foreground/30 h-px w-32 rotate-12 border-t-2 border-dashed" />
        <div className="border-muted-foreground/30 absolute h-px w-32 -rotate-12 border-t-2 border-dashed" />
      </div>
    </div>
  )
}

function ChatSkeleton() {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex justify-end">
        <Skeleton className="h-10 w-[72%] max-w-md rounded-2xl rounded-br-sm" />
      </div>
      <div className="flex justify-start">
        <Skeleton className="h-16 w-[85%] max-w-lg rounded-2xl rounded-bl-sm" />
      </div>
      <div className="flex justify-end">
        <Skeleton className="h-8 w-[40%] max-w-xs rounded-2xl rounded-br-sm" />
      </div>
    </div>
  )
}

function FormSkeleton() {
  return (
    <div className="flex max-w-md flex-col gap-4">
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="space-y-2">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-10 w-full rounded-md" />
        </div>
      ))}
    </div>
  )
}

function TableSkeleton() {
  return (
    <div className="flex flex-col gap-2">
      <div className="grid grid-cols-4 gap-2 border-b pb-2">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-5 w-full" />
        ))}
      </div>
      {[0, 1, 2, 3, 4].map((row) => (
        <div key={row} className="grid grid-cols-4 gap-2">
          {[0, 1, 2, 3].map((col) => (
            <Skeleton key={col} className="h-4 w-full" />
          ))}
        </div>
      ))}
    </div>
  )
}

export function PageSkeleton({ variant }: PageSkeletonProps) {
  return (
    <div
      data-slot="page-skeleton"
      className="w-full"
      aria-busy
      aria-label="Đang tải"
    >
      {variant === "card-list" && <CardListSkeleton />}
      {variant === "graph" && <GraphSkeleton />}
      {variant === "chat" && <ChatSkeleton />}
      {variant === "form" && <FormSkeleton />}
      {variant === "table" && <TableSkeleton />}
    </div>
  )
}
