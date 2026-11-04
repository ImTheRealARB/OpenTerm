import type { FunctionProps } from "./registry";

/** FUNC: Function directory: every function code with its purpose; type to filter, Enter opens. Scaffolded by scripts/new_function.py; replace the body. Never show invented numbers (STALE / ERR with source and as_of). */
export default function FUNC({ args }: FunctionProps) {
  return (
    <div>
      <h2>FUNC</h2>
      <div className="dim">NOT IMPLEMENTED {args.length ? `: ${args.join(" ")}` : ""}</div>
    </div>
  );
}
