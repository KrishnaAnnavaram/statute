import { useQuery } from "@tanstack/react-query";
import { api, type HealthCheck, type Status } from "./api";

/** The snapshot is always authoritative, so a missed or duplicated poll can never
 *  lose or invent state (research §38). Polling pauses while the tab is hidden. */
export function useStatus() {
  return useQuery({
    queryKey: ["status"],
    queryFn: () => api<Status>("/status"),
    // Local and cheap (~40-90 ms), so poll every 2 s while visible: a newly started
    // run must appear within one poll even when the console was idle (criterion S6).
    refetchInterval: 2000,
    refetchIntervalInBackground: false,
  });
}

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: () => api<{ checks: HealthCheck[] }>("/health"),
    refetchInterval: 60000,
  });
}
