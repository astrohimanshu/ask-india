"use client";

import { useEffect, useRef, useState } from "react";
import { AnswerCard } from "@/components/answer-card";
import { ProgressSteps } from "@/components/progress-steps";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { askStream, type Answer, type Status } from "@/lib/api";

type Turn = { id: number; question: string; steps: Status[]; answer: Answer | null; error: string | null };

const EXAMPLES = [
  "Which airline carried the most domestic passengers in January 2025?",
  "How much rain did Kerala get in the 2018 monsoon compared with normal?",
  "Which state had the highest literacy rate in the 2011 census?",
  "How has the petrol price in Delhi changed each year since 2017?",
  "Top five sugarcane producing states in 2024-25",
  "Is Bengaluru airport busier than Hyderabad?",
];

export default function Home() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  async function submit(q: string) {
    const text = q.trim();
    if (!text || busy) return;
    const id = Date.now();
    setTurns((t) => [...t, { id, question: text, steps: [], answer: null, error: null }]);
    setQuestion("");
    setBusy(true);
    const update = (patch: (turn: Turn) => Turn) => setTurns((all) => all.map((t) => (t.id === id ? patch(t) : t)));
    try {
      await askStream(text, {
        onStatus: (s) => update((t) => ({ ...t, steps: [...t.steps, s] })),
        onFinal: (a) => update((t) => ({ ...t, answer: a })),
        onError: (m) => update((t) => ({ ...t, error: m })),
      });
    } catch (e) {
      update((t) => ({ ...t, error: e instanceof Error ? e.message : "The request failed." }));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col px-5 pt-8 pb-28">
      {turns.length === 0 ? (
        <section className="mb-8">
          <h1 className="font-display text-4xl font-semibold leading-tight tracking-tight sm:text-5xl">
            Ask a question about India.
            <br />
            <span className="text-saffron">Get the number, and the receipt.</span>
          </h1>
          <p className="mt-4 max-w-xl text-muted-foreground">
            Every answer is computed by a SQL query over a versioned copy of an official government dataset.
            No figure comes from a model&rsquo;s memory; a programmatic guard checks each number against
            the rows before you see it, and refuses rather than guesses.
          </p>
          <div className="mt-6 flex flex-wrap gap-2">
            {EXAMPLES.map((e) => (
              <button
                key={e}
                onClick={() => submit(e)}
                className="rounded-full border border-border bg-card px-3 py-1.5 text-left text-sm hover:border-saffron hover:text-foreground"
              >
                {e}
              </button>
            ))}
          </div>
        </section>
      ) : null}

      <div className="flex flex-1 flex-col gap-6">
        {turns.map((t) => (
          <section key={t.id} className="space-y-3">
            <p className="ml-auto max-w-[85%] rounded-2xl rounded-br-sm bg-ink px-4 py-2 text-sm text-zinc-50 w-fit">{t.question}</p>
            {t.answer ? <AnswerCard answer={t.answer} /> : <ProgressSteps steps={t.steps} done={false} />}
            {t.error ? <p className="text-sm text-red-700">{t.error}</p> : null}
          </section>
        ))}
        <div ref={bottom} />
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit(question);
        }}
        className="sticky bottom-4 mt-8 flex items-end gap-2 rounded-xl border border-border bg-card p-2 shadow-lg"
      >
        <Textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit(question);
            }
          }}
          placeholder="e.g. How many passengers did Delhi airport handle in June 2025?"
          className="min-h-[44px] resize-none border-0 bg-transparent shadow-none focus-visible:ring-0"
          rows={1}
          maxLength={500}
        />
        <Button type="submit" disabled={busy || question.trim().length < 3}>
          {busy ? "Working…" : "Ask"}
        </Button>
      </form>
    </main>
  );
}
