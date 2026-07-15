# hobby progress log

A mobile-first, single-page app for seeing your own improvement. You photograph
each attempt at a hobby; the app threads them together and shows today's attempt
next to an earlier one, so progress becomes visible. No streaks, no scores,
no ratings — the images and your own notes carry everything.

## Screens

- **capture** — camera/upload front and center, one optional note, done.
  Attempt number and date are assigned automatically. Saving drops you straight
  onto the compare screen.
- **compare** — the payoff. Today's attempt fixed on the right, an earlier
  attempt on the left (defaults to attempt 1). A scrubber below changes which
  earlier attempt you're comparing against.
- **thread** — chronological list of every attempt. Tap one to set it as the
  compare target.

## Stack

Next.js (App Router) + Tailwind CSS 4. No auth, no database — local React
state seeded with one hobby ("latte art", 14 attempts over ~6 weeks) from
`lib/seed.js`. Seed images are local SVG placeholders in `public/seed/`
whose milk shapes roughly track the notes, from splatter to a clean heart.

## Run

```bash
npm install
npm run dev
```

Open http://localhost:3000 in a ~390px mobile viewport.
