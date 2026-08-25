"use client";

import { Badge } from "@/components/ui/badge";
import { ResultChart } from "@/components/result-chart";
import type { Answer } from "@/lib/api";

const STATUS: Record<Answer["status"], { label: string; className: string }> = {
  answered: { label: "Grounded answer", className: "bg-emerald-600/10 text-emerald-800 dark:text-emerald-300" },
  out_of_scope: { label: "Outside the catalogue", className: "bg-amber-500/15 text-amber-800 dark:text-amber-300" },
  failed: { label: "Could not answer", className: "bg-red-600/10 text-red-800 dark:text-red-300" },
  verdict: { label: "Claim checked", className: "bg-sky-600/10 text-sky-800 dark:text-sky-300" },
  unverifiable: { label: "Claim not checkable", className: "bg-amber-500/15 text-amber-800 dark:text-amber-300" },
};

const VERDICT_STYLE: Record<NonNullable<Answer["verdict"]>["verdict"], string> = {
  Supported: "bg-emerald-600 text-white",
  Misleading: "bg-amber-500 text-white",
  Contradicted: "bg-red-600 text-white",
  Unverifiable: "bg-zinc-500 text-white",
};

function num(v: number | null): string {
  return v === null ? "—" : Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(v);
}

function VerdictPanel({ answer }: { answer: Answer }) {
  const v = answer.verdict;
  if (!v) return null;
  const hasFigures = v.claimed !== null || v.actual !== null;
  return (
    <div className="mb-4 rounded-lg border border-border/70 bg-muted/30 p-4">
      <div className="flex flex-wrap items-center gap-3">
        <span className={`rounded-md px-2.5 py-1 font-display text-lg font-semibold ${VERDICT_STYLE[v.verdict]}`}>{v.verdict}</span>
        {answer.claim ? <span className="text-sm text-muted-foreground">“{answer.claim}”</span> : null}
      </div>
      {hasFigures ? (
        <dl className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
          <div><dt className="text-xs uppercase tracking-wide text-muted-foreground">Claimed</dt><dd className="font-mono text-lg tabular-nums">{num(v.claimed)}</dd></div>
          <div><dt className="text-xs uppercase tracking-wide text-muted-foreground">In the data</dt><dd className="font-mono text-lg tabular-nums">{num(v.actual)}</dd></div>
          {v.relative_error !== null && Number.isFinite(v.relative_error) ? (
            <div><dt className="text-xs uppercase tracking-wide text-muted-foreground">Difference</dt><dd className="font-mono text-lg tabular-nums">{(v.relative_error * 100).toFixed(1)}%</dd></div>
          ) : null}
        </dl>
      ) : null}
      {v.tolerance ? (
        <p className="mt-2 text-xs text-muted-foreground">
          Bands: Supported within ±{Math.round(v.tolerance.supported_within * 100)}% of the official figure; Misleading when the direction is right but the figure is off by more than that, up to a factor of {v.tolerance.misleading_factor}; Contradicted otherwise.
        </p>
      ) : null}
    </div>
  );
}

function fmt(v: unknown, column: string): string {
  if (v === null || v === undefined) return "—";
  const n = typeof v === "number" ? v : typeof v === "string" && /^-?\d+(\.\d+)?$/.test(v) ? Number(v) : null;
  if (n === null) return String(v);
  const looksLikeYear = /year|period/i.test(column) && Number.isInteger(n) && n >= 1800 && n <= 2200;
  return looksLikeYear ? String(n) : Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 }).format(n);
}

