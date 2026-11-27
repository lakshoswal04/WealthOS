"use client";

import Link from "next/link";
import { useBook } from "@/components/prompt-book/use-book";
import { Icon, Loading } from "@/components/trade/primitives";

export default function PromptBookPage() {
  const { book, lang, setLang, error } = useBook();
  if (error) return <p className="text-body text-[var(--down)]">{error}</p>;
  if (!book) return <Loading />;
  const h = book.hero;
  return (
    <div className="mx-auto max-w-[920px] pb-20">
      <nav className="mb-24 mt-4 text-body-lg uppercase tracking-[0.04em] text-[var(--ink-muted)]">
        <Link href="/home" className="hover:text-[var(--ink-secondary)]">Home</Link>
        <span className="mx-4">/</span><span className="text-[var(--ink-secondary)]">Prompt book</span>
      </nav>
      <div className="mb-8 flex items-center gap-4">
        <span className="font-mono text-body uppercase tracking-[0.3em] text-[var(--ink-secondary)]">{h.eyebrow}</span>
        <span className="h-px w-8 bg-[var(--hairline-strong)]" />
        <button onClick={() => setLang(lang === "en" ? "hi" : "en")}
          className="flex items-center gap-2 rounded-full border border-[var(--hairline-strong)] px-4 py-1.5 text-body text-[var(--ink-secondary)] hover:bg-[var(--surface-3)]">
          <span aria-hidden>文A</span> {lang === "en" ? "हिंदी" : "English"}
        </button>
      </div>
      <h1 className="text-[clamp(44px,7vw,96px)] font-semibold leading-[1.02] tracking-[-0.035em]">
        {h.title_1}<br />{h.title_2a}<em className="font-normal italic">{h.title_2b}</em>{h.title_2c}<br />{h.title_3}
      </h1>
      <p className="mt-10 max-w-xl text-h3 font-normal leading-relaxed text-[var(--ink-secondary)]">{h.lede}</p>

      <ol className="mt-24 border-t border-[var(--hairline)]">
        {book.chapters.map((c) => (
          <li key={c.slug} className="border-b border-[var(--hairline)]">
            <Link href={`/prompt-book/${c.slug}`} className="group grid grid-cols-[100px_1fr_auto] items-center gap-6 py-12">
              <span className="font-mono text-[56px] leading-none text-[var(--ink-faint)] transition-colors group-hover:text-[var(--ink-secondary)]">
                {String(c.number).padStart(2, "0")}
              </span>
              <span>
                <span className="flex items-center gap-2 font-mono text-caption uppercase tracking-[0.2em] text-[var(--ink-muted)]">
                  <Icon name={c.icon} size={14} /> {lang === "en" ? "Chapter" : "अध्याय"} {String(c.number).padStart(2, "0")} · {lang === "en" ? "Level" : "स्तर"} {c.level} · {c.badge}
                </span>
                <span className="mt-2 block text-[28px] font-semibold tracking-tight">{c.title}</span>
                <span className="mt-1.5 block text-body-lg text-[var(--ink-secondary)]">{c.summary}</span>
              </span>
              <span className="text-h2 text-[var(--ink-faint)] transition-all group-hover:translate-x-1 group-hover:text-[var(--ink-primary)]">→</span>
            </Link>
          </li>
        ))}
      </ol>
    </div>
  );
}
