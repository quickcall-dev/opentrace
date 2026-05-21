import type { Message } from "./types";
import {
  CODEX_TAGS,
  COMPACTION_SIG,
  INTERRUPTION_CLAUDE_SIG,
  INTERRUPTION_CODEX_SIG,
} from "./constants";

export function isCompaction(m: Message): boolean {
  return m.msg_type === "user" && !!m.content && m.content.startsWith(COMPACTION_SIG);
}

export function isInterruption(m: Message): boolean {
  return (
    (m.msg_type === "tool_result" &&
      !!m.tool_output &&
      m.tool_output.includes(INTERRUPTION_CLAUDE_SIG)) ||
    (m.msg_type === "user" && !!m.content && m.content.startsWith(INTERRUPTION_CODEX_SIG))
  );
}

export interface TaggedSection {
  tag: string;
  body: string;
  isCodex: boolean;
}

export function parseTaggedSections(text: string): {
  plain: string;
  sections: TaggedSection[];
} {
  const tagRegex = /<([a-zA-Z_][a-zA-Z0-9_ -]*)>([\s\S]*?)<\/\1>/g;
  const sections: TaggedSection[] = [];
  let lastIndex = 0;
  const plainParts: string[] = [];
  let match: RegExpExecArray | null;
  while ((match = tagRegex.exec(text)) !== null) {
    if (match.index > lastIndex) plainParts.push(text.slice(lastIndex, match.index));
    const tagName = match[1].trim();
    const isCodex =
      CODEX_TAGS.has(tagName) || CODEX_TAGS.has(tagName.replace(/\s+/g, "_"));
    sections.push({ tag: tagName, body: match[2].trim(), isCodex });
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) plainParts.push(text.slice(lastIndex));
  return { plain: plainParts.join("").trim(), sections };
}

export function stripTags(text: string): string {
  return text
    .replace(/<([a-zA-Z_][a-zA-Z0-9_ -]*)>[\s\S]*?<\/\1>/g, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

/** Filter messages, removing progress, empty tool_calls, and consecutive duplicates */
export function filterVisibleMessages(msgs: Message[]): Message[] {
  const filtered = msgs.filter((m) => {
    if (m.msg_type === "progress") return false;
    if (m.msg_type === "tool_call" && !m.content && !m.tool_name) return false;
    return true;
  });
  // Dedup consecutive messages with same content + type
  return filtered.filter((m, i) => {
    if (i === 0) return true;
    const prev = filtered[i - 1];
    return !(
      m.msg_type === prev.msg_type &&
      m.content != null &&
      m.content === prev.content &&
      m.tool_name === prev.tool_name
    );
  });
}
