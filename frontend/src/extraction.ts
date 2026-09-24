import type { ChatMessage } from "./types";

/**
 * Where an `extraction` frame belongs: `[messageIndex, toolCallIndex]`, or null.
 *
 * langstage-core emits `extraction` right AFTER the `tool_end` of the tool it was
 * extracted from, and the frame carries only `tool_name`, not the call's id. The
 * UI used to attach it to a same-name tool call still marked `running`, so once
 * `tool_end` had marked the call done the extraction was dropped (Wave 2 finding;
 * same root cause as the #160 duration work).
 *
 * Match, in order:
 *  1. `targetId`: the frame's own `id` when it has one, otherwise the id of the
 *     `tool_end` that immediately preceded it when that `tool_end` was for the same
 *     tool (the caller records it). This pins the right call even when several calls
 *     to the same tool run in parallel.
 *  2. Fallback, for an extraction with no usable id (for example one that arrives
 *     before its `tool_end`): the most recent same-name call that has no extraction
 *     yet, whatever its status.
 */
export function findExtractionTarget(
  messages: ChatMessage[],
  toolName: string,
  targetId: string | null | undefined
): [number, number] | null {
  if (targetId) {
    for (let i = messages.length - 1; i >= 0; i--) {
      const j = messages[i].toolCalls.findIndex(
        (tc) => tc.id === targetId && tc.name === toolName
      );
      if (j >= 0) return [i, j];
    }
  }
  for (let i = messages.length - 1; i >= 0; i--) {
    const calls = messages[i].toolCalls;
    for (let j = calls.length - 1; j >= 0; j--) {
      if (calls[j].name === toolName && !calls[j].extraction) return [i, j];
    }
  }
  return null;
}

/** The id to prefer for an extraction frame (see {@link findExtractionTarget}). */
export function extractionTargetId(
  frameId: string | null | undefined,
  toolName: string,
  lastEnded: { id: string; name: string } | null
): string | null {
  if (frameId) return frameId;
  if (lastEnded && lastEnded.name === toolName) return lastEnded.id;
  return null;
}
