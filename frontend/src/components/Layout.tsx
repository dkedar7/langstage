import { useEffect, useState } from "react";
import { Allotment } from "allotment";
import "allotment/dist/style.css";
import { FolderTree, Palette, ListTodo, AlarmClock, KanbanSquare, PanelRightClose, PanelRightOpen, Sparkles } from "lucide-react";
import type {
  ChatMessage,
  TodoItem,
  TokenUsage,
  TurnUsage,
  InterruptEventMsg,
  Decision,
  CanvasItem,
  CronJob,
  Task,
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
import { TaskBoard } from "./TaskBoard";
import { TodoPanel } from "./TodoPanel";
import { InterruptDialog } from "./InterruptDialog";
import { ThemeToggle } from "./ThemeToggle";
import { StatusBar } from "./StatusBar";

type RightTab = "files" | "canvas" | "tasks" | "board" | "schedules";

function TabButton({
  active,
  onClick,
  icon: Icon,
  label,
  count,
}: {
  active: boolean;
  onClick: () => void;
  icon: typeof FolderTree;
  label: string;
  count?: number;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-1.5 flex-shrink-0 px-2.5 h-7 rounded-md text-[13px] font-medium whitespace-nowrap transition-colors ${
        active
          ? "bg-[var(--color-surface-3)] text-[var(--color-text)]"
          : "text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-3)]"
      }`}
    >
      <Icon size={14} />
      {label}
      {count != null && count > 0 && (
        <span className="min-w-[16px] h-4 px-1 rounded-full bg-[var(--color-card)] border border-[var(--color-border)] text-[10px] tabular-nums text-[var(--color-text-muted)] inline-flex items-center justify-center">
          {count}
        </span>
      )}
    </button>
  );
}

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
  tasks: Task[];
  onCreateTask: (prompt: string, title?: string) => Promise<void>;
  onCancelTask: (id: string) => void;
  onRetryTask: (id: string) => void;
  onNewSession: () => void;
}

export function Layout(props: LayoutProps) {
  const [activeTab, setActiveTab] = useState<RightTab>("tasks");
  const [sidebarOpen, setSidebarOpen] = useState(true);

  const showCanvas = props.config.show_canvas;
  const showFiles = props.config.show_files;

  // If the currently active tab gets hidden by config, fall back to Plan.
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
            <div data-print-hide className="flex flex-col h-full bg-[var(--color-panel)]">
              {/* Tab bar — scrollable pills so it degrades gracefully when narrow */}
              <div className="flex items-center gap-1 px-2 h-11 border-b border-[var(--color-border)] overflow-x-auto">
                <TabButton
                  active={activeTab === "tasks"}
                  onClick={() => setActiveTab("tasks")}
                  icon={ListTodo}
                  label="Plan"
                  count={props.todos.length}
                />
                {showCanvas && (
                  <TabButton
                    active={activeTab === "canvas"}
                    onClick={() => setActiveTab("canvas")}
                    icon={Palette}
                    label="Canvas"
                    count={props.canvasItems.length}
                  />
                )}
                {showFiles && (
                  <TabButton
                    active={activeTab === "files"}
                    onClick={() => setActiveTab("files")}
                    icon={FolderTree}
                    label="Files"
                  />
                )}
                <TabButton
                  active={activeTab === "schedules"}
                  onClick={() => setActiveTab("schedules")}
                  icon={AlarmClock}
                  label="Schedules"
                  count={props.cronJobs.length}
                />
                <TabButton
                  active={activeTab === "board"}
                  onClick={() => setActiveTab("board")}
                  icon={KanbanSquare}
                  label="Board"
                  count={props.tasks.filter(
                    (t) => t.state === "queued" || t.state === "ongoing" || t.state === "review_needed"
                  ).length}
                />
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
                {activeTab === "board" && (
                  <TaskBoard
                    tasks={props.tasks}
                    onCreate={props.onCreateTask}
                    onCancel={props.onCancelTask}
                    onRetry={props.onRetryTask}
                  />
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
