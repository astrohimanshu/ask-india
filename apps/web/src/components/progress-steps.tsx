"use client";

import type { Status } from "@/lib/api";

export function ProgressSteps({ steps, done }: { steps: Status[]; done: boolean }) {
  if (!steps.length) return null;
  return (
    <ol className="space-y-1 text-sm text-muted-foreground">
      {steps.map((s, i) => {
        const last = i === steps.length - 1;
        return (
          <li key={i} className="flex items-start gap-2">
            <span className={`mt-1.5 size-1.5 shrink-0 rounded-full ${last && !done ? "animate-pulse bg-saffron" : "bg-emerald-600"}`} />
            <span>
              {s.label}
              {s.datasets?.length ? <span className="text-foreground/70"> → {s.datasets[0]}</span> : null}
              {s.attempt && s.attempt > 1 ? <span className="text-foreground/70"> (attempt {s.attempt})</span> : null}
              {s.last_error ? <span className="text-red-700/80"> · {s.last_error.kind}</span> : null}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
