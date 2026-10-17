import { FUNCTIONS, FUNCTION_LIST, type FunctionProps } from "./registry";

export default function Help({ args }: FunctionProps) {
  const code = args[0]?.toUpperCase();
  if (code) {
    const def = FUNCTIONS.get(code);
    if (!def) return <div className="err">UNKNOWN FUNCTION: {code}</div>;
    return (
      <div>
        <h2>
          {def.code} — {def.title.toUpperCase()}
        </h2>
        <div>USAGE: {def.needsSecurity ? "<SECURITY> " : ""}{def.code} {def.argsSchema ?? ""}</div>
        <div className="dim">{def.load ? "AVAILABLE" : `NOT BUILT YET (PHASE ${def.phase})`}</div>
      </div>
    );
  }
  return (
    <div>
      <h2>FUNCTIONS</h2>
      <div className="dim">GRAMMAR: [N:] &lt;SECURITY&gt; [MARKET] &lt;FUNCTION&gt; [ARGS] | &lt;FUNCTION&gt; [ARGS]. SHIFT+ENTER = NEW PANEL. ? = SHORTCUTS.</div>
      <table className="t">
        <colgroup>
          <col style={{ width: 80 }} />
          <col />
          <col style={{ width: 90 }} />
        </colgroup>
        <tbody>
          {FUNCTION_LIST.map((f) => (
            <tr key={f.code}>
              <td className="acc">{f.code}</td>
              <td>{f.title.toUpperCase()}</td>
              <td className={f.load ? "up" : "dim"}>{f.load ? "READY" : `PHASE ${f.phase}`}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
