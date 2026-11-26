/** OSCAN arguments (pure): `OSCAN <UNIVERSE> [IVR>50] [EM>5] [OI>1000] [PCR>1.2]`. The server validates the filter terms. */
export type OscanArgs = { ok: true; universe: string; filter: string } | { ok: false; error: string };

export function parseOscanArgs(args: string[]): OscanArgs {
  const universe = (args[0] ?? "").trim().toUpperCase();
  if (!universe) return { ok: false, error: "OSCAN NEEDS A UNIVERSE: OSCAN WL:<NAME> IVR>50" };
  return { ok: true, universe, filter: args.slice(1).join(" ").toUpperCase() };
}
