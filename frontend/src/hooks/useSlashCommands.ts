import { useState, useCallback, useRef, useMemo } from "react";
import type { FileEntry } from "../types";

export interface SlashCommandDefinition {
  name: string;
  label: string;
  description: string;
  hasArg: boolean;
  expandMessage: (arg?: string) => string;
}

interface SlashCommandsOptions {
  saveWorkflowPrompt?: string;
  runWorkflowPrompt?: string;
}

const DEFAULT_SAVE_PROMPT =
  "Please capture this conversation as a detailed workflow markdown file in the ./workflows/ directory. Include: a title, description of the goal, step-by-step instructions that could be followed to reproduce this workflow, any configuration or parameters needed, and expected outputs.";

const DEFAULT_RUN_PROMPT =
  "Please read and follow the workflow defined in ./workflows/{filename}. Execute each step as described in the workflow file.";

function buildCommands(savePrompt: string, runPrompt: string): SlashCommandDefinition[] {
  return [
    {
      name: "save-workflow",
      label: "/save-workflow",
      description: "Save this conversation as a reusable workflow",
      hasArg: false,
      expandMessage: (arg?: string) =>
        arg ? `${savePrompt}\n\nAdditional instructions: ${arg}` : savePrompt,
    },
    {
      name: "run-workflow",
      label: "/run-workflow",
      description: "Execute a saved workflow from ./workflows/",
      hasArg: true,
      expandMessage: (arg?: string) => {
        const parts = arg?.match(/^(\S+\.md)\s*(.*)$/);
        if (parts) {
          const base = runPrompt.replace("{filename}", parts[1]);
          return parts[2] ? `${base}\n\nAdditional instructions: ${parts[2]}` : base;
        }
        return runPrompt.replace("{filename}", arg ?? "");
      },
    },
  ];
}

