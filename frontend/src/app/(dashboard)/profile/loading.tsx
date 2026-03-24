import { Skeleton } from "@/components/ui/skeleton"

export default function ProfileLoading() {
  return (
    <div className="max-w-2xl mx-auto py-8 px-4 space-y-6">
      <Skeleton className="h-7 w-44" />
      {/* Basic info */}
      <div className="border rounded-lg p-6 flex items-center gap-5">
        <Skeleton className="h-16 w-16 rounded-full shrink-0" />
        <div className="space-y-2 flex-1">
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-4 w-56" />
          <Skeleton className="h-5 w-20 rounded-full" />
        </div>
      </div>
      {/* Upload section */}
      <div className="border rounded-lg p-6 space-y-3">
        <Skeleton className="h-5 w-32" />
        <Skeleton className="h-3 w-3/4" />
        <Skeleton className="h-24 w-full rounded-lg" />
      </div>
      {/* Skills section */}
      <div className="border rounded-lg p-6 space-y-3">
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