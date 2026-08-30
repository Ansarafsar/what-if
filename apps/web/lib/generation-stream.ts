const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface StageEvent {
  type: "stage";
  stage: string;
  label: string;
  iteration: number;
  branch_count: number;
}

export interface CompleteEvent {
  type: "complete";
  node_count: number;
  edge_count: number;
  branch_count: number;
  branches: unknown[];
  mock: boolean;
}

export interface ErrorEvent {
  type: "error";
  detail: string;
}

export type GenerationEvent = StageEvent | CompleteEvent | ErrorEvent;

/**
 * Consume the generation SSE stream.
 *
 * `EventSource` cannot issue a POST, so the stream is read off a fetch body -
 * which also lets the caller abort it when the user navigates away.
 */
export async function streamGeneration(
  scenarioId: string,
  onEvent: (event: GenerationEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  const response = await fetch(`${API_URL}/api/v1/scenarios/${scenarioId}/generate/stream`, {
    method: "POST",
    headers: { Accept: "text/event-stream" },
    signal,
  });

  if (!response.ok || !response.body) {
    let detail = `${response.status}`;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : detail;
    } catch {}
    throw new Error(detail);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line; a partial frame stays buffered.
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      const line = frame.split("\n").find((l) => l.startsWith("data: "));
      if (!line) continue;
      try {
        onEvent(JSON.parse(line.slice(6)) as GenerationEvent);
      } catch {
        // A malformed frame should not kill an otherwise working stream.
      }
    }
  }
}
