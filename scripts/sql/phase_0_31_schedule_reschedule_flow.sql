-- Phase 0.31: schedule reschedule workflow updates.

ALTER TABLE vdme.interview_schedules
  ADD COLUMN IF NOT EXISTS reschedule_history jsonb DEFAULT '[]'::jsonb;

UPDATE vdme.interview_schedules
SET reschedule_history = COALESCE(reschedule_history, '[]'::jsonb)
WHERE reschedule_history IS NULL;
