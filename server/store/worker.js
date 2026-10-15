// The FlickOS store's Worker (docs/design/flickos-software.md, Q7 and
// ADR-009). So far it serves one file: the Software app's front page shelves,
// featured.json, which flickos-software fetches at most once a day. The list
// is the package's own copy, bundled at deploy, so the shelves change with
// `wrangler deploy` and the next package release carries the same list for
// computers that are offline. Nothing is stored or logged.
import featured from "../../packages/flickos-software/usr/share/flickos/software/featured.json";

const BODY = JSON.stringify(featured, null, 2) + "\n";
const HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "public, max-age=3600",
};

export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (url.pathname !== "/v1/featured.json") {
      return new Response("not found\n", { status: 404 });
    }
    if (request.method === "HEAD") {
      return new Response(null, { headers: HEADERS });
    }
    if (request.method !== "GET") {
      return new Response("method not allowed\n", { status: 405, headers: { allow: "GET, HEAD" } });
    }
    return new Response(BODY, { headers: HEADERS });
  },
};
