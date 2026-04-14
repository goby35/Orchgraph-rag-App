import { Skeleton } from "@/components/ui/skeleton"

export default function ProfileLoading() {
  return (
    <div className="mx-auto max-w-3xl space-y-6 px-4 py-8">
      <Skeleton className="h-7 w-44" />
      {/* Basic info */}
      <div className="flex items-center gap-5 rounded-2xl border border-border/70 p-6">
        <Skeleton className="h-16 w-16 rounded-full shrink-0" />
        <div className="space-y-2 flex-1">
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-4 w-56" />
          <Skeleton className="h-5 w-20 rounded-full" />
        </div>
      </div>
      {/* Upload section */}
      <div className="space-y-3 rounded-2xl border border-border/70 p-6">
        <Skeleton className="h-5 w-32" />
        <Skeleton className="h-3 w-3/4" />
        <Skeleton className="h-24 w-full rounded-xl" />
      </div>
      {/* Skills section */}
      <div className="space-y-3 rounded-2xl border border-border/70 p-6">
        <Skeleton className="h-5 w-40" />
        <div className="flex flex-wrap gap-1.5">
          {[1, 2, 3, 4, 5].map(i => (
            <Skeleton key={i} className="h-6 w-20 rounded-full" />
          ))}
        </div>
      </div>
    </div>
  )
}