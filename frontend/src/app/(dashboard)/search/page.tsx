"use client"

import { useMutation } from "@tanstack/react-query"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { SearchBar, type SearchFormValues } from "@/components/search/SearchBar"
import { SearchResults } from "@/components/search/SearchResults"
import { createInterviewSession, type ReasoningSummary } from "@/lib/api/chat"
import { mapSearchResponseToCandidates, searchCandidates } from "@/lib/api"
import { cn } from "@/lib/utils"
import { useAuthStore } from "@/store/auth.store"
import type { CandidateResult } from "@/types"

// ── Search history (localStorage) ────────────────────────────────────────────

interface SearchHistoryEntry {
  id:        string
  query:     string
  jobTitle:  string
  timestamp: number
  results:   CandidateResult[]
}

const HISTORY_KEY = "org_search_history"
const MAX_HISTORY = 5

function extractJobTitleFromJd(jdText: string): string {
  const normalized = jdText.replace(/\r/g, "").trim()
  if (!normalized) return ""

  const lines = normalized
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)

  const linePattern = /^(?:v[iị]\s*tr[ií]|position|job\s*title)\s*[:\-]\s*(.+)$/i
  for (const line of lines.slice(0, 8)) {
    const match = line.match(linePattern)
    if (match?.[1]) {
      return match[1].trim().slice(0, 120)
    }
  }

  const inlinePattern = /(?:v[iị]\s*tr[ií]|position|job\s*title)\s*[:\-]\s*([^\n\r]+)/i
  const inlineMatch = normalized.match(inlinePattern)
  if (inlineMatch?.[1]) {
    return inlineMatch[1].trim().slice(0, 120)
  }

  const firstLine = lines[0]?.replace(/^[-*#\s]+/, "") ?? ""
  if (firstLine) {
    return firstLine.slice(0, 120)
  }

  return normalized.length > 50
    ? `${normalized.slice(0, 50).trim()}...`
    : normalized
}

function loadHistory(): SearchHistoryEntry[] {
  try {
    const raw = typeof window !== "undefined" ? localStorage.getItem(HISTORY_KEY) : null
    const parsed = raw ? (JSON.parse(raw) as Partial<SearchHistoryEntry>[]) : []
    return parsed
      .filter((entry): entry is SearchHistoryEntry => Boolean(entry?.id && entry.query && entry.timestamp && entry.results))
      .map((entry) => ({
        ...entry,
        jobTitle: entry.jobTitle?.trim() ? entry.jobTitle : extractJobTitleFromJd(entry.query),
      }))
  } catch {
    return []
  }
}

function saveHistory(entry: SearchHistoryEntry): void {
  try {
    const prev = loadHistory().filter(e => e.query !== entry.query)
    localStorage.setItem(HISTORY_KEY, JSON.stringify([entry, ...prev].slice(0, MAX_HISTORY)))
  } catch { /* noop */ }
}

// ── RecentSearchHistory component ─────────────────────────────────────────────

function RecentSearchHistory({ history }: { history: SearchHistoryEntry[] }) {
  const [open, setOpen]         = useState(false)
  const [expanded, setExpanded] = useState<string | null>(null)

  if (history.length === 0) return null

  return (
    <div className="border rounded-lg overflow-hidden text-sm">
      {/* Header toggle */}
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center justify-between px-4 py-3 font-medium hover:bg-muted/50 transition-colors"
      >
        <span>Tìm kiếm gần đây</span>
        <span className="text-xs text-muted-foreground">
          {history.length} lần {open ? "▲" : "▼"}
        </span>
      </button>

      {open && (
        <div className="divide-y border-t">
          {history.map(entry => (
            <div key={entry.id} className="px-4 py-3 space-y-2">

              {/* Search header — click to expand candidates */}
              <button
                onClick={() => setExpanded(expanded === entry.id ? null : entry.id)}
                className="w-full text-left"
              >
                <div className="flex items-start justify-between gap-3">
                  <p className="text-xs text-muted-foreground line-clamp-2 flex-1">
                    {entry.query.length > 120
                      ? entry.query.slice(0, 120) + "…"
                      : entry.query}
                  </p>
                  <div className="shrink-0 text-right space-y-0.5">
                    <p className="text-[11px] text-muted-foreground whitespace-nowrap">
                      {new Date(entry.timestamp).toLocaleString("vi-VN", {
                        day: "2-digit", month: "2-digit",
                        hour: "2-digit", minute: "2-digit",
                      })}
                    </p>
                    <p className="text-[11px] text-muted-foreground">
                      {entry.results.length} ứng viên {expanded === entry.id ? "▲" : "▼"}
                    </p>
                  </div>
                </div>
              </button>

              {/* Candidate list */}
              {expanded === entry.id && (
                <div className="space-y-1 pt-1">
                  {entry.results.map(c => {
                    const pct  = Math.round(Math.min(1, Math.max(0, c.score)) * 100)
                    const tone = pct >= 70 ? "green" : pct >= 40 ? "amber" : "gray"
                      const jobTitle = entry.jobTitle || extractJobTitleFromJd(entry.query)
                    const personnelId = (c as CandidateResult & { personnel_id?: string }).personnel_id || c.id
                    const params = new URLSearchParams({
                      personnelId,
                      jobTitle,
                      sessionId: "new",
                    })
                    return (
                      <Link
                        key={c.id}
                        href={`/interview?${params.toString()}`}
                        className="flex items-center justify-between gap-3 px-3 py-2 rounded-md hover:bg-muted/60 transition-colors"
                      >
                        <span className="truncate text-sm">{c.name || c.id}</span>
                        <div className="flex items-center gap-2 shrink-0">
                          <span className={cn(
                            "text-xs font-medium tabular-nums",
                            tone === "green" && "text-green-700",
                            tone === "amber" && "text-amber-700",
                            tone === "gray"  && "text-muted-foreground",
                          )}>
                            {pct}%
                          </span>
                          {/* Relationship status: not available without extra API call */}
                          <span className="text-[11px] text-muted-foreground border rounded px-1.5 py-0.5">
                            —
                          </span>
                        </div>
                      </Link>
                    )
                  })}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function OrgSearchPage() {
  const router = useRouter()
  const orgNeoId = useAuthStore((state) => state.neoId)
  const [results,   setResults]   = useState<CandidateResult[]>([])
  const [searched,  setSearched]  = useState(false)
  const [history,   setHistory]   = useState<SearchHistoryEntry[]>([])
  const [submittedJobTitle, setSubmittedJobTitle] = useState("")
  const [lastForm, setLastForm] = useState<SearchFormValues | null>(null)

  useEffect(() => {
    setHistory(loadHistory())
  }, [])

  const mutation = useMutation({
    mutationFn: (form: SearchFormValues) =>
      searchCandidates({ query: buildSearchQuery(form), top_k: 5 }),
    onSuccess: (data, form) => {
      const candidates = mapSearchResponseToCandidates(data)
      setResults(candidates)
      setSearched(true)
      setSubmittedJobTitle(form.job_title)

      if (candidates.length > 0) {
        const entry: SearchHistoryEntry = {
          id:        crypto.randomUUID(),
          query:     buildSearchQuery(form),
          jobTitle:  form.job_title,
          timestamp: Date.now(),
          results:   candidates,
        }
        saveHistory(entry)
        setHistory(loadHistory())
      }
    },
  })

  function buildSearchQuery(form: SearchFormValues): string {
    const parts: string[] = []

    parts.push(form.job_title.trim())

    if (form.seniority_level) {
      parts.push(`Cấp độ: ${form.seniority_level}`)
    }

    if (form.must_have_skills.length > 0) {
      parts.push(`Kỹ năng bắt buộc: ${form.must_have_skills.join(', ')}`)
    }

    if (form.job_description?.trim()) {
      parts.push(form.job_description.trim())
    }

    return parts.join('. ')
  }

  function handleSearch(form: SearchFormValues) {
    setLastForm(form)
    setSubmittedJobTitle(form.job_title)
    mutation.mutate(form)
  }

  async function handleStartInterview(candidate: CandidateResult) {
    if (!orgNeoId) {
      toast.error("Không tìm thấy tổ chức hiện tại.")
      return
    }

    try {
      const reasoningSummary: ReasoningSummary | undefined = candidate.reasoning_summary
        ? candidate.reasoning_summary
        : {
            skills: candidate.skills ?? [],
            seniority_years: null,
            connection_strength: null,
            match_score: candidate.score,
          }

      const session = await createInterviewSession({
        personnel_id: candidate.personnel_id || candidate.id,
        org_id: orgNeoId,
        job_title: submittedJobTitle || "Vị trí chưa xác định",
        reasoning_summary: reasoningSummary,
      })

      const params = new URLSearchParams({
        personnelId: candidate.personnel_id || candidate.id,
        jobTitle: submittedJobTitle || "Vị trí chưa xác định",
        sessionId: session.session_id,
      })

      router.push(`/interview?${params.toString()}`)
    } catch (error) {
      console.error("Failed to create interview session", error)
      toast.error("Không thể mở phiên phỏng vấn. Thử lại sau.")
    }
  }

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Tìm kiếm ứng viên
        </h1>
        <p className="text-muted-foreground mt-1 text-sm">
          Dán hoặc nhập mô tả công việc (JD), sau đó nhấn Tìm ứng viên.
        </p>
      </div>

      <SearchBar onSearch={handleSearch} loading={mutation.isPending} />

      <RecentSearchHistory history={history} />

      <SearchResults
        results={results}
        jobTitle={submittedJobTitle}
        loading={mutation.isPending}
        error={mutation.error}
        searched={searched}
        onStartInterview={handleStartInterview}
        onRetry={
          lastForm
            ? () => { mutation.mutate(lastForm) }
            : undefined
        }
      />
    </div>
  )
}
