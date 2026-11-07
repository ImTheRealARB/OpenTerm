"""Scaffolds a new function (panel): the panel file, the registry entry, a vitest stub, then regenerates docs/FUNCTIONS.md.

    python scripts/new_function.py FOO
    python scripts/new_function.py FOO --title "What it does" --security --args "[1Y|5Y]"
    python scripts/new_function.py FOO --dry-run        # print the plan, write nothing

It refuses to overwrite: if the code is in the registry, or `frontend/src/functions/<NAME>.tsx` or
`<NAME>.test.ts` exists (compared case-insensitively, Windows is case-insensitive), nothing is written.

There is no per-function keybinding step: `keys/keybindings.json` holds only the global actions (focus, split, ...).
A function is reached by typing its code; keys inside a panel are registered by the panel itself (`registerPanelKeys`).
See docs/ADDING_A_FUNCTION.md. The stub panel shows "NOT IMPLEMENTED" and no numbers: never put invented data in it.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FUNCS = ROOT / "frontend/src/functions"
REGISTRY = FUNCS / "registry.ts"
CODE_RE = re.compile(r"^[A-Z][A-Z0-9]{0,11}$")
END_OF_DEFS = "\n];\n\nexport const FUNCTIONS"

PANEL = """import type {{ FunctionProps }} from "./registry";

/** {name}: {title}. Scaffolded by scripts/new_function.py; replace the body. Never show invented numbers (STALE / ERR with source and as_of). */
export default function {name}({{ {destructure} }}: FunctionProps) {{
  return (
    <div>
      <h2>{name}</h2>
      <div className="dim">NOT IMPLEMENTED{security_part}{args_part}</div>
    </div>
  );
}}
"""

TEST = """import {{ describe, expect, it }} from "vitest";
import {{ FUNCTIONS }} from "./registry";

// Stub scaffolded by scripts/new_function.py. Put pure parsing/formatting logic in its own file and test it here.
describe("{name} registry entry", () => {{
  it("is registered with a loader", () => {{
    const def = FUNCTIONS.get("{name}");
    expect(def).toBeDefined();
    expect(def?.load).toBeTypeOf("function");
  }});
}});
"""


def lf(text: str) -> bytes:
    return text.replace("\r\n", "\n").encode("utf-8")


def plan(name: str, title: str, security: bool, args: str) -> dict[Path, bytes]:
    parts = ""
    if security:
        parts += " for {security?.symbol ?? \"(no security)\"}"
    arg_part = " {args.length ? `: ${args.join(\" \")}` : \"\"}"
    panel = PANEL.format(name=name, title=title, security_part=parts, args_part=arg_part, destructure="security, args" if security else "args")
    return {
        FUNCS / f"{name}.tsx": lf(panel),
        FUNCS / f"{name}.test.ts": lf(TEST.format(name=name)),
    }


def registry_line(name: str, title: str, security: bool, args: str) -> str:
    bits = [f"code: {json.dumps(name)}", f"title: {json.dumps(title, ensure_ascii=False)}", f"needsSecurity: {str(security).lower()}"]
    if args:
        bits.append(f"argsSchema: {json.dumps(args, ensure_ascii=False)}")
    bits.append(f'load: () => import("./{name}")')
    return "  { " + ", ".join(bits) + " },"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("name", help="function code, upper case, e.g. FOO")
    ap.add_argument("--title", default=None, help="one-line description shown in HELP (default: the code)")
    ap.add_argument("--security", action="store_true", help="needsSecurity: true (falls back to the panel's sticky security)")
    ap.add_argument("--args", default="", help='argsSchema text shown in HELP, e.g. "[1Y|5Y]"')
    ap.add_argument("--dry-run", action="store_true", help="print the plan and write nothing")
    ns = ap.parse_args()

    name = ns.name.upper()
    if not CODE_RE.match(name):
        print(f"REFUSED: {ns.name!r} is not a function code (A-Z then A-Z0-9, at most 12 characters)", file=sys.stderr)
        return 2
    src = REGISTRY.read_text(encoding="utf-8")
    if END_OF_DEFS not in src:
        print("REFUSED: cannot find the end of the defs array in registry.ts (format changed?)", file=sys.stderr)
        return 2
    if re.search(rf'\{{ code: "{name}",', src):
        print(f"REFUSED: {name} is already in registry.ts", file=sys.stderr)
        return 1
    title = ns.title or name
    files = plan(name, title, ns.security, ns.args)
    existing = {p.name.lower() for p in FUNCS.iterdir()}
    clash = [p for p in files if p.name.lower() in existing]
    if clash:
        print("REFUSED: would overwrite " + ", ".join(str(p.relative_to(ROOT)) for p in clash), file=sys.stderr)
        return 1

    line = registry_line(name, title, ns.security, ns.args)
    print(("DRY RUN: would write" if ns.dry_run else "Writing") + ":")
    for p in files:
        print(f"  create {p.relative_to(ROOT)}")
    print(f"  append to {REGISTRY.relative_to(ROOT)}:\n    {line}")
    print("  run python scripts/gen_functions_doc.py")
    if ns.dry_run:
        return 0

    for p, data in files.items():
        p.write_bytes(data)
    REGISTRY.write_bytes(lf(src.replace(END_OF_DEFS, "\n" + line + END_OF_DEFS, 1)))
    # The registry's last entry has a trailing comma already, so the new line slots in cleanly.
    r = subprocess.run([sys.executable, str(ROOT / "scripts/gen_functions_doc.py")], cwd=ROOT)
    if r.returncode != 0:
        print("gen_functions_doc.py failed: files were written; fix and rerun it by hand", file=sys.stderr)
        return r.returncode
    print(f"Done. Next: replace the stub in frontend/src/functions/{name}.tsx, then `cd frontend; npx vitest run src/functions/{name}.test.ts; npx tsc --noEmit`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
