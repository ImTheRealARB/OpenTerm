import { Banner } from "./Banner";
import { MenuBar } from "./MenuBar";

/** The GUI strip under the top bar: the menu bar and, below it, the dismissible banner. It is one grid row of the app (height: auto). */
export function GuiTop() {
  return (
    <div className="gm-top">
      <MenuBar />
      <Banner />
    </div>
  );
}
