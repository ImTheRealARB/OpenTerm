# Adding a function

A function (`GP`, `DES`, ...) is one lazily-loaded React module plus one registry entry.

Shortcut: `python scripts/new_function.py FOO --title "What it does" [--security] [--args "[1Y|5Y]"]` does steps 1 and 2 below,
adds a vitest stub (`FOO.test.ts`) and regenerates `docs/FUNCTIONS.md`; `--dry-run` prints the plan, and it refuses to overwrite anything.
There is no per-function key binding step: `keys/keybindings.json` holds only the global actions, and a function is reached by typing its code.

1. Create `frontend/src/functions/Foo.tsx` with a default export:

   ```tsx
   import type { FunctionProps } from "./registry";
   export default function Foo({ panelId, security, args }: FunctionProps) {
     return <div>{security?.symbol} {args.join(" ")}</div>;
   }
   ```

2. Register it in `frontend/src/functions/registry.ts`:

   ```ts
   { code: "FOO", title: "What it does", needsSecurity: true, argsSchema: "[1Y|5Y]",
     load: () => import("./Foo") },
   ```

That is all: the command parser, autocomplete, `HELP`, panel titles, error boundary, lazy loading,
idle preloading and command-to-paint timing all pick it up from the registry.

Rules:
- `needsSecurity: true` makes the command fall back to the panel's sticky security and fail with a clear message when there is none.
- Never block the main thread: push heavy math into a Web Worker, and draw live tables on canvas, not DOM.
- Never show invented numbers. Missing data renders as `STALE` or `ERR` with the source and `as_of`.
- After adding or changing a function (registry) or a key binding, run `python scripts/gen_functions_doc.py` and commit `docs/FUNCTIONS.md`.
  `backend/tests/test_functions_doc.py` fails while the doc is stale.
