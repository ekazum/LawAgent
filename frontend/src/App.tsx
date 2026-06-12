import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import Markdown from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import DocumentsPanel from "./DocumentsPanel";
import { API_URL } from "./config";
import "./App.css";

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
};

type ConversationInfo = {
  id: number;
  title: string;
  updated_at: string;
};

type TemplateInfo = {
  key: string;
  label: string;
  description: string;
};

type FilePayload = {
  mime_type: string;
  data_base64: string;
  name?: string;
};

type StreamEvent =
  | { type: "start"; conversation_id: number | null }
  | { type: "status"; text: string }
  | { type: "delta"; text: string }
  | { type: "error"; detail: string }
  | { type: "done"; conversation_id: number | null };

const API_KEY_STORAGE_KEY = "anthropic_api_key";

function extractText(node: ReactNode): string | null {
  if (typeof node === "string") return node;
  if (Array.isArray(node) && node.length === 1 && typeof node[0] === "string") {
    return node[0];
  }
  return null;
}

function AssistantContent({ text }: { text: string }) {
  return (
    <Markdown
      remarkPlugins={[remarkGfm, remarkBreaks]}
      components={{
        a: ({ href, children }) => {
          let label: ReactNode = children;
          const childText = extractText(children);
          // Bare autolinked URL — show the site name instead of the full address.
          if (href && childText && childText.replace(/\/$/, "") === href.replace(/\/$/, "")) {
            try {
              label = new URL(href).hostname.replace(/^www\./, "");
            } catch {
              // keep original label
            }
          }
          return (
            <a href={href} target="_blank" rel="noopener noreferrer" title={href}>
              {label}
            </a>
          );
        },
      }}
    >
      {text}
    </Markdown>
  );
}

