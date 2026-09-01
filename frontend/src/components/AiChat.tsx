/**
 * AI sidebar chat — SSE streaming client for /api/v1/ai/chat.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuthStore } from "@/stores/auth";
import { apiBase } from "@/stores/server";
import { Button, Input } from "@/components/ui";
import { Loader2, Send, Sparkles, Wrench } from "lucide-react";

/* -------------------------------- types --------------------------------- */

interface AiStatus {
  module: string;
  mode: string;
  provider_ready: boolean;
}

interface ChatEvent {
  event: "assistant" | "tool_call" | "tool_result" | "final" | "error";
  content?: string;
  name?: string;
  arguments?: Record<string, unknown>;
  result?: string;
  is_error?: boolean;
  message?: string;
}

interface Bubble {
  role: "user" | "assistant";
  content: string;
  toolCalls?: Array<{ name: string; result: string; isError: boolean }>;
}

/* ------------------------------ SSE fetch ------------------------------- */

async function streamChat(
  messages: Array<{ role: string; content: string }>,
  onEvent: (e: ChatEvent) => void,
): Promise<void> {
  const token = useAuthStore.getState().token;
  // Same contract as api.ts: empty base → same-origin (browser), otherwise
  // the persisted desktop server URL.
  const base = apiBase();
  const res = await fetch(`${base}/api/v1/ai/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ messages }),
  });

  if (!res.ok || !res.body) {
    const payload = await res.json().catch(() => null);
    onEvent({
      event: "error",
      message:
        (payload?.detail?.message as string | undefined) ??
        "The assistant is unavailable.",
    });
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const line = part.trim();
      if (line.startsWith("data: ")) {
        try {
          onEvent(JSON.parse(line.slice(6)) as ChatEvent);
        } catch {
          // Skip malformed chunks.
        }
      }
    }
  }
}

/* ------------------------------- sidebar -------------------------------- */

export function AiChat() {
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  const statusQuery = useQuery({
    queryKey: ["ai-status"],
    queryFn: () => api.get<AiStatus>("/ai/status"),
  });

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;

    const history = [
      ...bubbles.map((b) => ({ role: b.role, content: b.content })),
      { role: "user", content: text },
    ];
    setInput("");
    setBusy(true);
    setBubbles((prev) => [...prev, { role: "user", content: text }]);

    const assistant: Bubble = {
      role: "assistant",
      content: "",
      toolCalls: [],
    };

    await streamChat(history, (e) => {
      if (e.event === "assistant" || e.event === "final") {
        assistant.content = assistant.content
          ? `${assistant.content}\n${e.content ?? ""}`
          : (e.content ?? "");
      } else if (e.event === "tool_call") {
        // Tool call chip placeholder — result follows.
        assistant.toolCalls!.push({
          name: e.name ?? "?",
          result: "…",
          isError: false,
        });
      } else if (e.event === "tool_result" && e.name) {
        const chip = assistant.toolCalls!.find(
          (c) => c.name === e.name && c.result === "…",
        );
        if (chip) {
          chip.result = e.result ?? "";
          chip.isError = e.is_error ?? false;
        }
      } else if (e.event === "error") {
        assistant.content =
          assistant.content || `⚠ ${e.message ?? "Something went wrong."}`;
      }
      setBubbles((prev) => [...prev]);
    });

    setBubbles((prev) => [...prev, assistant]);
    setBusy(false);
  };

  const disabled = !statusQuery.data?.provider_ready;

  return (
    <aside className="flex h-full w-[340px] shrink-0 flex-col border-l border-border bg-card">
      <div className="flex h-12 items-center gap-2 border-b border-border px-4">
        <Sparkles className="h-4 w-4 text-primary" />
        <span className="text-sm font-semibold">AI Assistant</span>
        {statusQuery.data && (
          <span className="ml-auto text-[10px] uppercase tracking-wider text-muted-foreground">
            {statusQuery.data.mode}
          </span>
        )}
      </div>

      {disabled && (
        <div className="border-b border-border bg-secondary/30 p-3 text-xs leading-relaxed text-muted-foreground">
          AI is disabled. Set <code className="font-mono">APEX_AI_MODE=byok</code>{" "}
          (OpenAI key) or <code className="font-mono">APEX_AI_MODE=local</code>{" "}
          (Ollama) in the backend <code className="font-mono">.env</code>, then
          restart.
        </div>
      )}

      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        {bubbles.length === 0 && (
          <div className="rounded-md border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
            Ask the assistant to record transactions or pull reports.
            <br />
            Example: <em>"Record a 500,000 cash sale"</em>
          </div>
        )}

        {bubbles.map((b, i) => (
          <div key={i} className={b.role === "user" ? "text-right" : "text-left"}>
            <div
              className={
                b.role === "user"
                  ? "inline-block max-w-[90%] rounded-md bg-primary/15 px-3 py-1.5 text-sm"
                  : "text-sm leading-relaxed"
              }
            >
              {b.content}
            </div>
            {b.toolCalls?.map((c, j) => (
              <div
                key={j}
                className="mt-1.5 flex items-center gap-1.5 rounded-md border border-border bg-background px-2 py-1 text-[11px] text-muted-foreground"
              >
                <Wrench className="h-3 w-3" />
                <span className="font-mono">{c.name}</span>
                {c.isError ? (
                  <span className="text-destructive">error</span>
                ) : (
                  <span className="text-success">ok</span>
                )}
              </div>
            ))}
          </div>
        ))}

        {busy && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" />
            thinking…
          </div>
        )}
      </div>

      <form
        className="flex items-center gap-2 border-t border-border p-3"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={disabled ? "AI disabled" : "Ask…"}
          disabled={disabled || busy}
        />
        <Button type="submit" size="icon" disabled={disabled || busy || !input.trim()}>
          <Send className="h-4 w-4" />
        </Button>
      </form>
    </aside>
  );
}
