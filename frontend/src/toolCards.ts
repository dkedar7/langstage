import type { ChatMessage } from "./types";

/**
 * Which tool card a `tool_start` or `tool_end` frame belongs to (gh #239).
 *
 * A tool call's id is only unique within one model response. The keyless demo
 * agent gives every call the same id, and so do fake models and OpenAI-compatible
 * servers that number ids per response. The chat used to match frames to cards by
 * id across the whole conversation. A later turn that reused an id then got no
 * card, and its result was written into the earlier turn's card.
 *
 * Matching is now limited to the current turn (the messages after the last user
 * message; answering an approval doesn't add one, so a resumed turn is still the
 * same turn), and only a card that is still running can take another `tool_start`:
 * that is the resumed turn re-announcing the call it paused in (#200).
 */

/** Index of the first message of the current turn: the one after the last user message. */
export function currentTurnStart(messages: ChatMessage[]): number {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === "user") return i + 1;
  }
  return 0;
}

/** The most recent card with this id, from `from` on, that passes `ok`. */
function latest(
  messages: ChatMessage[],
  id: string,
  from: number,
  ok: (status: string) => boolean
): [number, number] | null {
  for (let i = messages.length - 1; i >= Math.max(0, from); i--) {
    const calls = messages[i].toolCalls;
    for (let j = calls.length - 1; j >= 0; j--) {
      if (calls[j].id === id && ok(calls[j].status)) return [i, j];
    }
  }
  return null;
}

const running = (status: string) => status === "running";
const any = () => true;

/**
 * The card a `tool_start` re-announces: a running card with the same id in the
 * current turn, or null when the frame starts a new call (and so a new card).
 */
export function findAnnouncedCall(
  messages: ChatMessage[],
  id: string,
  turnStart: number = currentTurnStart(messages)
): [number, number] | null {
  return latest(messages, id, turnStart, running);
}

/**
 * The card a `tool_end` completes: the latest running card with that id in the
 * current turn, else the latest card with that id in the current turn, else a
 * running card with that id in an earlier turn. A finished card from an earlier
 * turn is never overwritten.
 */
export function findEndedCall(
  messages: ChatMessage[],
  id: string,
  turnStart: number = currentTurnStart(messages)
): [number, number] | null {
  return (
    latest(messages, id, turnStart, running) ??
    latest(messages, id, turnStart, any) ??
    latest(messages, id, 0, running)
  );
}
