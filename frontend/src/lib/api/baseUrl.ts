const LEGACY_MODAL_SUFFIX = "--orchgraph-rag.modal.run"
const FASTAPI_MODAL_SUFFIX = "--orchgraph-rag-fastapi-app.modal.run"

function normalizeModalAppUrl(rawUrl: string): string {
  if (rawUrl.includes(FASTAPI_MODAL_SUFFIX)) {
    return rawUrl
  }
  if (rawUrl.includes(LEGACY_MODAL_SUFFIX)) {
    return rawUrl.replace(LEGACY_MODAL_SUFFIX, FASTAPI_MODAL_SUFFIX)
  }
  return rawUrl
}

export function resolveApiBaseUrl(): string {
  const configured = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").trim()
  const normalized = normalizeModalAppUrl(configured)
  return normalized.replace(/\/$/, "")
}
