"use client"

import { Loader2 } from "lucide-react"
import { useState, type FormEvent } from "react"

import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"

interface SearchBarProps {
  onSearch: (query: string) => void
  loading: boolean
}

export function SearchBar({ onSearch, loading }: SearchBarProps) {
  const [text, setText] = useState("")

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const q = text.trim()
    if (!q || loading) return
    onSearch(q)
  }

  return (
    <form onSubmit={handleSubmit} className="flex w-full max-w-4xl flex-col gap-3">
      <Textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Dán mô tả công việc (JD) vào đây..."
        disabled={loading}
        rows={8}
        className="min-h-[180px] resize-y"
        aria-label="Mô tả công việc"
      />
      <div className="flex justify-end">
        <Button type="submit" disabled={loading || !text.trim()}>
          {loading ? (
            <>
              <Loader2 className="size-4 animate-spin" aria-hidden />
              Đang tìm…
            </>
          ) : (
            "Tìm ứng viên"
          )}
        </Button>
      </div>
      <p className="text-muted-foreground text-xs">
        Nhấn &quot;Tìm ứng viên&quot; để gửi. Shift+Enter để xuống dòng.
      </p>
    </form>
  )
}
