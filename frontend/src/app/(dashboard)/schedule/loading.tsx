import { Skeleton } from "@/components/ui/skeleton"

export default function ScheduleLoading() {
  return (
    <div className="mx-auto max-w-4xl space-y-6 px-4 py-8">
      <Skeleton className="h-7 w-36" />
      {/* Table header */}
      <div className="overflow-hidden rounded-2xl border border-border/70">
        <div className="grid grid-cols-4 gap-4 border-b border-border/70 bg-muted/30 p-4">
          {["Ứng viên", "Thời gian", "Trạng thái", "Thao tác"].map(col => (
            <Skeleton key={col} className="h-4 w-20" />
          ))}
        </div>
        {/* Table rows */}
        {[1, 2, 3, 4, 5].map(i => (
          <div key={i} className="grid grid-cols-4 gap-4 border-b border-border/70 p-4 last:border-0">
            <div className="flex items-center gap-2">
              <Skeleton className="h-8 w-8 rounded-full" />
              <Skeleton className="h-4 w-24" />
            </div>
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-6 w-24 rounded-full" />
            <Skeleton className="h-8 w-20 rounded-xl" />
          </div>
        ))}
      </div>
    </div>
  )
}