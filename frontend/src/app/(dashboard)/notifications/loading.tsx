import { Skeleton } from "@/components/ui/skeleton"

export default function NotificationsLoading() {
  return (
    <div className="mx-auto max-w-3xl space-y-6 px-4 py-8">
      <div className="flex items-center justify-between">
        <Skeleton className="h-7 w-32" />
        <Skeleton className="h-8 w-40 rounded-xl" />
      </div>
      {/* Day group */}
      <div className="space-y-2">
        <Skeleton className="h-3 w-28" />
        {[1, 2, 3].map(i => (
          <div key={i} className="flex items-start gap-3 rounded-2xl border border-border/70 px-4 py-3">
            <Skeleton className="h-2 w-2 rounded-full mt-1.5 shrink-0" />
            <div className="flex-1 space-y-1.5">
              <Skeleton className="h-4 w-2/3" />
              <Skeleton className="h-3 w-4/5" />
            </div>
            <Skeleton className="h-3 w-16 shrink-0" />
          </div>
        ))}
      </div>
      {/* Day group 2 */}
      <div className="space-y-2">
        <Skeleton className="h-3 w-20" />
        {[1, 2].map(i => (
          <div key={i} className="flex items-start gap-3 rounded-2xl border border-border/70 px-4 py-3">
            <Skeleton className="h-2 w-2 rounded-full mt-1.5 shrink-0" />
            <div className="flex-1 space-y-1.5">
              <Skeleton className="h-4 w-1/2" />
              <Skeleton className="h-3 w-3/4" />
            </div>
            <Skeleton className="h-3 w-16 shrink-0" />
          </div>
        ))}
      </div>
    </div>
  )
}