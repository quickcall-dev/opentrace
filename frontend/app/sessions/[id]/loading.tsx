import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* Filter toolbar skeleton */}
      <div className="bg-card border-b border-border flex-shrink-0 px-3 py-1.5 flex items-center gap-2">
        <Skeleton className="h-7 w-24" />
        <Skeleton className="h-7 w-20" />
        <Skeleton className="h-7 w-28" />
        <Skeleton className="h-7 w-14" />
        <Skeleton className="h-4 w-20 ml-auto" />
      </div>

      <div className="flex flex-1 min-h-0">
        {/* Sidebar skeleton */}
        <div className="w-80 border-r border-border flex-shrink-0 flex flex-col">
          {/* Gantt area */}
          <div className="h-48 border-b border-border p-3 space-y-2">
            <div className="flex items-center justify-between">
              <Skeleton className="h-3 w-20" />
              <Skeleton className="h-5 w-14" />
            </div>
            <Skeleton className="h-28 w-full" />
          </div>
          {/* Session list */}
          <div className="flex-1 overflow-hidden p-2 space-y-2">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="p-2 rounded-lg border border-border space-y-1.5">
                <div className="flex items-center gap-2">
                  <Skeleton className="h-4 w-16" />
                  <Skeleton className="h-3 w-10" />
                </div>
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-3 w-24" />
              </div>
            ))}
          </div>
        </div>

        {/* Message panel skeleton */}
        <div className="flex-1 flex flex-col min-w-0 bg-muted">
          {/* Header bar */}
          <div className="flex-shrink-0 border-b border-border bg-card px-4 py-3 space-y-2">
            <div className="flex items-center gap-2">
              <Skeleton className="h-4 w-4" />
              <Skeleton className="h-4 w-48" />
            </div>
            <div className="flex items-center gap-2">
              <Skeleton className="h-3 w-14" />
              <Skeleton className="h-3 w-20" />
              <Skeleton className="h-3 w-24" />
              <Skeleton className="h-3 w-16" />
            </div>
          </div>

          {/* Jump bar */}
          <div className="flex-shrink-0 px-4 py-1.5 border-b border-border bg-muted flex items-center justify-between">
            <Skeleton className="h-3 w-24" />
            <div className="flex gap-1">
              <Skeleton className="h-6 w-6" />
              <Skeleton className="h-6 w-6" />
            </div>
          </div>

          {/* Messages */}
          <div className="flex flex-1 min-h-0">
            <div className="flex-1 overflow-hidden p-2 space-y-2">
              {Array.from({ length: 12 }).map((_, i) => (
                <div key={i} className="border-l-[3px] border-border rounded-r-lg px-3 py-2 space-y-1.5">
                  <div className="flex items-center gap-2">
                    <Skeleton className="h-3 w-4" />
                    <Skeleton className="h-3 w-12" />
                    <Skeleton className="h-3 w-16" />
                  </div>
                  <Skeleton className="h-3 w-full" />
                  <Skeleton className="h-3 w-3/4" />
                </div>
              ))}
            </div>

            {/* Minimap */}
            <div className="w-12 border-l border-border flex-shrink-0 py-2">
              <Skeleton className="h-full w-full" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
