import { useEffect, useState } from "react";
import { Allotment } from "allotment";
import "allotment/dist/style.css";
import { FolderTree, Palette, ListTodo, AlarmClock, PanelRightClose, PanelRightOpen, Sparkles } from "lucide-react";
import type {
  ChatMessage,
  TodoItem,
  TokenUsage,
  TurnUsage,
  InterruptEventMsg,
  Decision,
  CanvasItem,
  CronJob,
  FileEntry,
  FilePreview,
  ConnectionStatus,
  AppConfig,
} from "../types";
import { ChatPanel } from "./ChatPanel";
import { FileBrowser } from "./FileBrowser";
import { FileViewer } from "./FileViewer";
import { CanvasPanel } from "./CanvasPanel";
import { SchedulesPanel } from "./SchedulesPanel";
import { TodoPanel } from "./TodoPanel";
import { InterruptDialog } from "./InterruptDialog";
import { ThemeToggle } from "./ThemeToggle";
import { StatusBar } from "./StatusBar";

type RightTab = "files" | "canvas" | "tasks" | "schedules";

interface LayoutProps {
  config: AppConfig;
  messages: ChatMessage[];
  todos: TodoItem[];
  isStreaming: boolean;
  interrupt: InterruptEventMsg | null;
  connectionStatus: ConnectionStatus;
  tokenUsage: TokenUsage;
  usageHistory: TurnUsage[];
  onSend: (content: string) => void;
  onCancel: () => void;
  onRespondInterrupt: (decisions: Decision[]) => void;
  fileEntries: FileEntry[];
  fileLoading: boolean;
  expandedDirs: Set<string>;
  selectedFile: FilePreview | null;
  workspacePath: string;
  onToggleDir: (path: string) => void;
  onOpenFile: (path: string) => void;
  onCloseFile: () => void;
  onEnterDir: (path: string) => void;
  onUpload: (file: File) => void;
  onCreateFolder: (name: string) => void;
  onDeletePath: (path: string) => void;
  canvasItems: CanvasItem[];
  onDeleteCanvasItem: (id: string) => void;
  onClearCanvas: () => void;
  onExportCanvas: () => Promise<string>;
  cronJobs: CronJob[];
  onCreateCron: (name: string, cron: string, prompt: string) => Promise<void>;
  onDeleteCron: (id: string) => void;
  onRunCron: (id: string) => void;
  onNewSession: () => void;
}

