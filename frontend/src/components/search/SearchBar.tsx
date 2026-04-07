"use client"

import { Loader2 } from "lucide-react"
import { useForm, Controller } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { TagInput } from "@/components/ui/tag-input"
import { cn } from "@/lib/utils"

const searchSchema = z.object({
  job_title: z.string().trim().min(1, "Vui lòng nhập vị trí tuyển dụng"),
  seniority_level: z.string().optional(),
  must_have_skills: z.array(z.string()).default([]),
  job_description: z.string().optional(),
})

export type SearchFormValues = z.infer<typeof searchSchema>

interface SearchBarProps {
  onSearch: (form: SearchFormValues) => void
  loading: boolean
}

export function SearchBar({ onSearch, loading }: SearchBarProps) {
  const {
    register,
    control,
    handleSubmit,
    watch,
    formState: { errors },
  } = useForm<z.input<typeof searchSchema>, any, SearchFormValues>({
    resolver: zodResolver(searchSchema),
    defaultValues: {
      job_title: "",
      seniority_level: "",
      must_have_skills: [],
      job_description: "",
    },
  })

  const jobDescription = watch("job_description") ?? ""

  const submit = handleSubmit((values) => {
    if (loading) return
    onSearch({
      job_title: values.job_title.trim(),
      seniority_level: values.seniority_level ?? "",
      must_have_skills: values.must_have_skills ?? [],
      job_description: values.job_description ?? "",
    })
  })

  return (
    <form onSubmit={submit} className="flex w-full max-w-4xl flex-col gap-5">
      <div className="grid gap-4 rounded-2xl border bg-card p-4 shadow-sm md:p-6">
        <div className="grid gap-2">
          <Label htmlFor="job_title">Vị trí tuyển dụng</Label>
          <Input
            id="job_title"
            placeholder="VD: Senior Data Engineer"
            disabled={loading}
            aria-invalid={Boolean(errors.job_title)}
            {...register("job_title")}
          />
          <p className="text-xs text-muted-foreground">
            Dùng làm nhãn cho các cuộc phỏng vấn
          </p>
          {errors.job_title ? (
            <p className="text-xs text-destructive">{errors.job_title.message}</p>
          ) : null}
        </div>

        <div className="grid gap-2">
          <Label htmlFor="seniority_level">Cấp độ</Label>
          <select
            id="seniority_level"
            disabled={loading}
            className={cn(
              "h-8 w-full rounded-lg border border-input bg-background px-2.5 py-1 text-sm outline-none transition-colors",
              "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50",
            )}
            {...register("seniority_level")}
          >
            <option value="">Chọn cấp độ (tuỳ chọn)</option>
            <option value="Intern">Intern</option>
            <option value="Junior">Junior</option>
            <option value="Mid-level">Mid-level</option>
            <option value="Senior">Senior</option>
            <option value="Lead">Lead</option>
            <option value="Principal / Staff">Principal / Staff</option>
            <option value="Manager">Manager</option>
          </select>
        </div>

        <div className="grid gap-2">
          <Label htmlFor="must_have_skills">Kỹ năng bắt buộc</Label>
          <Controller
            control={control}
            name="must_have_skills"
            render={({ field }) => (
              <TagInput
                value={field.value ?? []}
                onChange={field.onChange}
                placeholder="Nhập kỹ năng rồi nhấn Enter hoặc dấu phẩy..."
                className="min-h-12"
              />
            )}
          />
        </div>

        <div className="grid gap-2">
          <div className="flex items-end justify-between gap-3">
            <Label htmlFor="job_description">Mô tả công việc</Label>
            <span className="text-xs text-muted-foreground">
              {jobDescription.length} ký tự
            </span>
          </div>
          <Textarea
            id="job_description"
            placeholder={
              "Mô tả yêu cầu, trách nhiệm, môi trường làm việc...\nMô tả càng chi tiết, kết quả matching càng chính xác."
            }
            disabled={loading}
            rows={8}
            className="min-h-[180px] resize-y"
            aria-label="Mô tả công việc"
            {...register("job_description")}
          />
        </div>
      </div>

      <div className="flex justify-end">
        <Button type="submit" disabled={loading}>
          {loading ? (
            <>
              <Loader2 className="size-4 animate-spin" aria-hidden />
              Đang tìm kiếm...
            </>
          ) : (
            "Tìm ứng viên phù hợp"
          )}
        </Button>
      </div>
    </form>
  )
}
