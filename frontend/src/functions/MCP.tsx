/**
 * MCP: third-party MCP servers OpenTerm can call as a client (stdio or Streamable HTTP), configured in `<data dir>/mcp_servers.yaml`.
 * Every server is OFF until you enable it; enabling shows the notice (third-party, unofficial, not affiliated with NSE, runs a program from npm/PyPI
 * on this machine, data terms are the source's) and needs a second press. Only tools on the per-tool allow-list reach the AI, as `<server>.<tool>`;
 * order-like tools are refused and cannot be allowed. Servers list: Up/Down or J/K select, E enable (twice), D disable, Enter or T test the connection
 * and list tools, R reload. Tools list: Up/Down or J/K select, Space or A toggle allow, Esc or Left back.
 * Commands: `MCP`, `MCP ENABLE <server> [YES]`, `MCP DISABLE <server>`, `MCP TEST <server>`, `MCP ALLOW <server> <tool>`, `MCP DENY <server> <tool>`.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { registerPanelKeys } from "../keys/panelKeys";
import { mcpApi } from "../net/aiApi";
import { replaceView } from "../state/workspace";
import { enableStep, mcpArgs, withTool } from "./mcpArgs";
import type { FunctionProps } from "./registry";

interface Server {
  name: string;
  preset: string | null;
  transport: "stdio" | "http";
  target: string;
  enabled: boolean;
  allow: string[];
  running: boolean;
  tools_seen: number | null;
  error: string | null;
  notice: string | null;
}
interface Tool {
  name: string;
  description: string;
  allowed: boolean;
  refused: string | null;
}
type Note = { text: string; cls: string } | null;
const GENERIC_NOTICE = "THIRD-PARTY CODE YOU CONFIGURED: IT RUNS ON THIS COMPUTER WITH YOUR PERMISSIONS WHEN USED. ITS RESULTS ARE LABELLED THIRD-PARTY AND THE AI TREATS THEM AS UNTRUSTED DATA.";

const errText = (r: { status: number; json: unknown }) => (r.json as { error?: { message?: string } } | null)?.error?.message ?? `HTTP ${r.status}`;

export default function MCP({ panelId, args }: FunctionProps) {
  const [servers, setServers] = useState<Server[]>([]);
  const [problems, setProblems] = useState<string[]>([]);
  const [file, setFile] = useState("");
  const [sel, setSel] = useState(0);
  const [tools, setTools] = useState<{ server: string; rows: Tool[] } | null>(null);
  const [tsel, setTsel] = useState(0);
  const [pending, setPending] = useState<string | null>(null);
  const [note, setNote] = useState<Note>(null);
  const [busy, setBusy] = useState(false);
  const live = useRef({ servers, sel, tools, tsel, pending, busy });
  live.current = { servers, sel, tools, tsel, pending, busy };

  const load = useCallback(async (): Promise<Server[] | null> => {
    try {
      const r = await mcpApi.servers<{ servers: Server[]; problems: string[]; file: string }>();
      if (!r.ok || !r.json) {
        setNote({ text: r.status === 403 ? "MCP SERVERS CAN ONLY BE MANAGED FROM THIS MACHINE" : `HTTP ${r.status}`, cls: "err" });
        return null;
      }
      setServers(r.json.servers);
      setProblems(r.json.problems);
      setFile(r.json.file);
      return r.json.servers;
    } catch {
      setNote({ text: "BACKEND DOWN", cls: "err" });
      return null;
    }
  }, []);

  const enable = useCallback(
    async (s: Server | undefined, confirmed: boolean) => {
      if (!s) return;
      if (enableStep(live.current.pending, s.name, confirmed) === "ask") {
        setPending(s.name);
        setNote({ text: `${s.notice ?? GENERIC_NOTICE} PRESS E AGAIN TO ENABLE ${s.name.toUpperCase()} (ANY OTHER KEY CANCELS; MCP ENABLE ${s.name} YES DOES THE SAME)`, cls: "warn" });
        return;
      }
      setPending(null);
      try {
        const r = await mcpApi.enable<{ notice: string; allow: string[] }>(s.name);
        if (!r.ok || !r.json) return setNote({ text: errText(r), cls: "err" });
        setNote({ text: `${s.name} ENABLED (${r.json.allow.length} TOOLS ALLOWED; T LISTS AND EDITS THEM). ${r.json.notice}`, cls: "up" });
        await load();
      } catch {
        setNote({ text: "BACKEND DOWN", cls: "err" });
      }
    },
    [load],
  );

  const disable = useCallback(
    async (name: string) => {
      try {
        const r = await mcpApi.disable(name);
        if (!r.ok) return setNote({ text: errText(r), cls: "err" });
        setTools((t) => (t?.server === name ? null : t));
        setNote({ text: `${name} DISABLED AND STOPPED`, cls: "dim" });
        await load();
      } catch {
        setNote({ text: "BACKEND DOWN", cls: "err" });
      }
    },
    [load],
  );

  const test = useCallback(
    async (name: string) => {
      setBusy(true);
      setNote({ text: `STARTING ${name} ... (CAN TAKE A WHILE THE FIRST TIME: IT MAY DOWNLOAD A PACKAGE)`, cls: "dim" });
      try {
        const r = await mcpApi.tools<{ tools: Tool[] }>(name);
        if (!r.ok || !r.json) setNote({ text: `${name}: ${errText(r)}`, cls: "err" });
        else {
          setTools({ server: name, rows: r.json.tools });
          setTsel(0);
          setNote({ text: `${name} CONNECTED: ${r.json.tools.length} TOOLS. SPACE TOGGLES ALLOW (ONLY ALLOWED TOOLS REACH THE AI)`, cls: "up" });
        }
      } catch {
        setNote({ text: "BACKEND DOWN", cls: "err" });
      }
      setBusy(false);
      await load();
    },
    [load],
  );

  const setAllow = useCallback(
    async (name: string, tool: string, on: boolean) => {
      const cur = live.current.servers.find((s) => s.name === name);
      if (!cur) return;
      try {
        const r = await mcpApi.allow<{ allow: string[] }>(name, withTool(cur.allow, tool, on));
        if (!r.ok || !r.json) return setNote({ text: errText(r), cls: "err" });
        setTools((t) => (t && t.server === name ? { ...t, rows: t.rows.map((x) => (x.name === tool ? { ...x, allowed: on } : x)) } : t));
        setNote({ text: `${name}.${tool} ${on ? "ALLOWED" : "NOT ALLOWED"}`, cls: "dim" });
        await load();
      } catch {
        setNote({ text: "BACKEND DOWN", cls: "err" });
      }
    },
    [load],
  );

  const asked = useRef(false);
  useEffect(() => {
    if (asked.current) return;
    asked.current = true;
    const a = mcpArgs(args);
    void (async () => {
      const list = await load();
      if (a.mode === "bad") setNote({ text: a.error, cls: "err" });
      else if (a.mode !== "list" && list) {
        const s = list.find((x) => x.name === a.name);
        if (!s) setNote({ text: `NO SERVER NAMED ${a.name}: THE LIST SHOWS THEM`, cls: "err" });
        else if (a.mode === "enable") await enable(s, a.confirmed);
        else if (a.mode === "disable") await disable(s.name);
        else if (a.mode === "test") await test(s.name);
        else if (a.mode === "allow" || a.mode === "deny") await setAllow(s.name, a.tool, a.mode === "allow");
      }
    })();
    if (args.length) replaceView(panelId, (v) => ({ ...v, args: [] }));
  }, [args, panelId, load, enable, disable, test, setAllow]);

  useEffect(
    () =>
      registerPanelKeys(panelId, (e) => {
        const k = e.key.toLowerCase();
        const { servers: ss, sel: i, tools: t, tsel: ti, pending: p, busy: b } = live.current;
        if (p && k !== "e") setPending(null);
        if (b) return true;
        const down = k === "arrowdown" || k === "j";
        const up = k === "arrowup" || k === "k";
        if (t) {
          if (down) setTsel(Math.min(t.rows.length - 1, ti + 1));
          else if (up) setTsel(Math.max(0, ti - 1));
          else if (k === "escape" || k === "arrowleft") setTools(null);
          else if (k === " " || k === "a") {
            const row = t.rows[ti];
            if (row && !row.refused) void setAllow(t.server, row.name, !row.allowed);
            else if (row) setNote({ text: `${row.name}: ${row.refused}`, cls: "warn" });
          } else if (k === "r") void test(t.server);
          else return false;
          return true;
        }
        const s = ss[i];
        if (down) setSel(Math.min(ss.length - 1, i + 1));
        else if (up) setSel(Math.max(0, i - 1));
        else if (k === "e") void enable(s, false);
        else if (k === "d") {
          if (s?.enabled) void disable(s.name);
        } else if (k === "t" || k === "enter") {
          if (!s) return true;
          if (s.enabled) void test(s.name);
          else setNote({ text: `${s.name} IS OFF: PRESS E TO ENABLE IT FIRST`, cls: "warn" });
        } else if (k === "r") void load();
        else return false;
        return true;
      }),
    [panelId, enable, disable, test, setAllow, load],
  );

  const cur = servers[Math.min(sel, servers.length - 1)];
  return (
    <div className="fn" data-testid="mcp-panel">
      <div className="line">
        <span className="acc">MCP</span>{" "}
        <span className="dim">
          THIRD-PARTY MCP SERVERS (OFF UNTIL YOU ENABLE THEM; RESULTS ARE UNTRUSTED DATA) ·{" "}
          {tools ? "UP/DOWN SELECT · SPACE ALLOW/DENY · R RELOAD TOOLS · ESC BACK" : "UP/DOWN SELECT · E ENABLE (TWICE) · D DISABLE · ENTER/T TEST + TOOLS · R RELOAD"}
        </span>
      </div>
      <div className="dim">CONFIG {file || "<data dir>/mcp_servers.yaml"} (EDIT BY HAND TO ADD SERVERS: command, args, env, url, headers; SEE docs/MCP.md)</div>
      {problems.map((p, i) => (
        <div key={i} className="warn">{p}</div>
      ))}
      {note && <div className={note.cls} data-testid="mcp-note">{note.text}</div>}
      <div className="ai-log">
        {servers.map((s, i) => (
          <div key={s.name} className={i === Math.min(sel, servers.length - 1) && !tools ? "acc" : ""} data-testid="mcp-row">
            {i === Math.min(sel, servers.length - 1) ? "> " : "  "}
            {s.name.padEnd(18)} {s.enabled ? "ON " : "OFF"} {s.transport.toUpperCase().padEnd(5)} {s.running ? "RUNNING" : "STOPPED"} · {s.allow.length} ALLOWED
            {s.tools_seen !== null ? ` OF ${s.tools_seen} TOOLS` : ""} · {s.target}
            {s.preset ? " · PRESET (UNOFFICIAL)" : ""}
            {s.error ? ` · LAST ERROR: ${s.error}` : ""}
          </div>
        ))}
        {!tools && cur && !cur.enabled && cur.preset && <div className="dim" data-testid="mcp-preset-notice">{cur.notice}</div>}
        {tools && (
          <div className="ai-turn" data-testid="mcp-tools">
            <div className="dim">{tools.server} TOOLS ({tools.rows.length}): [x] ALLOWED TO THE AI AS {tools.server}.&lt;tool&gt; · [-] REFUSED (ORDER-LIKE) · [ ] NOT ALLOWED</div>
            {tools.rows.map((t, i) => (
              <div key={t.name} className={i === tsel ? "acc" : t.refused ? "warn" : ""} data-testid="mcp-tool">
                {i === tsel ? "> " : "  "}[{t.refused ? "-" : t.allowed ? "x" : " "}] {t.name.padEnd(32)} {t.refused ?? t.description}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
