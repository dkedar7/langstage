import { useState, useRef, useEffect } from "react";
import {
  ChevronDown,
  ChevronRight,
  Folder,
  FolderOpen,
  FileText,
  FileCode,
  File,
  FolderPlus,
  Upload,
  Home,
  Trash2,
} from "lucide-react";
import type { FileEntry } from "../types";

interface FileBrowserProps {
  entries: FileEntry[];
  expandedDirs: Set<string>;
  loading: boolean;
  workspacePath: string;
  onToggleDir: (path: string) => void;
  onOpenFile: (path: string) => void;
  onEnterDir: (path: string) => void;
  onUpload: (file: File) => void;
  onCreateFolder: (name: string) => void;
  onDelete: (path: string) => void;
}

const CODE_EXTENSIONS = new Set([
  ".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".yaml", ".yml", ".toml",
  ".rs", ".go", ".java", ".c", ".cpp", ".h", ".hpp", ".rb", ".php",
  ".sql", ".sh", ".bash", ".r", ".css", ".html", ".xml",
]);

function getFileIcon(name: string) {
  const ext = "." + name.split(".").pop()?.toLowerCase();
  if (CODE_EXTENSIONS.has(ext)) return FileCode;
  if ([".md", ".txt", ".csv", ".log"].some((e) => name.endsWith(e)))
    return FileText;
  return File;
}

