/**
 * Canvas state management with REST fetch.
 * Re-fetches when .canvas/ files change (via file watcher events).
 */

import { useState, useEffect, useCallback } from "react";
import type { CanvasItem } from "../types";

export function useCanvas(
  fileChanges: { event: string; path: string }[]
) {
  const [items, setItems] = useState<CanvasItem[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchItems = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/canvas/items");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setItems(data);
    } catch (err) {
      console.error("Failed to fetch canvas items:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial fetch
  useEffect(() => {
    fetchItems();
  }, [fetchItems]);

  // Re-fetch when .canvas/ files change
  useEffect(() => {
    if (fileChanges.some((c) => c.path.startsWith("/.canvas/"))) {
      fetchItems();
    }
  }, [fileChanges, fetchItems]);

  const deleteItem = useCallback(async (id: string) => {
    try {
      await fetch(`/api/canvas/items/${id}`, { method: "DELETE" });
      setItems((prev) => prev.filter((item) => item.id !== id));
    } catch (err) {
      console.error("Failed to delete canvas item:", err);
    }
  }, []);

  const clearAll = useCallback(async () => {
    try {
      await fetch("/api/canvas/items", { method: "DELETE" });
      setItems([]);
    } catch (err) {
      console.error("Failed to clear canvas:", err);
    }
  }, []);

  const exportMarkdown = useCallback(async () => {
    try {
      const res = await fetch("/api/canvas/export");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      return data.content as string;
    } catch (err) {
      console.error("Failed to export canvas:", err);
      return "";
    }
  }, []);

  return { items, loading, fetchItems, deleteItem, clearAll, exportMarkdown };
}
