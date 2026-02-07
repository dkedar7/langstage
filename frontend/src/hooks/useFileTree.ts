/**
 * File tree state management with REST fetch and live updates.
 * Supports workspace navigation, file preview, upload, and mkdir.
 */

import { useState, useEffect, useCallback } from "react";
import type { FileEntry, FilePreview } from "../types";

interface FileTreeState {
  entries: FileEntry[];
  loading: boolean;
  error: string | null;
}

export function useFileTree(fileChanges: { event: string; path: string }[]) {
  const [tree, setTree] = useState<FileTreeState>({
    entries: [],
    loading: true,
    error: null,
  });
  const [selectedFile, setSelectedFile] = useState<FilePreview | null>(null);
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set(["/"]));
  const [workspacePath, setWorkspacePath] = useState("/");

  const fetchTree = useCallback(async (path = "/", depth = 1) => {
    try {
      const res = await fetch(
        `/api/files/tree?path=${encodeURIComponent(path)}&depth=${depth}`
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      return data.entries as FileEntry[];
    } catch (err) {
      console.error("Failed to fetch file tree:", err);
      return [];
    }
  }, []);

  const loadRoot = useCallback(async () => {
    setTree((s) => ({ ...s, loading: true }));
    const entries = await fetchTree(workspacePath, 1);
    setTree({ entries, loading: false, error: null });
  }, [fetchTree, workspacePath]);

  useEffect(() => {
    loadRoot();
  }, [loadRoot]);

  // Refresh on file changes
  useEffect(() => {
    if (fileChanges.length > 0) {
      loadRoot();
    }
  }, [fileChanges, loadRoot]);

  const toggleDir = useCallback(
    async (path: string) => {
      setExpandedDirs((prev) => {
        const next = new Set(prev);
        if (next.has(path)) {
          next.delete(path);
        } else {
          next.add(path);
        }
        return next;
      });

      // Fetch children if not loaded
      setTree((prev) => {
        const updateChildren = (entries: FileEntry[]): FileEntry[] =>
          entries.map((e) => {
            if (e.path === path && e.is_dir && !e.children) {
              return { ...e, children: [] };
            }
            if (e.children) {
              return { ...e, children: updateChildren(e.children) };
            }
            return e;
          });
        return { ...prev, entries: updateChildren(prev.entries) };
      });

      const children = await fetchTree(path, 1);
      setTree((prev) => {
        const setChildren = (entries: FileEntry[]): FileEntry[] =>
          entries.map((e) => {
            if (e.path === path) {
              return { ...e, children };
            }
            if (e.children) {
              return { ...e, children: setChildren(e.children) };
            }
            return e;
          });
        return { ...prev, entries: setChildren(prev.entries) };
      });
    },
    [fetchTree]
  );

  const openFile = useCallback(async (path: string) => {
    try {
      const res = await fetch(
        `/api/files/preview?path=${encodeURIComponent(path)}`
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: FilePreview = await res.json();
      setSelectedFile(data);
    } catch (err) {
      console.error("Failed to preview file:", err);
    }
  }, []);

  const enterDir = useCallback(
    (path: string) => {
      setWorkspacePath(path);
      setExpandedDirs(new Set([path]));
      setSelectedFile(null);
    },
    []
  );

  const uploadFile = useCallback(
    async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      try {
        const res = await fetch(
          `/api/files/upload?path=${encodeURIComponent(workspacePath)}`,
          { method: "POST", body: form }
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        loadRoot();
      } catch (err) {
        console.error("Failed to upload file:", err);
      }
    },
    [workspacePath, loadRoot]
  );

  const createFolder = useCallback(
    async (name: string) => {
      const folderPath =
        workspacePath === "/"
          ? `/${name}`
          : `${workspacePath}/${name}`;
      try {
        const res = await fetch("/api/files/mkdir", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: folderPath }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        loadRoot();
      } catch (err) {
        console.error("Failed to create folder:", err);
      }
    },
    [workspacePath, loadRoot]
  );

  const deletePath = useCallback(
    async (path: string) => {
      try {
        const res = await fetch("/api/files/delete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        loadRoot();
      } catch (err) {
        console.error("Failed to delete:", err);
      }
    },
    [loadRoot]
  );

  return {
    tree,
    selectedFile,
    expandedDirs,
    workspacePath,
    toggleDir,
    openFile,
    enterDir,
    uploadFile,
    createFolder,
    deletePath,
    setSelectedFile,
    refresh: loadRoot,
  };
}