export function Layout(props: LayoutProps) {
  const [activeTab, setActiveTab] = useState<RightTab>("tasks");
  const [sidebarOpen, setSidebarOpen] = useState(true);

  const showCanvas = props.config.show_canvas;
  const showFiles = props.config.show_files;

  // If the currently active tab gets hidden by config, fall back to Tasks.
  useEffect(() => {
    if (activeTab === "canvas" && !showCanvas) setActiveTab("tasks");
    else if (activeTab === "files" && !showFiles) setActiveTab("tasks");
  }, [activeTab, showCanvas, showFiles]);

  return (
    <div className="h-full flex flex-col bg-[var(--color-surface)]">
      {/* Header */}
      <header data-print-hide className="flex items-center justify-between px-5 h-11 border-b border-[var(--color-border)] bg-[var(--color-surface)]">
        <div className="flex items-center gap-2.5">
          {props.config.icon_url ? (
            <img
              src={props.config.icon_url}
              alt=""
              className="w-6 h-6 rounded-md object-cover"
            />
          ) : (
            <div className="w-6 h-6 rounded-md bg-gradient-to-br from-[var(--color-primary)] to-[var(--color-primary-dark)] flex items-center justify-center">
              <Sparkles size={13} className="text-white" />
            </div>
          )}
          <h1 className="text-sm font-semibold tracking-tight text-[var(--color-text)]">
            {props.config.title}
          </h1>
          {props.config.subtitle && (
            <span className="text-[11px] text-[var(--color-text-muted)] hidden sm:inline border-l border-[var(--color-border)] pl-2.5">
              {props.config.subtitle}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <StatusBar
            connectionStatus={props.connectionStatus}
            isStreaming={props.isStreaming}
            tokenUsage={props.tokenUsage}
            usageHistory={props.usageHistory}
            onNewSession={props.onNewSession}
          />
          <div className="w-px h-4 bg-[var(--color-border)]" />
          <ThemeToggle initialTheme={props.config.theme} />
          <button
            onClick={() => setSidebarOpen((v) => !v)}
            className="p-1 rounded hover:bg-[var(--color-surface-3)] transition-colors"
            title={sidebarOpen ? "Hide sidebar" : "Show sidebar"}
          >
            {sidebarOpen ? (
              <PanelRightClose size={15} className="text-[var(--color-text-secondary)]" />
            ) : (
              <PanelRightOpen size={15} className="text-[var(--color-text-secondary)]" />
            )}
          </button>
        </div>
      </header>

      {/* Main content */}
      <div className="flex-1 overflow-hidden">
        <Allotment defaultSizes={[60, 40]}>
          <Allotment.Pane minSize={300}>
            <ChatPanel
              messages={props.messages}
              isStreaming={props.isStreaming}
              welcomeMessage={props.config.welcome_message}
              agentName={props.config.agent_name}
              iconUrl={props.config.icon_url}
              saveWorkflowPrompt={props.config.save_workflow_prompt}
              runWorkflowPrompt={props.config.run_workflow_prompt}
              createWorkflowPrompt={props.config.create_workflow_prompt}
              onSend={props.onSend}
              onCancel={props.onCancel}
            />
          </Allotment.Pane>

          <Allotment.Pane minSize={250} visible={sidebarOpen}>
            <div data-print-hide className="flex flex-col h-full bg-[var(--color-surface)]">
              {/* Tab bar */}
              <div className="flex items-center h-10 border-b border-[var(--color-border)]">
                <button
                  onClick={() => setActiveTab("tasks")}
                  className={`flex items-center gap-1.5 px-4 h-full text-xs font-medium tracking-wide uppercase transition-colors border-b-2 ${
                    activeTab === "tasks"
                      ? "border-[var(--color-text)] text-[var(--color-text)]"
                      : "border-transparent text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]"
                  }`}
                >
                  <ListTodo size={13} />
                  Tasks
                  {props.todos.length > 0 && (
                    <span className="ml-1 min-w-[16px] h-4 px-1 rounded-full bg-[var(--color-surface-3)] text-[10px] tabular-nums text-[var(--color-text-muted)] inline-flex items-center justify-center">
                      {props.todos.length}
                    </span>
                  )}
                </button>
                {showCanvas && (
                  <button
                    onClick={() => setActiveTab("canvas")}
                    className={`flex items-center gap-1.5 px-4 h-full text-xs font-medium tracking-wide uppercase transition-colors border-b-2 ${
                      activeTab === "canvas"
                        ? "border-[var(--color-text)] text-[var(--color-text)]"
                        : "border-transparent text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]"
                    }`}
                  >
                    <Palette size={13} />
                    Canvas
                    {props.canvasItems.length > 0 && (
                      <span className="ml-1 min-w-[16px] h-4 px-1 rounded-full bg-[var(--color-surface-3)] text-[10px] tabular-nums text-[var(--color-text-muted)] inline-flex items-center justify-center">
                        {props.canvasItems.length}
                      </span>
                    )}
                  </button>
                )}
                {showFiles && (
                  <button
                    onClick={() => setActiveTab("files")}
                    className={`flex items-center gap-1.5 px-4 h-full text-xs font-medium tracking-wide uppercase transition-colors border-b-2 ${
                      activeTab === "files"
                        ? "border-[var(--color-text)] text-[var(--color-text)]"
                        : "border-transparent text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]"
                    }`}
                  >
                    <FolderTree size={13} />
                    Files
                  </button>
                )}
                <button
                  onClick={() => setActiveTab("schedules")}
                  className={`flex items-center gap-1.5 px-4 h-full text-xs font-medium tracking-wide uppercase transition-colors border-b-2 ${
                    activeTab === "schedules"
                      ? "border-[var(--color-text)] text-[var(--color-text)]"
                      : "border-transparent text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]"
                  }`}
                >
                  <AlarmClock size={13} />
                  Schedules
                  {props.cronJobs.length > 0 && (
                    <span className="ml-1 min-w-[16px] h-4 px-1 rounded-full bg-[var(--color-surface-3)] text-[10px] tabular-nums text-[var(--color-text-muted)] inline-flex items-center justify-center">
                      {props.cronJobs.length}
                    </span>
                  )}
                </button>
              </div>

              <div className="flex-1 overflow-hidden">
                {activeTab === "tasks" && (
                  <TodoPanel todos={props.todos} />
                )}
                {activeTab === "canvas" && showCanvas && (
                  <CanvasPanel
                    items={props.canvasItems}
                    onDelete={props.onDeleteCanvasItem}
                    onClearAll={props.onClearCanvas}
                    onExport={props.onExportCanvas}
                  />
                )}
                {activeTab === "files" && showFiles && (
                  props.selectedFile ? (
                    <FileViewer
                      file={props.selectedFile}
                      onClose={props.onCloseFile}
                    />
                  ) : (
                    <FileBrowser
                      entries={props.fileEntries}
                      expandedDirs={props.expandedDirs}
                      loading={props.fileLoading}
                      workspacePath={props.workspacePath}
                      onToggleDir={props.onToggleDir}
                      onOpenFile={props.onOpenFile}
                      onEnterDir={props.onEnterDir}
                      onUpload={props.onUpload}
                      onCreateFolder={props.onCreateFolder}
                      onDelete={props.onDeletePath}
                    />
                  )
                )}
                {activeTab === "schedules" && (
                  <SchedulesPanel
                    jobs={props.cronJobs}
                    onCreate={props.onCreateCron}
                    onDelete={props.onDeleteCron}
                    onRun={props.onRunCron}
                  />
                )}
              </div>
            </div>
          </Allotment.Pane>
        </Allotment>
      </div>

      {props.interrupt && (
        <InterruptDialog
          interrupt={props.interrupt}
          onRespond={props.onRespondInterrupt}
        />
      )}
    </div>
  );
}
