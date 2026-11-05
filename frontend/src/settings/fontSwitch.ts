/**
 * Switches the font from anywhere in the UI (menu dropdown, `SETTINGS FONT ...`). The change applies at once. A font that is
 * not bundled (a system preset such as Menlo, or any custom name) is also checked, and a warning is shown when this browser cannot
 * confirm it is installed. The check is only a hint (see fontCheck.ts), so it never blocks the change.
 */
import { fail, info } from "../command/status";
import { findPreset } from "./fontPresets";
import { updateSettings } from "./runtime";

export function chooseFont(name: string): void {
  updateSettings((s) => ({ ...s, font: name }));
  const preset = findPreset(name);
  const label = preset ? preset.label : name;
  if (preset && !preset.system) {
    info(`FONT ${label.toUpperCase()}`);
    return;
  }
  void import("./fontCheck").then(({ fontInstalled }) => {
    if (fontInstalled(name)) info(`FONT ${label.toUpperCase()}`);
    else fail(`FONT "${name}" APPLIED, BUT THIS BROWSER COULD NOT CONFIRM IT IS INSTALLED. IF NOTHING CHANGED, CHECK THE SPELLING`);
  });
}
