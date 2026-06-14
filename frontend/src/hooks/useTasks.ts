/**
 * Async task board state: list / create / cancel / retry against /api/tasks.
 * Polls (faster than cron, since states move quickly) so the board stays fresh
 * while the tab is open.
 */
import { useState, useEffect, useCallback } from "react";
import type { Task } from "../types";

export function useTasks() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchTasks = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/tasks");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setTasks(await res.json());
    } catch (err) {
      console.error("Failed to fetch tasks:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTasks();
    const id = setInterval(fetchTasks, 3000);
    return () => clearInterval(id);
  }, [fetchTasks]);

  const createTask = useCallback(
    async (prompt: string, title?: string) => {
      const res = await fetch("/api/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt, title: title || null }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      await fetchTasks();
    },
    [fetchTasks]
  );

  const cancelTask = useCallback(
    async (id: string) => {
      try {
        await fetch(`/api/tasks/${id}/cancel`, { method: "POST" });
        setTimeout(fetchTasks, 300);
      } catch (err) {
        console.error("Failed to cancel task:", err);
      }
    },
    [fetchTasks]
  );

  const retryTask = useCallback(
    async (id: string) => {
      try {
        await fetch(`/api/tasks/${id}/retry`, { method: "POST" });
        setTimeout(fetchTasks, 300);
      } catch (err) {
        console.error("Failed to retry task:", err);
      }
    },
    [fetchTasks]
  );

  return { tasks, loading, fetchTasks, createTask, cancelTask, retryTask };
}
