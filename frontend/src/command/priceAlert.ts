/** Price alert from the chart (GP key A / Alt+click). Own module so only the lazy GP chunk carries it. */
import { api8 } from "../net/api";
import { act, askNotifyPermission } from "./alerts";
import { parseRule } from "./alertArgs";
import { fail } from "./status";

/**
 * Creates a price alert from the chart (GP key A / Alt+click): the same rule validation (`parseRule`) and the same create path
 * as `ALRT SYM > 200`. `priceText` is the rounded price as shown ("231.50"). Resolves true when saved.
 */
export function createPriceAlert(symbol: string, op: ">" | "<", priceText: string): Promise<boolean> {
  const rule = parseRule(`${op}${priceText}`);
  if (typeof rule === "string") return Promise.resolve(fail(rule));
  askNotifyPermission(); // synchronously, inside the keypress or click that asked
  const text = `${symbol} ${op} ${priceText}`;
  return act(`ALERT ${text} NOT SAVED`, () => api8.createAlert({ symbol, ...rule }), `ALERT SET: ${text} (ALRT TO MANAGE)`);
}
