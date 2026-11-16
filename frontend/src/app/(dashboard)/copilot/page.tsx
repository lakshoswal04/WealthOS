"use client";

import { useEffect, useRef, useState } from "react";
import { api, type ChatTurn, type CopilotReply } from "@/lib/api";
import { useApi } from "@/lib/auth";
import { Badge, Button, Card, CardBody, CardHeader, ErrorNote, inputClass } from "@/components/ui";
import { PageHead } from "@/components/ui/shell";

interface Message extends ChatTurn {
  meta?: CopilotReply;
}

const SUGGESTIONS = [
  "Why is my portfolio risky?",
  "Am I diversified?",
  "Why is my health score what it is?",
  "Am I on track for my goals?",
  "Has anything unusual happened?",
  "What will my portfolio be worth in a year?",
];

export default function CopilotPage() {
  const capabilities = useApi(() => api.copilotCapabilities(), []);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  async function send(text: string) {
    const question = text.trim();
    if (!question || busy) return;

    const history: ChatTurn[] = messages.map(({ role, content }) => ({ role, content }));
    setMessages((prev) => [...prev, { role: "user", content: question }]);
    setDraft("");
    setBusy(true);
    setError(null);

    try {
      const reply = await api.chat(question, history);
      setMessages((prev) => [...prev, { role: "assistant", content: reply.answer, meta: reply }]);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHead
        title="Wealth Copilot"
        lede="Ask about your portfolio. Every figure in an answer is checked against the backend measurement that produced it."
        aside={capabilities.data && (
          <Badge tone={capabilities.data.mode === "llm" ? "accent" : "neutral"}>
            {capabilities.data.mode === "llm"
              ? capabilities.data.model
              : "Deterministic explainer"}
          </Badge>
        )}
      />

      <div className="grid gap-5 lg:grid-cols-[1.4fr_0.6fr]">
        <Card className="rise flex min-h-[560px] flex-col">
          <div className="flex-1 space-y-4 overflow-y-auto px-5 py-5">
            {messages.length === 0 && (
              <div className="py-10 text-center">
                <p className="display text-[18px] text-[var(--ink-primary)]">
                  What would you like to understand?
                </p>
                <p className="mx-auto mt-2 max-w-md text-[13px] leading-relaxed text-[var(--ink-secondary)]">
                  The assistant reads only the measurements this platform computed
                  for your portfolio. It will say so when a figure is unavailable,
                  rather than producing one.
                </p>
                <div className="mt-6 flex flex-wrap justify-center gap-2">
                  {SUGGESTIONS.map((suggestion) => (
                    <button
                      key={suggestion}
                      onClick={() => void send(suggestion)}
                      className="rounded-full border border-[var(--hairline)] px-3 py-1.5 text-[12px] text-[var(--ink-secondary)] transition-colors hover:border-[var(--accent-dim)] hover:text-[var(--accent)]"
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((message, index) => (
              <div key={index} className={message.role === "user" ? "flex justify-end" : ""}>
                {message.role === "user" ? (
                  <div className="max-w-[80%] rounded-[12px] rounded-br-[4px] bg-[var(--surface-3)] px-4 py-2.5 text-[13.5px] text-[var(--ink-primary)]">
                    {message.content}
                  </div>
                ) : (
                  <div className="max-w-[92%]">
                    <div className="whitespace-pre-wrap rounded-[12px] rounded-bl-[4px] border border-[var(--hairline)] bg-[var(--surface-1)] px-4 py-3 text-[13.5px] leading-relaxed text-[var(--ink-primary)]">
                      {message.content}
                    </div>
                    {message.meta && <ReplyMeta meta={message.meta} />}
                  </div>
                )}
              </div>
            ))}

            {busy && (
              <div className="flex items-center gap-2.5 text-[13px] text-[var(--ink-secondary)]">
                <span className="h-3 w-3 animate-spin rounded-full border-2 border-[var(--surface-3)] border-t-[var(--accent)]" />
                Reading your portfolio…
              </div>
            )}
            {error && <ErrorNote message={error} />}
            <div ref={endRef} />
          </div>

          <form
            onSubmit={(e) => { e.preventDefault(); void send(draft); }}
            className="flex gap-2 border-t border-[var(--hairline)] p-4"
          >
            <input
              className={inputClass}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Ask about your risk, goals, concentration…"
              disabled={busy}
            />
            <Button type="submit" disabled={busy || !draft.trim()}>Ask</Button>
          </form>
        </Card>

        <div className="space-y-5">
          <Card className="rise">
            <CardHeader title="How it answers" />
            <CardBody>
              <p className="text-[12.5px] leading-relaxed text-[var(--ink-secondary)]">
                {capabilities.data?.grounding}
              </p>
              <ul className="mt-4 space-y-2">
                {(capabilities.data?.limits ?? []).map((limit) => (
                  <li key={limit} className="flex gap-2 text-[12px] leading-relaxed text-[var(--ink-muted)]">
                    <span className="mt-[6px] h-1 w-1 shrink-0 rounded-full bg-[var(--ink-muted)]" />
                    {limit}
                  </li>
                ))}
              </ul>
            </CardBody>
          </Card>

          <Card className="rise">
            <CardHeader title="Tools it can call"
                        subtitle="Read-only. None can change your portfolio." />
            <CardBody>
              <ul className="space-y-2">
                {(capabilities.data?.tools ?? []).map((tool) => (
                  <li key={tool.name}>
                    <code className="text-[11.5px] text-[var(--accent)]">{tool.name}</code>
                    <p className="mt-0.5 text-[11px] leading-snug text-[var(--ink-muted)]">
                      {tool.description.split(". ")[0]}.
                    </p>
                  </li>
                ))}
              </ul>
            </CardBody>
          </Card>
        </div>
      </div>
    </>
  );
}

/** Shows which tools produced the answer and whether every number in it
 *  could be verified — the check is worth surfacing, not burying. */
function ReplyMeta({ meta }: { meta: CopilotReply }) {
  const { grounding } = meta;
  return (
    <div className="mt-2 flex flex-wrap items-center gap-2 px-1">
      <Badge tone={grounding.is_grounded ? "good" : "warning"}>
        {grounding.is_grounded
          ? `All ${grounding.numbers_checked} figures verified`
          : `${grounding.numbers_verified}/${grounding.numbers_checked} figures verified`}
      </Badge>
      {meta.tools_called.map((tool) => (
        <span key={tool} className="rounded-full bg-[var(--surface-3)] px-2 py-[2px] text-[10.5px] text-[var(--ink-muted)]">
          {tool}
        </span>
      ))}
      <span className="text-[10.5px] text-[var(--ink-muted)]">{meta.latency_ms.toFixed(0)}ms</span>
      {!grounding.is_grounded && (
        <span className="w-full text-[11px] text-[var(--warning)]">
          Unverified: {grounding.unverified_numbers.join(", ")} — these could not be
          matched to a backend measurement.
        </span>
      )}
    </div>
  );
}
