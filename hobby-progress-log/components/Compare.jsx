"use client";

import { shortDate, weeksIn } from "../lib/seed";

function Panel({ attempt, isToday }) {
  return (
    <figure className="min-w-0">
      <div className="aspect-[3/4] overflow-hidden rounded-xl bg-line">
        {/* plain img: attempt images can be blob: URLs from the camera */}
        <img
          src={attempt.imageUrl}
          alt={`attempt ${attempt.index}`}
          className="h-full w-full object-cover"
        />
      </div>
      <figcaption className="mt-2.5 px-0.5">
        <p className="text-xs font-medium">
          {isToday ? "today" : shortDate(attempt.date)}
          <span className="text-faint font-normal">
            {" "}· attempt {attempt.index}
          </span>
        </p>
        {attempt.note && (
          <p className="text-faint mt-1 text-sm leading-snug">{attempt.note}</p>
        )}
      </figcaption>
    </figure>
  );
}

export default function Compare({ hobby, leftIndex, onLeftIndexChange }) {
  const attempts = hobby.attempts;
  const latest = attempts[attempts.length - 1];
  const left = attempts[leftIndex];

  return (
    <section className="px-5 pt-8">
      <header>
        <h1 className="text-xl font-medium">{hobby.name}</h1>
        <p className="text-faint mt-1 text-sm">
          attempt {latest.index} · {weeksIn(attempts)}
        </p>
      </header>

      <div className="mt-7 grid grid-cols-2 gap-3">
        <Panel attempt={left} isToday={false} />
        <Panel attempt={latest} isToday={true} />
      </div>

      <div className="mt-8">
        <p className="text-faint text-xs">earlier attempt</p>
        <input
          type="range"
          className="scrubber mt-1"
          min={0}
          max={attempts.length - 2}
          step={1}
          value={leftIndex}
          onChange={(e) => onLeftIndexChange(Number(e.target.value))}
          aria-label="choose which earlier attempt to compare against"
        />
        {/* one tick per selectable attempt, aligned under the thumb's travel */}
        <div className="flex justify-between px-[13px]" aria-hidden="true">
          {attempts.slice(0, -1).map((a, i) => (
            <span
              key={a.id}
              className={`h-1 w-1 rounded-full ${
                i === leftIndex ? "bg-ink" : "bg-line"
              }`}
            />
          ))}
        </div>
      </div>
    </section>
  );
}
