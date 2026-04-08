import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import "./App.css";

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
};

type FilePayload = {
  mime_type: string;
  data_base64: string;
  name?: string;
};

type ChatApiResponse = {
  response: string;
  history: ChatMessage[];
};

const GEMINI_API_KEY_STORAGE_KEY = "gemini_api_key";

function App() {
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  const [currentInput, setCurrentInput] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [backendPort, setBackendPort] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [apiKey, setApiKey] = useState(
    () => localStorage.getItem(GEMINI_API_KEY_STORAGE_KEY) ?? "",
  );
  const [showSavedFeedback, setShowSavedFeedback] = useState(false);

  useEffect(() => {
    invoke<number>("get_backend_port")
      .then(setBackendPort)
      .catch(() => setBackendPort(null));
  }, []);

  const saveApiKey = () => {
    localStorage.setItem(GEMINI_API_KEY_STORAGE_KEY, apiKey);
    setShowSavedFeedback(true);
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
    if (!currentInput.trim() || !backendPort || loading || !apiKey.trim()) return;

    const userMessage: ChatMessage = { role: "user", content: currentInput };
    const prevHistory = [...chatHistory];

    setChatHistory((history) => [...history, userMessage]);
    setCurrentInput("");
    setLoading(true);

    try {
      let filePayload: FilePayload | undefined;
      if (selectedFile) {
        filePayload = {
          mime_type: selectedFile.type || "application/octet-stream",
          data_base64: await toBase64(selectedFile),
          name: selectedFile.name,
        };
      }

      const response = await fetch(`http://127.0.0.1:${backendPort}/api/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": apiKey.trim(),
        },
        body: JSON.stringify({
          message: userMessage.content,
          history: prevHistory,
          file: filePayload,
        }),
      });

      const data = (await response.json()) as ChatApiResponse | { detail?: string };
      if (!response.ok) {
        throw new Error(
          "detail" in data && data.detail ? data.detail : "Request failed",
        );
      }

      setChatHistory((data as ChatApiResponse).history);
      setSelectedFile(null);
    } catch (error) {
      console.error(error);
      const message =
        error instanceof Error && error.message
          ? `אירעה שגיאה במהלך השיחה: ${error.message}`
          : "אירעה שגיאה במהלך השיחה.";
      setChatHistory((history) => [
        ...history,
        { role: "assistant", content: message },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="app">
      <div className="chat-shell">
        <header className="header">⚖️ סוכן משפטי - דיני עבודה</header>
        <div className="composer">
          <div className="row api-key-row">
            <input
              className="text-input"
              type="password"
              placeholder="Gemini API Key"
              value={apiKey}
              onChange={(event) => {
                setApiKey(event.target.value);
                setShowSavedFeedback(false);
              }}
            />
            <button type="button" onClick={saveApiKey} aria-label="Save API key">
              שמור
            </button>
            {showSavedFeedback && <span className="saved-feedback">✅ נשמר</span>}
          </div>
        </div>
        <main className="messages">
          {chatHistory.map((message, index) => (
            <div
              key={index}
              className={`message ${message.role === "user" ? "user" : "assistant"}`}
            >
              {message.content}
            </div>
          ))}
        </main>
        <footer className="composer">
          <input
            type="file"
            accept=".pdf,.txt,.png,.jpg,.jpeg"
            onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
          />
          <div className="row">
            <input
              className="text-input"
              placeholder="כתוב הוראות או שאלת המשך..."
              value={currentInput}
              onChange={(event) => setCurrentInput(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && void sendMessage()}
            />
            <button
              onClick={() => void sendMessage()}
              disabled={loading || !backendPort || !apiKey.trim()}
            >
              {loading ? "מנתח..." : "שלח"}
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}

export default App;
