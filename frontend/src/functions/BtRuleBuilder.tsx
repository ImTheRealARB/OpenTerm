import { useState, type KeyboardEvent } from "react";
import {
  OPERANDS, OPS, defaultOperand, emptyClause, formError, formToRule, formToSentence, isPeriodKind,
  type Clause, type Form, type Op, type Operand, type OperandKind,
} from "./ruleSentence";

/**
 * GUI mode: "Buy when [20-day average] [crosses above] [50-day average]; sell when it crosses back below."
 * A sentence-shaped form that writes the existing BT rule grammar (ruleSentence.ts) and shows the generated rule text,
 * so a beginner learns the grammar by using it. Native selects and number inputs: Tab, arrows and typing all work.
 * Loaded on demand (BtRuleLazy) so it adds nothing to the startup bundle.
 */
export default function BtRuleBuilder({ onRun }: { onRun: (rule: string, symbol: string) => void }) {
  const [form, setForm] = useState<Form>({ buy: [[emptyClause()]] });
  const [symbol, setSymbol] = useState("AAPL");

  const rule = formToRule(form);
  const error = formError(form);
  const total = form.buy.reduce((n, g) => n + g.length, 0);

  const setClause = (gi: number, ci: number, fn: (c: Clause) => Clause) =>
    setForm((f) => ({ buy: f.buy.map((g, i) => (i === gi ? g.map((c, j) => (j === ci ? fn(c) : c)) : g)) }));
  const addAnd = (gi: number) => setForm((f) => ({ buy: f.buy.map((g, i) => (i === gi ? [...g, emptyClause()] : g)) }));
  const addOr = () => setForm((f) => ({ buy: [...f.buy, [emptyClause()]] }));
  const remove = (gi: number, ci: number) =>
    setForm((f) => ({ buy: f.buy.map((g, i) => (i === gi ? g.filter((_, j) => j !== ci) : g)).filter((g) => g.length) }));

  // Typing in a field must not trigger panel keys; Ctrl/Alt/Meta chords still bubble (Ctrl+K opens the command line).
  const guard = (e: KeyboardEvent) => {
    if (!e.ctrlKey && !e.altKey && !e.metaKey) e.stopPropagation();
  };

  return (
    <div className="bt-rule" data-testid="bt-rule-builder" onKeyDown={guard}>
      <div className="bt-starter-h">Or build your own rule</div>
      {form.buy.map((g, gi) => (
        <div className="bt-rule-group" key={gi}>
          {g.map((c, ci) => {
            const n = `${gi + 1}.${ci + 1}`;
            return (
              <div className="bt-rule-clause" key={ci} data-testid="bt-rule-clause">
                <span className="bt-rule-lead">{ci > 0 ? "and" : gi > 0 ? "or buy when" : "Buy when"}</span>
                <OperandField label={`Condition ${n} first value`} value={c.left} onChange={(left) => setClause(gi, ci, (x) => ({ ...x, left }))} />
                <select
                  aria-label={`Condition ${n} comparison`}
                  value={c.op}
                  onChange={(e) => setClause(gi, ci, (x) => ({ ...x, op: e.target.value as Op }))}
                >
                  {OPS.map((o) => (
                    <option key={o.op} value={o.op}>{o.op}</option>
                  ))}
                </select>
                <OperandField label={`Condition ${n} second value`} value={c.right} onChange={(right) => setClause(gi, ci, (x) => ({ ...x, right }))} />
                {total > 1 && (
                  <button type="button" className="bt-rule-x" aria-label={`Remove condition ${n}`} onClick={() => remove(gi, ci)}>
                    Remove
                  </button>
                )}
              </div>
            );
          })}
          <button type="button" onClick={() => addAnd(gi)}>+ add condition</button>
        </div>
      ))}
      <button type="button" onClick={addOr}>+ add another way to buy</button>
      <div className="bt-rule-sentence" data-testid="bt-rule-live-sentence">{formToSentence(form) || "Add a condition."}</div>
      <div className="bt-rule-text" data-testid="bt-rule-text">
        Rule: <span className="acc">{rule}</span>
      </div>
      {error && <div className="err" data-testid="bt-rule-error">{error}</div>}
      <div className="bt-starter-run">
        <label>
          Stock{" "}
          <input
            className="bt-starter-sym"
            value={symbol}
            spellCheck={false}
            autoComplete="off"
            aria-label="Stock to test with this rule"
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
          />
        </label>
        <button type="button" data-testid="bt-rule-run" disabled={!!error || !symbol.trim()} onClick={() => onRun(rule, symbol.trim())}>
          Run this rule
        </button>
        <span className="dim"> 5 years of daily prices, default fees. Past results do not predict the future.</span>
      </div>
    </div>
  );
}

function OperandField({ label, value, onChange }: { label: string; value: Operand; onChange: (o: Operand) => void }) {
  const period = isPeriodKind(value.kind);
  const input = (
    <input
      type="number"
      className="bt-rule-n"
      aria-label={`${label}: ${value.kind === "number" ? "number" : "days"}`}
      min={period ? 1 : undefined}
      max={period ? 1000 : undefined}
      step={period ? 1 : "any"}
      value={Number.isNaN(value.n) ? "" : value.n}
      onChange={(e) => onChange({ ...value, n: e.target.value === "" ? NaN : Number(e.target.value) })}
    />
  );
  const pick = (kind: OperandKind) => onChange(defaultOperand(kind)); // each kind starts at its usual period (RSI 14, average 20)
  return (
    <span className="bt-rule-operand">
      {period && input}
      <select aria-label={label} value={value.kind} onChange={(e) => pick(e.target.value as OperandKind)}>
        {OPERANDS.map((o) => (
          <option key={o.kind} value={o.kind}>{o.label.replace(/^-/, "")}</option>
        ))}
      </select>
      {value.kind === "number" && input}
    </span>
  );
}
