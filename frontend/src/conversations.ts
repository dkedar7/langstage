/**
 * Past conversations (gh #232): turning a saved transcript into chat messages, and
 * the small pieces the History menu and the stream hook share.
 */
import type { ChatMessage, ConversationDetail, ToolCall } from "./types";

/**
 * A saved transcript as the messages the chat renders.
 *
 * Ids are positional (`hist-<n>`), so re-reading the same conversation (the
 * read-only view refreshes itself) keeps every bubble's React key and nothing
 * flickers. A tool call with no recorded result is shown as still waiting when the
 * conversation is paused on an approval or a turn is running, and as stopped
 * otherwise.
 */
export function transcriptToMessages(detail: ConversationDetail): ChatMessage[] {
  const waiting = detail.running || detail.interrupt != null;
  return detail.messages.map((entry, i) => {
    const toolCalls: ToolCall[] = (entry.tool_calls ?? []).map((call) =>
      call.status === "pending"
        ? waiting
          ? { id: call.id, name: call.name, args: call.args, status: "running" }
          : {
              id: call.id,
              name: call.name,
              args: call.args,
              status: "error",
              errorMessage: "No result was recorded for this call.",
            }
        : {
            id: call.id,
            name: call.name,
            args: call.args,
            status: call.status,
            result: call.result,
          }
    );
    return {
      id: `hist-${i}`,
      role: entry.role,
      content: entry.content,
      reasoning: entry.reasoning,
      toolCalls,
    };
  });
}

/** "just now", "5 min ago", "3 h ago", "yesterday", then a short date. */
export function relativeTime(iso: string | null, now: number = Date.now()): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const minutes = Math.floor((now - then) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  if (hours < 48) return "yesterday";
  const date = new Date(then);
  const sameYear = date.getFullYear() === new Date(now).getFullYear();
  return date.toLocaleDateString([], {
    month: "short",
    day: "numeric",
    ...(sameYear ? {} : { year: "numeric" }),
  });
}

/** The server's refusal text, whichever shape `detail` came in. */
export async function errorDetail(res: Response): Promise<string> {
  const body = await res.json().catch(() => null);
  const detail = body?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail.message === "string") return detail.message;
  return `request failed (${res.status})`;
}
