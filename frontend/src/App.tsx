import { useState, useEffect, useCallback } from "react";
import { useAgentStream } from "./hooks/useAgentStream";
import { useFileTree } from "./hooks/useFileTree";
import { useCanvas } from "./hooks/useCanvas";
import { useCron } from "./hooks/useCron";
import { Layout } from "./components/Layout";
import type { AppConfig } from "./types";

const DEFAULT_CONFIG: AppConfig = {
  title: "Cowork Dash",
  subtitle: "AI-Powered Workspace",
  welcome_message: "",
  theme: "auto",
  workspace_name: "",
  agent_name: "Agent",
  icon_url: "",
  save_workflow_prompt: "",
  run_workflow_prompt: "",
  create_workflow_prompt: "",
  show_canvas: true,
  show_files: true,
};

export default function App() {
  const [config, setConfig] = useState<AppConfig>(DEFAULT_CONFIG);
  const [configLoaded, setConfigLoaded] = useState(false);

  // Fetch app config and custom CSS from server
  useEffect(() => {
    fetch("/api/config")
      .then((res) => res.json())
      .then((data) => {
        setConfig(data);
        setConfigLoaded(true);
      })
      .catch(() => {
        setConfigLoaded(true);
      });

    // Load custom CSS theme if configured
    fetch("/api/custom-css")
      .then((res) => {
        if (!res.ok) return;
        return res.text();
      })
      .then((css) => {
        if (!css) return;
        const style = document.createElement("style");
        style.id = "custom-theme";
        style.textContent = css;
        document.head.appendChild(style);
      })
      .catch(() => {});

    return () => {
      const el = document.getElementById("custom-theme");
      if (el) el.remove();
    };
  }, []);

  // Core hooks
  const {
    messages,
    isStreaming,
    interrupt,
    todos,
    tokenUsage,
    usageHistory,
    connectionStatus,
    fileChanges,
    sendMessage,
    respondToInterrupt,
    cancelStream,
    resetSession,
  } = useAgentStream();

  const {
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
  } = useFileTree(fileChanges);

  const { items: canvasItems, deleteItem, clearAll, exportMarkdown } =
    useCanvas(fileChanges);

  const { jobs: cronJobs, createJob, deleteJob, runNow } = useCron();

  const handleSend = useCallback(
    (content: string) => sendMessage(content, { cwd: workspacePath }),
    [sendMessage, workspacePath]
  );

  // Update document title
  useEffect(() => {
    document.title = config.title;
  }, [config.title]);

  if (!configLoaded) {
    return (
      <div className="h-full flex items-center justify-center bg-[var(--color-surface)]">
        <div className="text-[var(--color-text-muted)]">Loading...</div>
      </div>
    );
  }

  return (
    <Layout
      config={config}
      messages={messages}
      todos={todos}
      isStreaming={isStreaming}
      interrupt={interrupt}
      connectionStatus={connectionStatus}
      tokenUsage={tokenUsage}
      usageHistory={usageHistory}
      onSend={handleSend}
      onCancel={cancelStream}
      onRespondInterrupt={respondToInterrupt}
      fileEntries={tree.entries}
      fileLoading={tree.loading}
      expandedDirs={expandedDirs}
      selectedFile={selectedFile}
      workspacePath={workspacePath}
      onToggleDir={toggleDir}
      onOpenFile={openFile}
      onCloseFile={() => setSelectedFile(null)}
      onEnterDir={enterDir}
      onUpload={uploadFile}
      onCreateFolder={createFolder}
      onDeletePath={deletePath}
      canvasItems={canvasItems}
      onDeleteCanvasItem={deleteItem}
      onClearCanvas={clearAll}
      onExportCanvas={exportMarkdown}
      cronJobs={cronJobs}
      onCreateCron={createJob}
      onDeleteCron={deleteJob}
      onRunCron={runNow}
      onNewSession={resetSession}
    />
  );
}
