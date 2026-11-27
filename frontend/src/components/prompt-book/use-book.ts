"use client";

import { useEffect, useState } from "react";
import { account, type PromptBook } from "@/lib/trade-api";

/** The Prompt Book in the reader's chosen language (remembered between visits). */
export function useBook() {
  const [lang, setLangState] = useState<"en" | "hi">("en");
  const [book, setBook] = useState<PromptBook | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const saved = window.localStorage.getItem("wealthos.promptbook.lang");
    if (saved === "hi") setLangState("hi");
  }, []);
  useEffect(() => {
    account.promptBook(lang).then(setBook).catch((e: Error) => setError(e.message));
  }, [lang]);
  const setLang = (l: "en" | "hi") => { window.localStorage.setItem("wealthos.promptbook.lang", l); setLangState(l); };
  return { book, lang, setLang, error };
}