export function useSlashCommands(options: SlashCommandsOptions = {}) {
  const commands = useMemo(
    () => buildCommands(
      options.saveWorkflowPrompt || DEFAULT_SAVE_PROMPT,
      options.runWorkflowPrompt || DEFAULT_RUN_PROMPT,
    ),
    [options.saveWorkflowPrompt, options.runWorkflowPrompt],
  );

  const [showCommandMenu, setShowCommandMenu] = useState(false);
  const [showWorkflowPicker, setShowWorkflowPicker] = useState(false);
  const [filteredCommands, setFilteredCommands] = useState<SlashCommandDefinition[]>([]);
  const [filteredWorkflowFiles, setFilteredWorkflowFiles] = useState<string[]>([]);
  const [isLoadingWorkflows, setIsLoadingWorkflows] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);

  const workflowCacheRef = useRef<{ files: string[]; fetchedAt: number }>({
    files: [],
    fetchedAt: 0,
  });

  const fetchWorkflowFiles = useCallback(async (): Promise<string[]> => {
    const now = Date.now();
    if (
      now - workflowCacheRef.current.fetchedAt < 30_000 &&
      workflowCacheRef.current.files.length > 0
    ) {
      return workflowCacheRef.current.files;
    }

    setIsLoadingWorkflows(true);
    try {
      const res = await fetch("/api/files/tree?path=/workflows&depth=1");
      if (!res.ok) return [];
      const data = await res.json();
      const entries: FileEntry[] = data.entries ?? [];
      const mdFiles = entries
        .filter((e) => !e.is_dir && e.name.endsWith(".md"))
        .map((e) => e.name);
      workflowCacheRef.current = { files: mdFiles, fetchedAt: now };
      return mdFiles;
    } catch {
      return [];
    } finally {
      setIsLoadingWorkflows(false);
    }
  }, []);

  const handleInputChange = useCallback(
    (value: string) => {
      // Case 1: starts with "/" and no space yet → command menu
      if (value.startsWith("/") && !value.includes(" ") && value.length < 30) {
        const prefix = value.toLowerCase();
        const matches = commands.filter((cmd) => cmd.label.startsWith(prefix));
        setFilteredCommands(matches);
        setShowCommandMenu(matches.length > 0);
        setShowWorkflowPicker(false);
        setSelectedIndex(0);
        return;
      }

      // Case 2: starts with "/run-workflow " → workflow picker
      if (value.startsWith("/run-workflow ") || value === "/run-workflow") {
        setShowCommandMenu(false);
        setShowWorkflowPicker(true);
        const filter = value.replace(/^\/run-workflow\s*/, "").toLowerCase();
        fetchWorkflowFiles().then((files) => {
          const filtered = filter
            ? files.filter((f) => f.toLowerCase().includes(filter))
            : files;
          setFilteredWorkflowFiles(filtered);
          setSelectedIndex(0);
        });
        return;
      }

      // Case 3: not a slash command
      setShowCommandMenu(false);
      setShowWorkflowPicker(false);
      setSelectedIndex(0);
    },
    [commands, fetchWorkflowFiles],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent): boolean => {
      if (!showCommandMenu && !showWorkflowPicker) return false;

      const items = showCommandMenu ? filteredCommands : filteredWorkflowFiles;
      const count = items.length;

      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          setSelectedIndex((prev) => (prev + 1) % Math.max(count, 1));
          return true;
        case "ArrowUp":
          e.preventDefault();
          setSelectedIndex((prev) => (prev - 1 + Math.max(count, 1)) % Math.max(count, 1));
          return true;
        case "Escape":
          e.preventDefault();
          setShowCommandMenu(false);
          setShowWorkflowPicker(false);
          return true;
        case "Tab":
        case "Enter":
          if (count > 0) {
            e.preventDefault();
            return true;
          }
          return false;
        default:
          return false;
      }
    },
    [showCommandMenu, showWorkflowPicker, filteredCommands, filteredWorkflowFiles],
  );

  const handleSelect = useCallback(
    (index: number): { expanded: string | null; newInput: string | null } => {
      if (showCommandMenu) {
        const cmd = filteredCommands[index];
        if (!cmd) return { expanded: null, newInput: null };
        if (!cmd.hasArg) {
          return { expanded: cmd.expandMessage(), newInput: null };
        }
        // /run-workflow → switch to file picker
        setShowCommandMenu(false);
        setShowWorkflowPicker(true);
        setSelectedIndex(0);
        fetchWorkflowFiles().then((files) => {
          setFilteredWorkflowFiles(files);
        });
        return { expanded: null, newInput: "/run-workflow " };
      }

      if (showWorkflowPicker) {
        const file = filteredWorkflowFiles[index];
        if (!file) return { expanded: null, newInput: null };
        const cmd = commands.find((c) => c.name === "run-workflow")!;
        return { expanded: cmd.expandMessage(file), newInput: null };
      }

      return { expanded: null, newInput: null };
    },
    [commands, showCommandMenu, showWorkflowPicker, filteredCommands, filteredWorkflowFiles, fetchWorkflowFiles],
  );

  const tryExecute = useCallback((input: string): string | null => {
    const trimmed = input.trim();
    // /save-workflow [optional instructions]
    const saveMatch = trimmed.match(/^\/save-workflow(?:\s+(.+))?$/);
    if (saveMatch) {
      return commands[0].expandMessage(saveMatch[1]?.trim());
    }
    // /run-workflow <file> [optional instructions]
    const runMatch = trimmed.match(/^\/run-workflow\s+(.+)$/);
    if (runMatch) {
      return commands[1].expandMessage(runMatch[1].trim());
    }
    return null;
  }, [commands]);

  const reset = useCallback(() => {
    setShowCommandMenu(false);
    setShowWorkflowPicker(false);
    setFilteredCommands([]);
    setFilteredWorkflowFiles([]);
    setSelectedIndex(0);
  }, []);

  return {
    showCommandMenu,
    showWorkflowPicker,
    filteredCommands,
    filteredWorkflowFiles,
    isLoadingWorkflows,
    selectedIndex,
    setSelectedIndex,
    handleInputChange,
    handleKeyDown,
    handleSelect,
    tryExecute,
    reset,
  };
}
