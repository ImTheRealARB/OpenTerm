/** Jumping to the MAP panel from another function (AIS, PORTS, SHIP): the same panel is navigated, so Back returns to where you were. */
import { navigate } from "../state/workspace";
import { AIS_AREAS } from "../functions/aisArgs";

/** The MAP words for a function: AIS shows its chokepoint's ships, PORTS the ports layer, SHIP the chokepoint boxes. */
export function mapArgsFor(fn: "AIS" | "PORTS" | "SHIP", aisQuery = ""): string[] | null {
  if (fn === "AIS") {
    const area = aisQuery.toUpperCase();
    // A custom BOX has no place on the map's chokepoint list: say nothing rather than open the wrong area.
    return (AIS_AREAS as readonly string[]).includes(area) ? ["VESSELS", area] : null;
  }
  return fn === "PORTS" ? ["PORTS"] : ["CHOKEPOINTS"];
}

export function openMap(panelId: number, args: string[]): void {
  navigate(panelId, { fn: "MAP", args });
}
