# packages/shared

Reserved for TypeScript types and Zod schemas shared between the frontend and any
Node-side tooling.

**Currently empty by design.** The API contract schemas live in
[`apps/web/lib/schemas.ts`](../../apps/web/lib/schemas.ts) — they are the single
source of truth for every response shape the web app parses, and `apps/web/lib/api.ts`
validates against them at the fetch boundary.

They stay inside `apps/web` because this repo is not an npm workspace: a package
here cannot resolve `zod` from the app's `node_modules`. Move them into this
package at the point a second consumer appears (a Node CLI, an eval runner in TS),
which is also the point a root `package.json` with `workspaces` becomes worth adding.
