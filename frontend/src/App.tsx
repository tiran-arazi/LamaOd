import {
  AssistantRuntimeProvider,
  useLocalRuntime,
} from "@assistant-ui/react";
import { Thread } from "@assistant-ui/react-ui";
import "@assistant-ui/react-ui/styles/index.css";
import { ExplorerToolUIs } from "./components/ExplorerToolUIs";
import { explorerChatAdapter } from "./runtime/ExplorerChatAdapter";

function ExplorerRuntimeProvider({ children }: { children: React.ReactNode }) {
  const runtime = useLocalRuntime(explorerChatAdapter);
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ExplorerToolUIs />
      {children}
    </AssistantRuntimeProvider>
  );
}

export default function App() {
  return (
    <ExplorerRuntimeProvider>
      <div className="app-shell">
        <header className="app-header">
          <h1>AI Data Explorer</h1>
          <p className="app-sub">
            ArcGIS REST + local Ollama · Set <code>ARCGIS_CATALOG_URL</code> when you move to a closed
            network
          </p>
        </header>
        <main className="app-main">
          <Thread />
        </main>
      </div>
    </ExplorerRuntimeProvider>
  );
}
