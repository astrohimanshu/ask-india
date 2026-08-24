// Client for the Ask India API. The streaming endpoint is a POST that returns Server-Sent
// Events, so it is read with fetch + a ReadableStream parser rather than EventSource.

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type ChartSpec = {
  type: "bar" | "line" | "table";
  x: string | null;
  y: string[];
  title: string;
};

export type Citation = {
  dataset: string;
  table: string;
  dataset_version: string | null;
  source: string | null;
  coverage: string | null;
};

export type Answer = {
  status: "answered" | "out_of_scope" | "failed";
  prose: string;
  chart: ChartSpec | null;
  sql: string | null;
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  citation: Citation | null;
  assumptions: string[];
  caveats: string[];
  attempts: number;
  errors: { attempt: number; kind: string; message: string; sql: string | null }[];
  guard: { passed: boolean; numerals: string[]; ungrounded: string[] } | null;
  elapsed_seconds: number;
};

export type Status = {
  node: string;
  label: string;
  datasets?: string[];
  attempt?: number;
  sql?: string;
  last_error?: { kind: string; message: string };
  guard?: { passed: boolean; ungrounded: string[] };
};

export type Dataset = {
  dataset: string;
  table_name: string;
  title: string;
  source_org: string;
  source_url: string | null;
  cadence: string | null;
  coverage_from: string | null;
  coverage_to: string | null;
  current_version: string;
  is_seed: boolean;
  updated_at: string;
};

type Handlers = {
  onStatus: (s: Status) => void;
  onFinal: (a: Answer) => void;
  onError: (message: string) => void;
};

export async function askStream(question: string, h: Handlers, signal?: AbortSignal): Promise<void> {
  const res = await fetch(`${API_URL}/ask/stream`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ question }),
    signal,
  });
  if (!res.ok || !res.body) {
    h.onError(res.status === 429 ? "Too many questions in a minute; please wait a little." : `The API returned ${res.status}.`);
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      dispatch(block, h);
    }
  }
  if (buffer.trim()) dispatch(buffer, h);
}

function dispatch(block: string, h: Handlers) {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trim());
  }
  if (!data.length) return;
  const payload = JSON.parse(data.join("\n"));
  if (event === "status") h.onStatus(payload as Status);
  else if (event === "final") h.onFinal(payload as Answer);
  else if (event === "error") h.onError(String(payload.message ?? "unknown error"));
}

export async function getDatasets(): Promise<Dataset[]> {
  const res = await fetch(`${API_URL}/datasets`, { cache: "no-store" });
  if (!res.ok) throw new Error(`datasets: ${res.status}`);
  return (await res.json()) as Dataset[];
}
