import type { ReactNode } from "react";

/** "Your wealth. *Understood.*" -> the starred words set in italic (the serif's accent). */
export function editorial(text: ReactNode): ReactNode {
  if (typeof text !== "string" || !text.includes("*")) return text;
  return text.split(/(\*[^*]+\*)/g).map((part, i) =>
    part.startsWith("*") && part.endsWith("*") ? <em key={i}>{part.slice(1, -1)}</em> : part);
}
