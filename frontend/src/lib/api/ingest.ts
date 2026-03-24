import { apiClient } from "./client"

// export const uploadFile = async (file: File): Promise<IngestUploadResult> => {
//   const form = new FormData()
//   form.append("file", file)
//   const res = await apiClient.post<IngestUploadResult>("/ingest", form)
//   return res.data
// }

// export const getIngestStatus = (jobId: string): Promise<IngestJob> =>
//   apiClient
//     .get<IngestJob>(`/ingest/status/${encodeURIComponent(jobId)}`)
//     .then((r) => r.data)

export interface IngestUploadResponse {
  status:   string    // "ok"
  filename: string
  neo4j_id: string    // dùng cái này làm jobId
}

export const uploadFile = async (file: File): Promise<IngestUploadResponse> => {
  const form = new FormData()
  form.append('file', file)
  const res = await apiClient.post<IngestUploadResponse>('/ingest', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return res.data
}