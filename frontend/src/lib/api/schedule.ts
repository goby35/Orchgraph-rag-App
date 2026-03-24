import type { paths } from "@/types/api"

import type { AvailableSlot } from "@/types"

import { apiClient } from "./client"

type AvailabilityBody =
  paths["/availability"]["put"]["requestBody"]["content"]["application/json"]
type AvailabilityResponse =
  paths["/availability"]["put"]["responses"]["200"]["content"]["application/json"]
type ScheduleCreate =
  paths["/schedule"]["post"]["requestBody"]["content"]["application/json"]
type ScheduleResponse =
  paths["/schedule"]["post"]["responses"]["200"]["content"]["application/json"]
type ScheduleList =
  paths["/schedule"]["get"]["responses"]["200"]["content"]["application/json"]
type ScheduleStatusBody =
  paths["/schedule/{schedule_id}/status"]["patch"]["requestBody"]["content"]["application/json"]
type ScheduleRescheduleBody =
  paths["/schedule/{schedule_id}/reschedule"]["patch"]["requestBody"]["content"]["application/json"]

export const upsertAvailability = (
  body: AvailabilityBody,
): Promise<AvailabilityResponse> =>
  apiClient.put<AvailabilityResponse>("/availability", body).then((r) => r.data)

export const getAvailableSlots = (
  perNeoId: string,
  daysAhead = 14,
): Promise<AvailableSlot[]> =>
  apiClient
    .get<AvailableSlot[]>(`/availability/${encodeURIComponent(perNeoId)}/slots`, {
      params: { days_ahead: daysAhead },
    })
    .then((r) => r.data)

export const createSchedule = (
  body: ScheduleCreate,
): Promise<ScheduleResponse> =>
  apiClient.post<ScheduleResponse>("/schedule", body).then((r) => r.data)

export const updateScheduleStatus = (
  id: string,
  status: ScheduleStatusBody["status"],
  notes?: string,
): Promise<ScheduleResponse> => {
  const body: ScheduleStatusBody = { status, notes }
  return apiClient
    .patch<ScheduleResponse>(
      `/schedule/${encodeURIComponent(id)}/status`,
      body,
    )
    .then((r) => r.data)
}

export const rescheduleAppointment = (
  id: string,
  rescheduled_at: string,
  notes?: string,
): Promise<ScheduleResponse> => {
  const body: ScheduleRescheduleBody = { rescheduled_at, notes }
  return apiClient
    .patch<ScheduleResponse>(
      `/schedule/${encodeURIComponent(id)}/reschedule`,
      body,
    )
    .then((r) => r.data)
}

export const listSchedules = (): Promise<ScheduleList> =>
  apiClient.get<ScheduleList>("/schedule").then((r) => r.data)