export function AnswerCard({ answer }: { answer: Answer }) {
  const s = STATUS[answer.status];
  const seed = answer.citation?.dataset_version?.startsWith("seed-");
  return (
    <article className="rounded-xl border border-border/70 bg-card p-5 shadow-sm">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Badge className={s.className} variant="secondary">{s.label}</Badge>
        {answer.guard ? (
          <Badge variant="outline" className={answer.guard.passed ? "" : "border-red-500 text-red-700"}>
            {answer.guard.passed ? `every number traced to the rows` : `guard rejected: ${answer.guard.ungrounded.join(", ")}`}
          </Badge>
        ) : null}
        {seed ? <Badge variant="destructive">seed fixture, not real data</Badge> : null}
        <span className="ml-auto text-xs text-muted-foreground">{answer.elapsed_seconds.toFixed(1)} s · {answer.attempts || 0} attempt{answer.attempts === 1 ? "" : "s"}</span>
      </div>
      {answer.mode === "claim" ? <VerdictPanel answer={answer} /> : null}
      <p className="font-display text-lg leading-relaxed">{answer.prose}</p>
      {answer.chart ? <ResultChart spec={answer.chart} rows={answer.rows} /> : null}
      {answer.citation ? (
        <p className="mt-3 text-sm text-muted-foreground">
          Source: <span className="text-foreground">{answer.citation.dataset}</span>
          {answer.citation.coverage ? ` · covers ${answer.citation.coverage}` : ""}
          {answer.citation.dataset_version ? ` · version ${answer.citation.dataset_version}` : ""}
        </p>
      ) : null}
      {answer.caveats.length ? (
        <ul className="mt-2 space-y-1 text-sm text-muted-foreground">
          {answer.caveats.map((c, i) => (
            <li key={i}>⚠︎ {c}</li>
          ))}
        </ul>
      ) : null}
      {answer.sql || answer.errors.length ? (
        <details className="group mt-4 rounded-lg border border-dashed border-border/70 p-3 open:bg-muted/30">
          <summary className="cursor-pointer select-none text-sm font-medium">
            Show your work
            <span className="ml-2 text-xs font-normal text-muted-foreground">
              {answer.row_count} row{answer.row_count === 1 ? "" : "s"} · SQL · assumptions · dataset
            </span>
          </summary>
          <div className="mt-3 space-y-3 text-sm">
            {answer.sql ? (
              <div>
                <div className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">SQL executed as the read-only role</div>
                <pre className="overflow-x-auto rounded-md bg-ink p-3 font-mono text-xs leading-relaxed text-zinc-100">{answer.sql}</pre>
              </div>
            ) : null}
            {answer.citation ? (
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
                <dt className="text-muted-foreground">Dataset</dt><dd>{answer.citation.dataset} <span className="text-muted-foreground">({answer.citation.table})</span></dd>
                <dt className="text-muted-foreground">Vintage</dt><dd>{answer.citation.dataset_version ?? "—"}</dd>
                <dt className="text-muted-foreground">Coverage</dt><dd>{answer.citation.coverage ?? "—"}</dd>
                <dt className="text-muted-foreground">Publisher</dt><dd className="truncate">{answer.citation.source ?? "—"}</dd>
              </dl>
            ) : null}
            {answer.assumptions.length ? (
              <div>
                <div className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">Assumptions made by the query writer</div>
                <ul className="list-disc space-y-0.5 pl-5">{answer.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul>
              </div>
            ) : null}
            {answer.rows.length ? (
              <div className="overflow-x-auto">
                <div className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">Rows returned{answer.rows.length > 20 ? " (first 20)" : ""}</div>
                <table className="w-full text-left text-xs">
                  <thead><tr>{answer.columns.map((c) => <th key={c} className="border-b border-border py-1 pr-3 font-medium">{c}</th>)}</tr></thead>
                  <tbody>
                    {answer.rows.slice(0, 20).map((r, i) => (
                      <tr key={i} className="border-b border-border/40">{answer.columns.map((c) => <td key={c} className="py-1 pr-3 font-mono tabular-nums">{fmt(r[c], c)}</td>)}</tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
            {answer.errors.length ? (
              <div>
                <div className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">Attempts that failed</div>
                <ul className="space-y-0.5 font-mono text-xs">{answer.errors.map((e, i) => <li key={i}>#{e.attempt} {e.kind}: {e.message}</li>)}</ul>
              </div>
            ) : null}
          </div>
        </details>
      ) : null}
    </article>
  );
}