function App() {
  const [conversations, setConversations] = useState<ConversationInfo[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  const [templates, setTemplates] = useState<TemplateInfo[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState<string | null>(null);
  const [currentInput, setCurrentInput] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [statusText, setStatusText] = useState<string | null>(null);
  const [streamingText, setStreamingText] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [view, setView] = useState<"chat" | "documents">("chat");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [apiKey, setApiKey] = useState(
    () => localStorage.getItem(API_KEY_STORAGE_KEY) ?? "",
  );
  const [showSavedFeedback, setShowSavedFeedback] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  const refreshConversations = useCallback(async () => {
    try {
      const response = await fetch(`${API_URL}/api/conversations`);
      if (response.ok) {
        setConversations((await response.json()) as ConversationInfo[]);
      }
    } catch {
      // DB unavailable — sidebar stays empty, chat still works statelessly.
    }
  }, []);

  useEffect(() => {
    void refreshConversations();
  }, [refreshConversations]);

  useEffect(() => {
    fetch(`${API_URL}/api/templates`)
      .then((response) => response.json())
      .then((data) => setTemplates(data as TemplateInfo[]))
      .catch(() => {});
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatHistory, streamingText, statusText]);

  const saveApiKey = () => {
    localStorage.setItem(API_KEY_STORAGE_KEY, apiKey);
    setShowSavedFeedback(true);
  };

  const newConversation = () => {
    if (loading) return;
    setActiveId(null);
    setChatHistory([]);
    setSelectedTemplate(null);
    setSidebarOpen(false);
  };

  const openConversation = async (id: number) => {
    if (loading) return;
    setActiveId(id);
    setSelectedTemplate(null);
    setView("chat");
    setSidebarOpen(false);
    try {
      const response = await fetch(`${API_URL}/api/conversations/${id}/messages`);
      setChatHistory(response.ok ? ((await response.json()) as ChatMessage[]) : []);
    } catch {
      setChatHistory([]);
    }
  };

  const removeConversation = async (id: number) => {
    if (loading) return;
    try {
      await fetch(`${API_URL}/api/conversations/${id}`, { method: "DELETE" });
    } catch {
      // ignore
    }
    if (id === activeId) {
      newConversation();
    }
    void refreshConversations();
  };

  const toBase64 = (file: File) =>
    new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const result = String(reader.result || "");
        resolve(result.split(",")[1] || "");
      };
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });

  const sendMessage = async () => {
    if (!currentInput.trim() || loading) return;

    const userMessage: ChatMessage = { role: "user", content: currentInput };
    const messageText = currentInput;
    const template = selectedTemplate;

    setChatHistory((history) => [...history, userMessage]);
    setCurrentInput("");
    setSelectedTemplate(null);
    setLoading(true);
    setStreamingText(null);
    setStatusText(null);

    let accumulated = "";

    const finishWith = (text: string) => {
      setChatHistory((history) => [...history, { role: "assistant", content: text }]);
      setStreamingText(null);
      setStatusText(null);
    };

    try {
      let filePayload: FilePayload | undefined;
      if (selectedFile) {
        filePayload = {
          mime_type: selectedFile.type || "application/octet-stream",
          data_base64: await toBase64(selectedFile),
          name: selectedFile.name,
        };
      }

      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };
      if (apiKey.trim()) {
        headers["X-API-Key"] = apiKey.trim();
      }

      const response = await fetch(`${API_URL}/api/chat`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          message: messageText,
          conversation_id: activeId,
          template,
          file: filePayload,
        }),
      });

      if (!response.ok || !response.body) {
        const data = (await response.json().catch(() => null)) as {
          detail?: string;
        } | null;
        throw new Error(data?.detail ?? "Request failed");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let finished = false;

      const handleEvent = (event: StreamEvent) => {
        if (event.type === "start") {
          if (event.conversation_id !== null) setActiveId(event.conversation_id);
        } else if (event.type === "status") {
          setStatusText(event.text);
        } else if (event.type === "delta") {
          setStatusText(null);
          accumulated += event.text;
          setStreamingText(accumulated);
        } else if (event.type === "error") {
          finished = true;
          finishWith(accumulated ? accumulated : `⚠️ ${event.detail}`);
          if (accumulated) {
            setChatHistory((history) => [
              ...history,
              { role: "assistant", content: `⚠️ ${event.detail}` },
            ]);
          }
        } else if (event.type === "done") {
          finished = true;
          finishWith(accumulated || "לא התקבלה תשובה מהמודל.");
        }
      };

      while (!finished) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let separator = buffer.indexOf("\n\n");
        while (separator >= 0) {
          const rawEvent = buffer.slice(0, separator);
          buffer = buffer.slice(separator + 2);
          for (const line of rawEvent.split("\n")) {
            if (line.startsWith("data:")) {
              handleEvent(JSON.parse(line.slice(5)) as StreamEvent);
            }
          }
          separator = buffer.indexOf("\n\n");
        }
      }

      if (!finished) {
        finishWith(accumulated || "החיבור לשרת נותק באמצע התשובה.");
      }

      setSelectedFile(null);
      void refreshConversations();
    } catch (error) {
      console.error(error);
      const message =
        error instanceof Error && error.message
          ? `אירעה שגיאה במהלך השיחה: ${error.message}`
          : "אירעה שגיאה במהלך השיחה.";
      finishWith(message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="app">
      <div className="layout">
        {sidebarOpen && (
          <div className="backdrop" onClick={() => setSidebarOpen(false)} />
        )}
        <aside className={`sidebar ${sidebarOpen ? "open" : ""}`}>
          <button className="new-chat" onClick={newConversation} disabled={loading}>
            + שיחה חדשה
          </button>
          <div className="conv-list">
            {conversations.map((conversation) => (
              <div
                key={conversation.id}
                className={`conv-item ${conversation.id === activeId ? "active" : ""}`}
                onClick={() => void openConversation(conversation.id)}
              >
                <span className="conv-title">{conversation.title}</span>
                <button
                  className="conv-delete"
                  aria-label={`מחק את ${conversation.title}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    void removeConversation(conversation.id);
                  }}
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        </aside>
        <div className="chat-shell">
          <header className="header">
            <button
              className="menu-btn"
              aria-label="שיחות קודמות"
              onClick={() => setSidebarOpen((open) => !open)}
            >
              ☰
            </button>
            <span className="header-title">⚖️ סוכן משפטי - דיני עבודה</span>
            <nav className="tabs">
              <button
                className={`tab ${view === "chat" ? "active" : ""}`}
                onClick={() => setView("chat")}
              >
                צ'אט
              </button>
              <button
                className={`tab ${view === "documents" ? "active" : ""}`}
                onClick={() => setView("documents")}
              >
                מאגר ידע
              </button>
            </nav>
          </header>
          <div className="composer">
            <div className="row api-key-row">
              <input
                className="text-input"
                type="password"
                placeholder="Anthropic API Key (לא נדרש אם מוגדר בשרת)"
                value={apiKey}
                onFocus={() => setShowSavedFeedback(false)}
                onChange={(event) => {
                  setApiKey(event.target.value);
                  setShowSavedFeedback(false);
                }}
              />
              <button type="button" onClick={saveApiKey} aria-label="שמור מפתח API">
                שמור
              </button>
              {showSavedFeedback && <span className="saved-feedback">✅ נשמר</span>}
            </div>
          </div>
          {view === "documents" && <DocumentsPanel apiKey={apiKey} />}
          {view === "chat" && (
            <>
              <main className="messages">
                {chatHistory.map((message, index) => (
                  <div
                    key={index}
                    className={`message ${message.role === "user" ? "user" : "assistant"}`}
                  >
                    {message.role === "assistant" ? (
                      <AssistantContent text={message.content} />
                    ) : (
                      message.content
                    )}
                  </div>
                ))}
                {streamingText !== null && (
                  <div className="message assistant">
                    <AssistantContent text={streamingText} />
                  </div>
                )}
                {statusText && <div className="status-line">{statusText}</div>}
                <div ref={messagesEndRef} />
              </main>
              <footer className="composer">
                <div className="template-chips">
                  {templates.map((template) => (
                    <button
                      key={template.key}
                      className={`chip ${selectedTemplate === template.key ? "active" : ""}`}
                      title={template.description}
                      onClick={() =>
                        setSelectedTemplate((current) =>
                          current === template.key ? null : template.key,
                        )
                      }
                    >
                      {template.label}
                    </button>
                  ))}
                </div>
                <input
                  type="file"
                  accept=".pdf,.txt,.png,.jpg,.jpeg"
                  onChange={(event) =>
                    setSelectedFile(event.target.files?.[0] ?? null)
                  }
                />
                <div className="row">
                  <input
                    className="text-input"
                    placeholder={
                      selectedTemplate
                        ? "פרט את עובדות המקרה והחומר הרלוונטי..."
                        : "כתוב הוראות או שאלת המשך..."
                    }
                    value={currentInput}
                    onChange={(event) => setCurrentInput(event.target.value)}
                    onKeyDown={(event) => event.key === "Enter" && void sendMessage()}
                  />
                  <button onClick={() => void sendMessage()} disabled={loading}>
                    {loading ? "מנתח..." : "שלח"}
                  </button>
                </div>
              </footer>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default App;
