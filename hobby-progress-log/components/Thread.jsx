"use client";

import { shortDate } from "../lib/seed";

export default function Thread({ hobby, onPick }) {
  const attempts = hobby.attempts;
  const lastIdx = attempts.length - 1;

  return (
    <section className="px-5 pt-8">
      <header>
        <h1 className="text-xl font-medium">{hobby.name}</h1>
        <p className="text-faint mt-1 text-sm">{attempts.length} attempts</p>
      </header>

      <ul className="mt-6">
        {attempts.map((a, i) => (
          <li key={a.id}>
            <button
              onClick={() => onPick(i)}
              className="flex w-full items-start gap-4 border-b border-line py-4 text-left active:opacity-60"
            >
              <img
                src={a.imageUrl}
                alt=""
                className="h-14 w-14 shrink-0 rounded-lg bg-line object-cover"
              />
              <span className="min-w-0 pt-0.5">
                <span className="block text-sm font-medium">
                  attempt {a.index}
                  <span className="text-faint font-normal">
                    {" "}· {i === lastIdx ? "today" : shortDate(a.date)}
                  </span>
                </span>
                {a.note && (
                  <span className="text-faint mt-0.5 block text-sm leading-snug">
                    {a.note}
                  </span>
                )}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