function formatSize(bytes: number | null | undefined): string {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

interface ContextMenuState {
  x: number;
  y: number;
  path: string;
  name: string;
}

interface TreeNodeProps {
  entry: FileEntry;
  expandedDirs: Set<string>;
  depth: number;
  onToggleDir: (path: string) => void;
  onOpenFile: (path: string) => void;
  onEnterDir: (path: string) => void;
  onContextMenu: (e: React.MouseEvent, path: string, name: string) => void;
}

function TreeNode({
  entry,
  expandedDirs,
  depth,
  onToggleDir,
  onOpenFile,
  onEnterDir,
  onContextMenu,
}: TreeNodeProps) {
  const isExpanded = expandedDirs.has(entry.path);

  if (entry.is_dir) {
    const FolderIcon = isExpanded ? FolderOpen : Folder;
    return (
      <div>
        <button
          onClick={() => onToggleDir(entry.path)}
          onDoubleClick={() => onEnterDir(entry.path)}
          onContextMenu={(e) => onContextMenu(e, entry.path, entry.name)}
          className="flex items-center gap-1.5 w-full px-2 py-1 text-sm hover:bg-[var(--color-surface-3)] rounded transition-colors"
          style={{ paddingLeft: `${depth * 16 + 8}px` }}
        >
          {isExpanded ? (
            <ChevronDown size={14} className="text-[var(--color-text-muted)] flex-shrink-0" />
          ) : (
            <ChevronRight size={14} className="text-[var(--color-text-muted)] flex-shrink-0" />
          )}
          <FolderIcon size={14} className="text-[var(--color-warning)] flex-shrink-0" />
          <span className="truncate text-[var(--color-text)]">
            {entry.name}
          </span>
        </button>
        {isExpanded && entry.children && (
          <div>
            {entry.children.map((child) => (
              <TreeNode
                key={child.path}
                entry={child}
                expandedDirs={expandedDirs}
                depth={depth + 1}
                onToggleDir={onToggleDir}
                onOpenFile={onOpenFile}
                onEnterDir={onEnterDir}
                onContextMenu={onContextMenu}
              />
            ))}
          </div>
        )}
      </div>
    );
  }

  const FileIcon = getFileIcon(entry.name);
  return (
    <button
      onClick={() => onOpenFile(entry.path)}
      onContextMenu={(e) => onContextMenu(e, entry.path, entry.name)}
      className="flex items-center gap-1.5 w-full px-2 py-1 text-sm hover:bg-[var(--color-surface-3)] rounded transition-colors"
      style={{ paddingLeft: `${depth * 16 + 22}px` }}
    >
      <FileIcon size={14} className="text-[var(--color-text-secondary)] flex-shrink-0" />
      <span className="truncate text-[var(--color-text)]">{entry.name}</span>
      {entry.size != null && (
        <span className="ml-auto text-xs text-[var(--color-text-muted)] flex-shrink-0">
          {formatSize(entry.size)}
        </span>
      )}
    </button>
  );
}

export function FileBrowser({
  entries,
  expandedDirs,
  loading,
  workspacePath,
  onToggleDir,
  onOpenFile,
  onEnterDir,
  onUpload,
  onCreateFolder,
  onDelete,
}: FileBrowserProps) {
  const [showNewFolder, setShowNewFolder] = useState(false);
  const [folderName, setFolderName] = useState("");
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const uploadRef = useRef<HTMLInputElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close context menu on click outside or Escape
  useEffect(() => {
    if (!contextMenu) return;
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setContextMenu(null);
      }
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setContextMenu(null);
    };
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("keydown", handleKey);
    };
  }, [contextMenu]);

  const handleContextMenu = (e: React.MouseEvent, path: string, name: string) => {
    e.preventDefault();
    setContextMenu({ x: e.clientX, y: e.clientY, path, name });
  };

  const handleDelete = () => {
    if (!contextMenu) return;
    if (window.confirm(`Delete "${contextMenu.name}"?`)) {
      onDelete(contextMenu.path);
    }
    setContextMenu(null);
  };

  const handleCreateFolder = () => {
    const name = folderName.trim();
    if (!name) return;
    onCreateFolder(name);
    setFolderName("");
    setShowNewFolder(false);
  };

  const handleUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;
    for (let i = 0; i < files.length; i++) {
      onUpload(files[i]);
    }
    e.target.value = "";
  };

  // Build breadcrumb segments from workspace path
  const breadcrumbs: { label: string; path: string }[] = [];
  if (workspacePath !== "/") {
    const parts = workspacePath.replace(/^\//, "").split("/");
    let acc = "";
    for (const part of parts) {
      acc += "/" + part;
      breadcrumbs.push({ label: part, path: acc });
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="flex items-center gap-1 px-2 py-1.5 border-b border-[var(--color-border)]">
        {/* Breadcrumb */}
        <div className="flex items-center gap-0.5 flex-1 min-w-0 text-xs text-[var(--color-text-secondary)]">
          <button
            onClick={() => onEnterDir("/")}
            className="p-0.5 rounded hover:bg-[var(--color-surface-3)] transition-colors flex-shrink-0"
            title="Workspace root"
          >
            <Home size={13} />
          </button>
          {breadcrumbs.map((crumb) => (
            <span key={crumb.path} className="flex items-center gap-0.5 min-w-0">
              <span className="text-[var(--color-text-muted)]">/</span>
              <button
                onClick={() => onEnterDir(crumb.path)}
                className="truncate hover:underline"
              >
                {crumb.label}
              </button>
            </span>
          ))}
        </div>

        {/* Actions */}
        <button
          onClick={() => setShowNewFolder((v) => !v)}
          className="p-1 rounded hover:bg-[var(--color-surface-3)] transition-colors flex-shrink-0"
          title="New folder"
        >
          <FolderPlus size={14} className="text-[var(--color-text-secondary)]" />
        </button>
        <button
          onClick={() => uploadRef.current?.click()}
          className="p-1 rounded hover:bg-[var(--color-surface-3)] transition-colors flex-shrink-0"
          title="Upload file"
        >
          <Upload size={14} className="text-[var(--color-text-secondary)]" />
        </button>
        <input
          ref={uploadRef}
          type="file"
          multiple
          onChange={handleUpload}
          className="hidden"
        />
      </div>

      {/* New folder input */}
      {showNewFolder && (
        <div className="flex items-center gap-1 px-2 py-1.5 border-b border-[var(--color-border)]">
          <input
            autoFocus
            value={folderName}
            onChange={(e) => setFolderName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleCreateFolder();
              if (e.key === "Escape") setShowNewFolder(false);
            }}
            placeholder="Folder name..."
            className="flex-1 text-xs bg-transparent text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:outline-none border border-[var(--color-border)] rounded px-2 py-1"
          />
          <button
            onClick={handleCreateFolder}
            className="text-xs text-[var(--color-primary)] hover:underline px-1"
          >
            Create
          </button>
        </div>
      )}

      {/* Tree */}
      <div className="flex-1 overflow-y-auto py-1">
        {loading && entries.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-2">
            <Folder size={20} className="text-[var(--color-text-muted)] animate-pulse" />
            <span className="text-sm text-[var(--color-text-muted)]">Loading files...</span>
          </div>
        ) : entries.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-3 px-6">
            <div className="w-10 h-10 rounded-lg bg-[var(--color-surface-3)] flex items-center justify-center">
              <Folder size={20} className="text-[var(--color-text-muted)]" />
            </div>
            <div className="text-center">
              <p className="text-sm font-medium text-[var(--color-text-secondary)]">Workspace is empty</p>
              <p className="text-xs text-[var(--color-text-muted)] mt-1">
                Upload files or create folders to get started
              </p>
            </div>
          </div>
        ) : (
          entries.map((entry) => (
            <TreeNode
              key={entry.path}
              entry={entry}
              expandedDirs={expandedDirs}
              depth={0}
              onToggleDir={onToggleDir}
              onOpenFile={onOpenFile}
              onEnterDir={onEnterDir}
              onContextMenu={handleContextMenu}
            />
          ))
        )}
      </div>

      {/* Context menu */}
      {contextMenu && (
        <div
          ref={menuRef}
          className="fixed z-50 bg-[var(--color-surface-2)] border border-[var(--color-border)] rounded-md shadow-lg py-1 min-w-[140px]"
          style={{ left: contextMenu.x, top: contextMenu.y }}
        >
          <button
            onClick={handleDelete}
            className="flex items-center gap-2 w-full px-3 py-1.5 text-xs text-[var(--color-error)] hover:bg-[var(--color-surface-3)] transition-colors"
          >
            <Trash2 size={13} />
            Delete
          </button>
        </div>
      )}
    </div>
  );
}
