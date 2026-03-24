import { Skeleton } from "@/components/ui/skeleton"

export default function InterviewLoading() {
  return (
    <div className="flex h-[calc(100vh-4rem)] gap-0">
      {/* Profile panel */}
      <div className="w-80 border-r p-6 space-y-5 hidden md:block">
        <div className="flex items-center gap-3">
          <Skeleton className="h-14 w-14 rounded-full" />
          <div className="space-y-2 flex-1">
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-3 w-1/2" />
          </div>
        </div>
        <div className="space-y-2">
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-5/6" />
          <Skeleton className="h-3 w-4/6" />
        </div>
        <div className="flex flex-wrap gap-1.5">
          {[1, 2, 3, 4].map(i => (
            <Skeleton key={i} className="h-5 w-16 rounded-full" />
          ))}
        </div>
      </div>

      {/* Chat panel */}
      <div className="flex-1 flex flex-col p-4 space-y-4">
        {/* Messages */}
        <div className="flex-1 space-y-4 overflow-hidden">
          {/* Assistant bubble */}
          <div className="flex items-start gap-2 max-w-[70%]">
            <Skeleton className="h-8 w-8 rounded-full shrink-0" />
            <Skeleton className="h-16 flex-1 rounded-2xl rounded-tl-none" />
          </div>
          {/* User bubble */}
          <div className="flex items-start gap-2 max-w-[70%] ml-auto flex-row-reverse">
            <Skeleton className="h-8 w-8 rounded-full shrink-0" />
            <Skeleton className="h-10 w-48 rounded-2xl rounded-tr-none" />
          </div>
          {/* Assistant bubble */}
          <div className="flex items-start gap-2 max-w-[80%]">
            <Skeleton className="h-8 w-8 rounded-full shrink-0" />
            <Skeleton className="h-24 flex-1 rounded-2xl rounded-tl-none" />
          </div>
        </div>
        {/* Input */}
        <Skeleton className="h-12 w-full rounded-lg" />
      </div>
    </div>
  )
}