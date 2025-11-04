// src/api/notifications.ts
export interface EventRecord {
  id: string;
  event_type: string;
  source_service: string;
  occurred_at: string;
  payload: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}

export async function fetchEvents(
  limit = 50,
  eventType?: string,
  sourceService?: string
): Promise<EventRecord[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (eventType) params.append("event_type", eventType);
  if (sourceService) params.append("source_service", sourceService);

  const res = await fetch(`/notifications/events?${params.toString()}`);
  if (!res.ok) throw new Error("Failed to fetch events");
  return res.json();
}
