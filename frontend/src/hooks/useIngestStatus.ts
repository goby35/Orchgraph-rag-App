// // src/hooks/useIngestStatus.ts
// "use client"
// import { useQuery } from '@tanstack/react-query'
// import { getIngestStatus, type IngestStatusResponse } from '@/lib/api/ingest'

// export function useIngestStatus(jobId: string | null) {
//   return useQuery<IngestStatusResponse>({
//     queryKey: ['ingest', jobId],
//     queryFn:  () => getIngestStatus(jobId!),
//     enabled:  !!jobId,
//     // Poll mỗi 3s — dừng khi done hoặc failed
//     refetchInterval: (query) => {
//       const status = query.state.data?.status
//       return status === 'done' || status === 'failed' ? false : 3_000
//     },
//     // Không retry khi failed — tránh spam
//     retry: (failureCount, error: unknown) => {
//       const status = (error as { response?: { status?: number } })?.response?.status
//       return status !== 404 && failureCount < 2
//     },
//   })
// }