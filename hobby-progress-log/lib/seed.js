// one hobby, 14 attempts, spread over ~6 weeks ending today.
// dates are computed backwards from now so "today" is always today.

const NOTES = [
  "milk went everywhere, no shape at all",
  "a blob. but a centered blob",
  "milk too thin, it just sank into the crema",
  "first hint of a ring, poured too fast at the end",
  "steamed too hot, foam went stiff and chalky",
  "an actual circle. white, round, sat on top",
  "tried to drag a line through it. smeared",
  "heart??? if you squint",
  "back to blobs. tired, rushed the steam",
  "slowed the whole pour down. shape held",
  "two-layer heart, lopsided but definitely there",
  "first tulip try. came out more like a worm",
  "got the drag, wobbled the finish",
  "clean heart, almost symmetric. didn't even mean to",
];

// days before today for each attempt — irregular, like real life
const DAYS_AGO = [42, 40, 37, 34, 31, 28, 25, 21, 18, 14, 10, 7, 3, 0];

function daysAgoISO(days) {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString();
}

export function seedHobby() {
  return {
    id: "hobby-latte-art",
    name: "latte art",
    attempts: NOTES.map((note, i) => ({
      id: `attempt-${i + 1}`,
      imageUrl: `/seed/latte-${i + 1}.svg`,
      note,
      date: daysAgoISO(DAYS_AGO[i]),
      index: i + 1,
    })),
  };
}

const MONTHS = [
  "jan", "feb", "mar", "apr", "may", "jun",
  "jul", "aug", "sep", "oct", "nov", "dec",
];

export function shortDate(iso) {
  const d = new Date(iso);
  return `${MONTHS[d.getMonth()]} ${d.getDate()}`;
}

export function weeksIn(attempts) {
  if (attempts.length < 2) return "day one";
  const first = new Date(attempts[0].date);
  const last = new Date(attempts[attempts.length - 1].date);
  const weeks = Math.round((last - first) / (7 * 24 * 60 * 60 * 1000));
  if (weeks < 1) return "first week";
  if (weeks === 1) return "1 week in";
  return `${weeks} weeks in`;
}
