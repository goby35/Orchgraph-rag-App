"use client"

import { X } from "lucide-react"
import { useMemo, useState, type ClipboardEvent, type KeyboardEvent } from "react"

import { cn } from "@/lib/utils"

interface TagInputProps {
  value: string[]
  onChange: (tags: string[]) => void
  placeholder?: string
  className?: string
}

function normalizeTag(tag: string): string {
  return tag.trim().toLowerCase()
}

function splitTags(raw: string): string[] {
  return raw
    .split(/[,\n]/)
    .map(normalizeTag)
    .filter(Boolean)
}

export function TagInput({ value, onChange, placeholder, className }: TagInputProps) {
  const [inputValue, setInputValue] = useState("")

  const normalizedValue = useMemo(
    () => value.map(normalizeTag).filter(Boolean),
    [value],
  )

  function commitTags(nextTags: string[]) {
    if (nextTags.length === 0) return
    const existing = new Set(normalizedValue)
    const merged = [...normalizedValue]

    for (const tag of nextTags) {
      if (existing.has(tag)) continue
      existing.add(tag)
      merged.push(tag)
    }

    onChange(merged)
  }

  function commitInput() {
    const nextTag = normalizeTag(inputValue)
    if (!nextTag) {
      setInputValue("")
      return
    }

    commitTags([nextTag])
    setInputValue("")
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault()
      commitInput()
      return
    }

    if (e.key === "Backspace" && inputValue.length === 0 && normalizedValue.length > 0) {
      e.preventDefault()
      onChange(normalizedValue.slice(0, -1))
    }
  }

  function handlePaste(e: ClipboardEvent<HTMLInputElement>) {
    const pasted = e.clipboardData.getData("text")
    if (!/[\n,]/.test(pasted)) return

    e.preventDefault()
    commitTags(splitTags(pasted))
  }

  function removeTag(tagToRemove: string) {
    onChange(normalizedValue.filter((tag) => tag !== tagToRemove))
  }

  return (
    <div
      className={cn(
        "flex min-h-11 flex-wrap items-center gap-2 rounded-lg border border-input bg-background px-3 py-2 transition-colors",
        "focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50",
        className,
      )}
    >
      {normalizedValue.map((tag) => (
        <span
          key={tag}
          className="inline-flex items-center gap-1 rounded-full bg-secondary px-2.5 py-1 text-xs font-medium text-secondary-foreground"
        >
          <span>{tag}</span>
          <button
            type="button"
            onClick={() => removeTag(tag)}
            className="rounded-full p-0.5 transition-colors hover:bg-background/80"
            aria-label={`Xoá ${tag}`}
          >
            <X className="size-3" aria-hidden />
          </button>
        </span>
      ))}
      <input
        value={inputValue}
        onChange={(e) => setInputValue(e.target.value)}
        onKeyDown={handleKeyDown}
        onPaste={handlePaste}
        placeholder={placeholder}
        className={cn(
          "min-w-[10rem] flex-1 border-0 bg-transparent p-0 text-sm outline-none placeholder:text-muted-foreground",
          "disabled:cursor-not-allowed disabled:opacity-50",
        )}
      />
    </div>
  )
}