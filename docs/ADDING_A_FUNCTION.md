# Adding a function

A function (`GP`, `DES`, ...) is one lazily-loaded React module plus one registry entry.

1. Create `frontend/src/functions/Foo.tsx` with a default export:

   ```tsx
   import type { FunctionProps } from "./registry";
   export default function Foo({ panelId, security, args }: FunctionProps) {
     return <div>{security?.symbol} {args.join(" ")}</div>;
   }
   ```

2. Register it in `frontend/src/functions/registry.ts`:

   ```ts
   { code: "FOO", title: "What it does", needsSecurity: true, argsSchema: "[1Y|5Y]", phase: 3,
     load: () => import("./Foo") },
   ```

That is all: the command parser, autocomplete, `HELP`, panel titles, error boundary, lazy loading,
idle preloading and command-to-paint timing all pick it up from the registry.

Rules:
- `needsSecurity: true` makes the command fall back to the panel's sticky security and fail with a clear message when there is none.
- Never block the main thread: push heavy math into a Web Worker, and draw live tables on canvas, not DOM.
- Never show invented numbers. Missing data renders as `STALE` or `ERR` with the source and `as_of`.
