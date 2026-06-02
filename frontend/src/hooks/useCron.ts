/**
 * Cron schedule state: list / create / delete / run-now against /api/cron.
 * Polls so next_run / last_run / status stay fresh while the tab is open.
 */
import { useState, useEffect, useCallback } from "react";
import type { CronJob } from "../types";

export function useCron() {
  const [jobs, setJobs] = useState<CronJob[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchJobs = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/cron");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setJobs(await res.json());
    } catch (err) {
      console.error("Failed to fetch schedules:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchJobs();
    const id = setInterval(fetchJobs, 10000);
    return () => clearInterval(id);
  }, [fetchJobs]);

  const createJob = useCallback(
    async (name: string, cron: string, prompt: string) => {
      const res = await fetch("/api/cron", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, cron, prompt }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      await fetchJobs();
    },
    [fetchJobs]
  );

  const deleteJob = useCallback(async (id: string) => {
    try {
      await fetch(`/api/cron/${id}`, { method: "DELETE" });
      setJobs((prev) => prev.filter((j) => j.id !== id));
    } catch (err) {
      console.error("Failed to delete schedule:", err);
    }
  }, []);

  const runNow = useCallback(
    async (id: string) => {
      try {
        await fetch(`/api/cron/${id}/run`, { method: "POST" });
        setTimeout(fetchJobs, 600);
      } catch (err) {
        console.error("Failed to run schedule:", err);
      }
    },
    [fetchJobs]
  );

  return { jobs, loading, fetchJobs, createJob, deleteJob, runNow };
}
