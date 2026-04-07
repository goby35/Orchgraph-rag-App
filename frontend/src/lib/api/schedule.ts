import type { paths } from "@/types/api"

import type { AvailableSlot, ScheduleRecord } from "@/types"

import { apiClient } from "./client"

type AvailabilityBody =
  paths["/availability"]["put"]["requestBody"]["content"]["application/json"]
type AvailabilityResponse =
  paths["/availability"]["put"]["responses"]["200"]["content"]["application/json"]
type ScheduleCreate =
  paths["/schedule"]["post"]["requestBody"]["content"]["application/json"]
type ScheduleStatusBody =
  paths["/schedule/{schedule_id}/status"]["patch"]["requestBody"]["content"]["application/json"]
type ScheduleRescheduleBody =
  paths["/schedule/{schedule_id}/reschedule"]["patch"]["requestBody"]["content"]["application/json"]

interface ScheduleCounterProposeBody {
  proposed_time: string
  notes?: string
}

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
): Promise<ScheduleRecord> =>
  apiClient.post<ScheduleRecord>("/schedule", body).then((r) => r.data)

export const updateScheduleStatus = (
  id: string,
  status: ScheduleStatusBody["status"],
  notes?: string,
): Promise<ScheduleRecord> => {
  const body: ScheduleStatusBody = { status, notes }
  return apiClient
    .patch<ScheduleRecord>(
      `/schedule/${encodeURIComponent(id)}/status`,
      body,
    )
    .then((r) => r.data)
}

export const rescheduleAppointment = (
  id: string,
  rescheduled_at: string,
  notes?: string,
): Promise<ScheduleRecord> => {
  const body: ScheduleRescheduleBody = { rescheduled_at, notes }
  return apiClient
    .patch<ScheduleRecord>(
      `/schedule/${encodeURIComponent(id)}/reschedule`,
      body,
    )
    .then((r) => r.data)
}

export const counterProposeSchedule = (
  id: string,
  proposed_time: string,
  notes?: string,
): Promise<ScheduleRecord> => {
  const body: ScheduleCounterProposeBody = { proposed_time, notes }
  return apiClient
    .patch<ScheduleRecord>(
      `/schedule/${encodeURIComponent(id)}/counter-propose`,
      body,
    )
    .then((r) => r.data)
}

export const listSchedules = (): Promise<ScheduleRecord[]> =>
  apiClient.get<ScheduleRecord[]>("/schedule").then((r) => r.data)
