"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useBook } from "@/components/prompt-book/use-book";
import { Icon, Loading } from "@/components/trade/primitives";

export default function ChapterPage() {
  const { chapter: slug } = useParams<{ chapter: string }>();
  const { book, lang, setLang, error } = useBook();
  if (error) return <p className="text-body text-[var(--down)]">{error}</p>;
  if (!book) return <Loading />;
  const i = book.chapters.findIndex((c) => c.slug === slug);
  const c = book.chapters[i];
  if (!c) return <p className="text-body text-[var(--ink-muted)]">That chapter does not exist. <Link href="/prompt-book" className="underline">Back to the Prompt Book</Link></p>;
  const nextChapter = book.chapters[i + 1];
  const t = lang === "en"
    ? { principles: "How to ask", examples: "Prompts that work", vague: "Too vague", why: "Why it fails", tryIt: "Try it", next: "Next chapter" }
    : { principles: "कैसे पूछें", examples: "काम करने वाले प्रॉम्प्ट", vague: "बहुत अस्पष्ट", why: "क्यों नहीं चलता", tryIt: "आज़माएँ", next: "अगला अध्याय" };

  return (
    <div className="mx-auto max-w-[880px] pb-20">
      <nav className="mb-16 mt-4 flex items-center justify-between text-body-lg uppercase tracking-[0.04em] text-[var(--ink-muted)]">
        <span>
          <Link href="/home" className="hover:text-[var(--ink-secondary)]">Home</Link><span className="mx-4">/</span>
          <Link href="/prompt-book" className="hover:text-[var(--ink-secondary)]">Prompt book</Link><span className="mx-4">/</span>
          <span className="text-[var(--ink-secondary)]">{String(c.number).padStart(2, "0")}</span>
        </span>
        <button onClick={() => setLang(lang === "en" ? "hi" : "en")}
          className="rounded-full border border-[var(--hairline-strong)] px-4 py-1.5 text-body normal-case text-[var(--ink-secondary)] hover:bg-[var(--surface-3)]">
          {lang === "en" ? "हिंदी" : "English"}
        </button>
      </nav>
      <div className="flex items-center gap-2 font-mono text-caption uppercase tracking-[0.2em] text-[var(--ink-muted)]">
        <Icon name={c.icon} size={14} /> Chapter {String(c.number).padStart(2, "0")} · Level {c.level} · {c.badge}
      </div>
      <h1 className="mt-4 text-[clamp(36px,5vw,60px)] font-semibold leading-[1.05] tracking-[-0.03em]">{c.title}</h1>
      <p className="mt-5 text-h3 font-normal text-[var(--ink-secondary)]">{c.summary}</p>

      <h2 className="mb-5 mt-16 font-mono text-caption uppercase tracking-[0.2em] text-[var(--ink-muted)]">{t.principles}</h2>
      <ol className="space-y-4">
        {c.principles.map((p, n) => (
          <li key={n} className="grid grid-cols-[40px_1fr] text-body-lg leading-relaxed">
            <span className="font-mono text-[var(--ink-faint)]">{String(n + 1).padStart(2, "0")}</span><span>{p}</span>
          </li>
        ))}
      </ol>

      <h2 className="mb-5 mt-16 font-mono text-caption uppercase tracking-[0.2em] text-[var(--ink-muted)]">{t.examples}</h2>
      <ul className="space-y-3">
        {c.examples.map((e) => (
          <li key={e.prompt} className="flex items-center justify-between gap-4 rounded-[var(--radius-lg)] border border-[var(--hairline)] bg-[var(--surface-1)] px-6 py-4">
            <span className="text-body-lg">&ldquo;{e.prompt}&rdquo;</span>
            <Link href={`/home?new=1&prompt=${encodeURIComponent(e.prompt)}`}
              className="shrink-0 rounded-full bg-[var(--action)] px-5 py-2 text-body font-semibold text-[var(--action-ink)] hover:opacity-90">{t.tryIt} →</Link>
          </li>
        ))}
      </ul>

      <h2 className="mb-5 mt-16 font-mono text-caption uppercase tracking-[0.2em] text-[var(--ink-muted)]">{t.vague}</h2>
      <ul className="space-y-3">
        {c.vague.map((v) => (
          <li key={v.prompt} className="rounded-[var(--radius-lg)] border border-dashed border-[var(--hairline-strong)] px-6 py-4">
            <div className="text-body-lg text-[var(--ink-secondary)] line-through decoration-[var(--down)]">&ldquo;{v.prompt}&rdquo;</div>
            <div className="mt-1 text-body text-[var(--ink-muted)]">{t.why}: {v.why}</div>
          </li>
        ))}
      </ul>

      {nextChapter && (
        <Link href={`/prompt-book/${nextChapter.slug}`} className="group mt-20 flex items-center justify-between border-t border-[var(--hairline)] pt-8">
          <span>
            <span className="font-mono text-caption uppercase tracking-[0.2em] text-[var(--ink-muted)]">{t.next}</span>
            <span className="mt-1 block text-h2 font-semibold">{nextChapter.title}</span>
          </span>
          <span className="text-h2 text-[var(--ink-faint)] group-hover:text-[var(--ink-primary)]">→</span>
        </Link>
      )}
    </div>
  );
}
