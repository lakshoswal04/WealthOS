"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { useChatThreads } from "@/components/trade/app-shell";
import { ChipRow, Composer, MessageList } from "@/components/trade/chat";
import { Loading } from "@/components/trade/primitives";
import { useAuth } from "@/lib/auth";
import { trade, type ChatMessage } from "@/lib/trade-api";

export default function HomePage() {
  return (
    <Suspense fallback={<Loading />}>
      <Home />
    </Suspense>
  );
}

function Home() {
  const params = useSearchParams();
  const router = useRouter();
  const { user } = useAuth();
  const { refresh, setActiveId } = useChatThreads();
  const threadParam = params.get("thread");
  const threadId = threadParam ? Number(threadParam) : null;

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [pending, setPending] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  useEffect(() => { setActiveId(threadId); return () => setActiveId(null); }, [threadId, setActiveId]);

  // The Prompt Book's "Try it" links arrive with ?prompt=…: prefill, never auto-send.
  const promptParam = params.get("prompt");
  useEffect(() => { if (promptParam) setDraft(promptParam.slice(0, 2000)); }, [promptParam]);

  useEffect(() => {
    setError(null);
    if (!threadId) { setMessages([]); return; }
    // A thread we just created already has its messages on screen.
    if (pending) return;
    setLoading(true);
    trade.thread(threadId)
      .then((t) => setMessages(t.messages ?? []))
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threadId]);

  const send = useCallback(async (text: string) => {
    setError(null);
    setPending(text);
    try {
      let id = threadId;
      if (!id) {
        id = (await trade.newThread()).id;
        router.replace(`/home?thread=${id}`);
      }
      const { message } = await trade.send(id, text);
      const asked: ChatMessage = { id: -Date.now(), role: "user", content: text, cards: [], meta: {}, created_at: null };
      setMessages((m) => [...m, asked, message]);
      void refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPending(null);
    }
  }, [threadId, router, refresh]);

  const firstName = (user?.full_name || user?.email.split("@")[0] || "").split(" ")[0];
  const empty = !threadId && messages.length === 0 && !pending;

  if (empty) {
    return (
      <div className="flex min-h-[calc(100vh-11rem)] flex-col items-center justify-center pb-24">
        <h1 className="display mb-12 text-center text-[clamp(28px,3.4vw,44px)] tracking-tight text-[var(--ink-primary)]">
          What&apos;s moving today{firstName ? `, ${firstName}` : ""}?
        </h1>
        <div className="w-full max-w-[760px]">
          <Composer large onSubmit={send} value={draft} onValueChange={setDraft} autoFocus />
        </div>
        <div className="mt-7"><ChipRow onPick={setDraft} /></div>
        {error && <p className="mt-6 text-small text-[var(--down)]">{error}</p>}
        <p className="mt-16 max-w-xl text-center text-caption leading-relaxed text-[var(--ink-faint)]">
          Answers quote only figures the backend computed, and each one is checked. Prices are delayed about
          fifteen minutes unless Upstox is connected. Trading is paper only, and nothing is placed without your confirmation.
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto flex min-h-[calc(100vh-11rem)] max-w-[820px] flex-col">
      <div className="flex-1 pb-6 pt-2">
        {loading ? <Loading label="Loading conversation" /> : <MessageList messages={messages} pending={pending} />}
        {error && <p className="mt-4 text-small text-[var(--down)]">{error}</p>}
      </div>
      <div className="sticky bottom-0 bg-gradient-to-t from-[var(--surface-0)] via-[var(--surface-0)] to-transparent pb-6 pt-6">
        <Composer onSubmit={send} busy={!!pending} placeholder="Ask a follow-up…" />
      </div>
    </div>
  );
}
