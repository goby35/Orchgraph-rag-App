"use client"
import { useAuthStore } from "@/store/auth.store"
import FileDropzone     from "@/components/ingest/FileDropzone"
import { cn }           from "@/lib/utils"
import { getGraph } from "@/lib/api/graph"
import { useQuery } from "@tanstack/react-query"

// Sections sau (skills, graph, chat) sẽ thêm vào file này
// khi có API — không cần tạo file mới

export default function ProfilePage() {
  const user  = useAuthStore(s => s.user)
  const neoId = useAuthStore(s => s.neoId)

  const fullName = (user?.user_metadata?.full_name as string | undefined)
    ?? user?.email
    ?? "Personnel"

  const email    = user?.email ?? ""
  const initials = fullName
    .split(" ")
    .filter(Boolean)
    .slice(-2)
    .map(w => w[0])
    .join("")
    .toUpperCase()

  return (
    <div className="mx-auto max-w-3xl space-y-6 px-4 py-8">
      <h1 className="text-2xl font-bold tracking-tight">Hồ sơ của tôi</h1>

      {/* ── Section 1: Thông tin cơ bản ── */}
      <section className="flex items-center gap-5 rounded-2xl border border-border/70 bg-card/90 p-6 shadow-sm">
        <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full bg-primary/12">
          <span className="text-lg font-semibold text-primary">{initials}</span>
        </div>
        <div className="space-y-1 min-w-0">
          <p className="truncate text-base font-semibold tracking-tight">{fullName}</p>
          <p className="truncate text-sm text-muted-foreground">{email}</p>
          <div className="flex items-center gap-2 flex-wrap">
            <span className="rounded-full border border-primary/20 bg-primary/12 px-2.5 py-0.5 text-xs font-medium text-primary">
              Ứng viên
            </span>
            {neoId && (
              <span className="text-xs text-muted-foreground font-mono">
                {neoId}
              </span>
            )}
          </div>
        </div>
      </section>

      {/* ── Section 2: Upload CV ── */}
      <section className="space-y-3 rounded-2xl border border-border/70 bg-card/90 p-6 shadow-sm">
        <div>
          <h2 className="text-base font-semibold">Upload hồ sơ</h2>
          <p className="text-sm text-muted-foreground mt-1">
            Upload CV để hệ thống phân tích và cập nhật Digital Twin của bạn.
          </p>
        </div>
        <FileDropzone />
      </section>

      {/* ── Placeholder: Skills/Summary — thêm sau khi có API ── */}
      {neoId !== null && <SkillsSummarySection neoId={neoId} />}

      {/* ── Placeholder: Chat history — thêm sau khi confirm API ── */}
      {/* <ChatHistorySection neoId={neoId} /> */}
    </div>
  )
}

// ── Skeleton sections — sẽ replace bằng real data sau ──

function SkillsSummarySection({ neoId }: { neoId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["graph"],
    queryFn:  () => getGraph(false),
    staleTime: 5 * 60 * 1000,
  })

  const myNode = data?.nodes.find((n) => String(n["id"]) === neoId)

  const rawSkills = (myNode?.data as Record<string, unknown> | undefined)?.skills
  const skills: string[] = Array.isArray(rawSkills) ? rawSkills.map(String) : []

  const rawSummary = (myNode?.data as Record<string, unknown> | undefined)?.summary
  const summary: string = typeof rawSummary === "string" ? rawSummary : ""

  return (
      <section className="space-y-4 rounded-2xl border border-border/70 bg-card/90 p-6 shadow-sm">
      <h2 className="text-base font-semibold">Skills & Giới thiệu</h2>

      {isLoading ? (
        <div className="space-y-2">
          <div className="h-4 bg-muted rounded animate-pulse w-3/4" />
          <div className="h-4 bg-muted rounded animate-pulse w-1/2" />
          <div className="h-4 bg-muted rounded animate-pulse w-2/3" />
        </div>
      ) : !myNode ? (
        <p className="text-sm text-muted-foreground text-center py-4">
          Chưa có dữ liệu. Upload CV để hệ thống phân tích và tạo profile tự động.
        </p>
      ) : (
        <div className="space-y-4">
          {summary && (
            <div>
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1">
                Giới thiệu
              </p>
              <p className="text-sm leading-relaxed">{summary}</p>
            </div>
          )}
          {skills.length > 0 && (
            <div>
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
                Kỹ năng
              </p>
              <div className="flex flex-wrap gap-1.5">
                {skills.map(skill => (
                  <span
                    key={skill}
                    className="rounded-full border border-border/70 bg-secondary/75 px-2.5 py-0.5 text-xs text-secondary-foreground"
                  >
                    {skill}
                  </span>
                ))}
              </div>
            </div>
          )}
          {!summary && skills.length === 0 && (
            <p className="text-sm text-muted-foreground">
              Chưa có thông tin skills hoặc giới thiệu.
            </p>
          )}
        </div>
      )}
    </section>
  )
}

function ChatHistorySection({ neoId }: { neoId: string | null }) {
  if (!neoId) return null
  return (
    <section className="space-y-3 rounded-2xl border border-border/70 bg-card/80 p-6 opacity-60 shadow-sm">
      <h2 className="text-base font-semibold">Lịch sử cuộc trò chuyện</h2>
      <p className="text-sm text-muted-foreground">
        Đang chờ xác nhận API endpoint...
      </p>
    </section>
  )
}