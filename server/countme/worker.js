// FlickOS weekly count: the server side of flickos-countme (packages/flickos-countme).
//
//   GET /v1/countme?version=2.0&age=1   one computer, this week: n + 1
//   GET /v1/stats                       all counts as JSON
//
// Only the ISO week (UTC), the version and the age bucket are stored. The
// request's address, user agent and time are never read or written, and
// observability (request logs) is off in wrangler.toml.

const VERSION = /^\d{1,2}\.\d{1,2}$/;
const AGES = new Set(["1", "2", "3", "4"]);

function isoWeek(date) {
  // ISO 8601: the week with the year's first Thursday is week 1.
  const day = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
  const weekday = day.getUTCDay() || 7;
  day.setUTCDate(day.getUTCDate() + 4 - weekday);
  const yearStart = new Date(Date.UTC(day.getUTCFullYear(), 0, 1));
  const week = Math.ceil(((day - yearStart) / 86400000 + 1) / 7);
  return `${day.getUTCFullYear()}-W${String(week).padStart(2, "0")}`;
}

function text(body, status = 200) {
  return new Response(body + "\n", { status, headers: { "content-type": "text/plain; charset=utf-8" } });
}

async function countme(url, env) {
  const version = url.searchParams.get("version") || "";
  const age = url.searchParams.get("age") || "";
  if (!VERSION.test(version) || !AGES.has(age) || [...url.searchParams.keys()].length !== 2) {
    return text("bad request", 400);
  }
  await env.DB.prepare(
    "INSERT INTO counts (week, version, age, n) VALUES (?1, ?2, ?3, 1) " +
    "ON CONFLICT (week, version, age) DO UPDATE SET n = n + 1"
  ).bind(isoWeek(new Date()), version, Number(age)).run();
  return text("counted");
}

async function stats(env) {
  const { results } = await env.DB.prepare(
    "SELECT week, version, age, n FROM counts ORDER BY week DESC, version, age"
  ).all();
  return new Response(JSON.stringify(results), {
    headers: { "content-type": "application/json", "access-control-allow-origin": "*" },
  });
}

export default {
  async fetch(request, env) {
    if (request.method !== "GET") {
      return text("method not allowed", 405);
    }
    const url = new URL(request.url);
    if (url.pathname === "/v1/countme") {
      return countme(url, env);
    }
    if (url.pathname === "/v1/stats") {
      return stats(env);
    }
    return text("not found", 404);
  },
};

export { isoWeek };
