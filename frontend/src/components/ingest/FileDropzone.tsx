"use client"
import { useCallback, useState, useRef, useEffect } from 'react'
import { useDropzone }           from 'react-dropzone'
import { toast }                 from 'sonner'
import { useQueryClient }        from '@tanstack/react-query'
import { uploadFile }            from '@/lib/api/ingest'
import IngestStatusBadge         from './IngestStatusBadge'
import { cn }                    from '@/lib/utils'

// Chỉ dùng cho Personnel — upload CV/hồ sơ
// Accept: PDF, DOCX, TXT, JSON

type UploadState = 'idle' | 'uploading' | 'done' | 'failed'

export default function FileDropzone() {
  const [uploadState, setUploadState] = useState<UploadState>('idle')
  const [fileName,    setFileName]    = useState<string | null>(null)
  const queryClient = useQueryClient()

  const onDrop = useCallback(async (acceptedFiles: File[]) => {
    const file = acceptedFiles[0]
    if (!file) return

    setUploadState('uploading')
    setFileName(file.name)

    try {
      const res = await uploadFile(file)

      if (res.status === 'ok') {
        setUploadState('done')
        toast.success('Hồ sơ đã được xử lý thành công!')
        queryClient.invalidateQueries({ queryKey: ['graph'] })
      } else {
        setUploadState('failed')
        toast.error('Xử lý thất bại. Vui lòng thử lại.')
      }
    } catch {
      setUploadState('failed')
      toast.error('Upload thất bại. Kiểm tra kết nối và thử lại.')
    }
  }, [])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/pdf': ['.pdf'],
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
      'text/plain':       ['.txt'],
      'application/json': ['.json'],
    },
    maxFiles: 1,
    disabled: uploadState === 'uploading',
  })

  const handleRetry = () => {
    setUploadState('idle')
    setFileName(null)
  }

  return (
    <div className="space-y-3">
      <div
        {...getRootProps()}
        className={cn(
          "border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors",
          isDragActive
            ? "border-primary bg-primary/5"
            : "border-muted-foreground/25 hover:border-primary/50",
          uploadState === 'uploading' && "opacity-50 cursor-not-allowed",
        )}
      >
        <input {...getInputProps()} />
        <p className="text-sm text-muted-foreground">
          {isDragActive
            ? "Thả file vào đây..."
            : "Kéo thả file CV hoặc click để chọn"}
        </p>
        <p className="text-xs text-muted-foreground mt-1">
          Hỗ trợ: PDF, DOCX, TXT, JSON
        </p>
      </div>

      {/* Status row */}
      {fileName && (
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm text-muted-foreground truncate max-w-[200px]">
            {fileName}
          </span>

          {uploadState === 'uploading' && (
            <span className="inline-flex items-center gap-1.5 text-xs text-amber-700 bg-amber-100 rounded-full px-3 py-1">
              <span className="h-3 w-3 rounded-full border-2 border-amber-400 border-t-transparent animate-spin" />
              Đang upload...
            </span>
          )}

          {uploadState === 'done' && (
            <span className="inline-flex items-center gap-1.5 text-xs text-green-700 bg-green-100 rounded-full px-3 py-1">
              ✓ Hoàn thành
            </span>
          )}

          {uploadState === 'failed' && (
            <span className="inline-flex items-center gap-1.5 text-xs text-red-700 bg-red-100 rounded-full px-3 py-1">
              ✕ Lỗi —
              <button onClick={handleRetry} className="underline hover:no-underline">
                Thử lại
              </button>
            </span>
          )}
        </div>
      )}
    </div>
  )
}