import { getDatasets, type Dataset } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function DatasetsPage() {
  let datasets: Dataset[] = [];
  let error: string | null = null;
  try {
    datasets = await getDatasets();
  } catch (e) {
    error = e instanceof Error ? e.message : "could not load the catalogue";
  }
  return (
    <main className="mx-auto w-full max-w-4xl px-5 py-8">
      <h1 className="font-display text-3xl font-semibold tracking-tight">What data is behind the answers</h1>
      <p className="mt-2 max-w-2xl text-muted-foreground">
        Questions outside these datasets and dates are declined, not guessed. Each load is versioned by fetch date and
        content hash; the version appears on every answer.
      </p>
      {error ? <p className="mt-6 text-red-700">{error}</p> : null}
      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        {datasets.map((d) => (
          <section key={d.dataset} className="rounded-xl border border-border/70 bg-card p-4">
            <h2 className="font-medium">{d.title}</h2>
            <p className="mt-1 text-sm text-muted-foreground">{d.source_org}</p>
            <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
              <dt className="text-muted-foreground">Covers</dt>
              <dd>{d.coverage_from ? `${d.coverage_from} → ${d.coverage_to}` : "—"}</dd>
              <dt className="text-muted-foreground">Cadence</dt>
              <dd>{d.cadence ?? "—"}</dd>
              <dt className="text-muted-foreground">Version</dt>
              <dd className="font-mono text-xs">{d.current_version}{d.is_seed ? " (seed fixture)" : ""}</dd>
              <dt className="text-muted-foreground">Table</dt>
              <dd className="font-mono text-xs">{d.table_name}</dd>
            </dl>
            {d.source_url ? (
              <a href={d.source_url} className="mt-3 inline-block text-sm text-saffron hover:underline">
                publisher page ↗
              </a>
            ) : null}
          </section>
        ))}
      </div>
    </main>
  );
}
