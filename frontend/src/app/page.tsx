"use client";

import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  meta?: string;
};

type ChatResponse = {
  response: string;
  session_id: string;
  provider: string;
  mode: "private" | "public";
  intent: string;
};

const API_BASE =
  process.env.NEXT_PUBLIC_AKASHI_API_URL ?? "http://127.0.0.1:8000";

const suggestions = [
  "Bugün yaptığımız Akashi sistemini özetle.",
  "Lamborghini Egoista hakkında konuşalım.",
  "Bunu daha profesyonel bir metne dönüştür.",
];

function createId() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export default function Home() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      role: "assistant",
      content:
        "Tekrar hoş geldin Metin. Yerel sistem hazır. Ne üzerinde çalışıyoruz?",
      meta: "AKASHI · LOCAL",
    },
  ]);

  const [input, setInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [backendOnline, setBackendOnline] = useState(false);
  const messageListRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const checkBackend = async () => {
      try {
        const response = await fetch(`${API_BASE}/health`, {
          cache: "no-store",
        });
        setBackendOnline(response.ok);
      } catch {
        setBackendOnline(false);
      }
    };

    checkBackend();
  }, []);

  useEffect(() => {
    messageListRef.current?.scrollTo({
      top: messageListRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, isSending]);

  async function sendMessage(messageOverride?: string) {
    const text = (messageOverride ?? input).trim();

    if (!text || isSending) {
      return;
    }

    setInput("");
    setIsSending(true);

    setMessages((current) => [
      ...current,
      {
        id: createId(),
        role: "user",
        content: text,
      },
    ]);

    try {
      const response = await fetch(`${API_BASE}/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json; charset=utf-8",
        },
        body: JSON.stringify({
          message: text,
          session_id: "metin-main",
          mode: "private",
        }),
      });

      if (!response.ok) {
        throw new Error(`Backend ${response.status} hatası verdi.`);
      }

      const data = (await response.json()) as ChatResponse;

      setBackendOnline(true);
      setMessages((current) => [
        ...current,
        {
          id: createId(),
          role: "assistant",
          content: data.response,
          meta: `${data.provider.toUpperCase()} · ${data.intent.toUpperCase()}`,
        },
      ]);
    } catch (error) {
      setBackendOnline(false);

      const detail =
        error instanceof Error ? error.message : "Bilinmeyen bağlantı hatası.";

      setMessages((current) => [
        ...current,
        {
          id: createId(),
          role: "assistant",
          content:
            "Akashi backend bağlantısına şu anda ulaşamıyorum. Backend terminalinin açık olduğundan emin ol.",
          meta: detail,
        },
      ]);
    } finally {
      setIsSending(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void sendMessage();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendMessage();
    }
  }

  return (
    <main className="app-shell">
      <aside className="icon-rail">
        <div className="monogram">A</div>

        <nav className="rail-nav" aria-label="Ana menü">
          <button className="rail-button active" title="Sohbet">
            ◇
          </button>
          <button className="rail-button" title="Görseller">
            ▧
          </button>
          <button className="rail-button" title="Hafıza">
            ◎
          </button>
        </nav>

        <div className="rail-bottom">ABS</div>
      </aside>

      <aside className="sidebar">
        <div>
          <p className="eyebrow">PROJECT ABSOLUTE</p>
          <h1>AKASHI</h1>
          <p className="sidebar-description">
            Yerel, kişisel ve sana ait yapay zekâ sistemi.
          </p>
        </div>

        <button
          className="new-chat"
          onClick={() =>
            setMessages([
              {
                id: createId(),
                role: "assistant",
                content: "Yeni oturum hazır. Nereden başlıyoruz?",
                meta: "AKASHI · LOCAL",
              },
            ])
          }
        >
          <span>＋</span>
          Yeni sohbet
        </button>

        <div className="sidebar-section">
          <p className="sidebar-label">SİSTEM</p>

          <div className="system-card">
            <div>
              <span
                className={`status-dot ${backendOnline ? "online" : "offline"}`}
              />
              <strong>
                {backendOnline ? "Backend çevrimiçi" : "Backend bağlantısız"}
              </strong>
            </div>
            <small>Ollama · qwen3:8b</small>
          </div>

          <div className="system-card muted">
            <div>
              <span className="status-dot online" />
              <strong>Görsel motoru hazır</strong>
            </div>
            <small>ComfyUI · SDXL</small>
          </div>
        </div>

        <div className="profile-card">
          <div className="profile-avatar">M</div>
          <div>
            <strong>Metin</strong>
            <span>Owner Mode</span>
          </div>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">ACTIVE SESSION</p>
            <h2>Akashi Local</h2>
          </div>

          <div className="mode-badge">
            <span className="status-dot online" />
            PRIVATE / LOCAL
          </div>
        </header>

        <div className="chat-area" ref={messageListRef}>
          <div className="conversation">
            {messages.map((message) => (
              <article
                key={message.id}
                className={`message-row ${message.role}`}
              >
                <div className="message-avatar">
                  {message.role === "assistant" ? "A" : "M"}
                </div>

                <div className="message-content">
                  <div className="message-heading">
                    <strong>
                      {message.role === "assistant" ? "Akashi" : "Metin"}
                    </strong>
                    {message.meta && <span>{message.meta}</span>}
                  </div>

                  <p>{message.content}</p>
                </div>
              </article>
            ))}

            {isSending && (
              <article className="message-row assistant">
                <div className="message-avatar">A</div>
                <div className="message-content">
                  <div className="message-heading">
                    <strong>Akashi</strong>
                    <span>THINKING</span>
                  </div>
                  <div className="typing">
                    <i />
                    <i />
                    <i />
                  </div>
                </div>
              </article>
            )}
          </div>
        </div>

        <div className="composer-zone">
          {messages.length <= 1 && (
            <div className="suggestions">
              {suggestions.map((suggestion) => (
                <button
                  key={suggestion}
                  onClick={() => void sendMessage(suggestion)}
                >
                  {suggestion}
                </button>
              ))}
            </div>
          )}

          <form className="composer" onSubmit={handleSubmit}>
            <button
              type="button"
              className="attach-button"
              title="Görsel yükleme sonraki aşamada"
              disabled
            >
              ＋
            </button>

            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Akashi'ye bir şey söyle..."
              rows={1}
            />

            <button
              className="send-button"
              type="submit"
              disabled={!input.trim() || isSending}
              aria-label="Gönder"
            >
              ↑
            </button>
          </form>

          <p className="composer-note">
            Enter gönderir · Shift + Enter yeni satır açar · Sistem yerel çalışır
          </p>
        </div>
      </section>
    </main>
  );
}
