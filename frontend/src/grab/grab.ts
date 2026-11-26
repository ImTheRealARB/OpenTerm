/**
 * GRAB (Phase 22): a picture of one panel as a PNG. `GRAB` copies it to the clipboard, `GRAB SAVE` downloads it,
 * `GRAB VIA TG,EMAIL` sends it through the delivery channels set up in DLVR. A lazy chunk: nothing here loads at startup.
 *
 * Browsers have no "screenshot this element" call, so `capture` redraws the panel itself onto one canvas: every element's
 * background colour, every <canvas> (grids and charts are canvases) copied pixel for pixel, and every piece of text at its
 * on-screen place in its own font and colour. That covers what OpenTerm panels are made of (no images, no gradients).
 */
import { deliveryApi } from "../net/deliveryApi";
import { fail, info } from "../command/status";
import { currentView, workspace } from "../state/workspace";

/** A transparent CSS colour (nothing to paint). */
const clear = (c: string) => !c || c === "transparent" || /rgba\([^)]*,\s*0\)$/.test(c);

/** Draws `root` and everything visible inside it onto a new canvas at device-pixel resolution. */
export function capture(root: HTMLElement): HTMLCanvasElement {
  const box = root.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const cv = document.createElement("canvas");
  cv.width = Math.round(box.width * dpr);
  cv.height = Math.round(box.height * dpr);
  const ctx = cv.getContext("2d")!;
  ctx.scale(dpr, dpr);
  ctx.textBaseline = "alphabetic";
  // The page background first: panels sit on it and many elements are transparent.
  ctx.fillStyle = getComputedStyle(document.body).backgroundColor || "#000";
  ctx.fillRect(0, 0, box.width, box.height);
  const walk = (el: Element) => {
    const st = getComputedStyle(el);
    if (st.display === "none" || st.visibility === "hidden") return;
    const r = el.getBoundingClientRect();
    const x = r.left - box.left;
    const y = r.top - box.top;
    if (!clear(st.backgroundColor)) {
      ctx.fillStyle = st.backgroundColor;
      ctx.fillRect(x, y, r.width, r.height);
    }
    if (el instanceof HTMLCanvasElement) {
      // Canvas content (grid rows, chart, drawings overlay) is copied as drawn.
      if (el.width && el.height) ctx.drawImage(el, x, y, r.width, r.height);
      return;
    }
    if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement || el instanceof HTMLSelectElement) {
      ctx.font = `${st.fontWeight} ${st.fontSize} ${st.fontFamily}`;
      ctx.fillStyle = st.color;
      const text = el instanceof HTMLSelectElement ? (el.selectedOptions[0]?.text ?? "") : el.value;
      ctx.fillText(text, x + 2, y + r.height / 2 + parseFloat(st.fontSize) / 3);
      return;
    }
    for (const n of Array.from(el.childNodes)) {
      if (n.nodeType === Node.ELEMENT_NODE) walk(n as Element);
      else if (n.nodeType === Node.TEXT_NODE && n.textContent && n.textContent.trim()) {
        // One rectangle per rendered line of this text node; draw the text into each line box.
        const range = document.createRange();
        range.selectNodeContents(n);
        const rects = Array.from(range.getClientRects());
        ctx.font = `${st.fontStyle} ${st.fontWeight} ${st.fontSize} ${st.fontFamily}`;
        ctx.fillStyle = st.color;
        const text = n.textContent.replace(/\s+/g, " ");
        if (rects.length === 1) ctx.fillText(text, rects[0].left - box.left, rects[0].bottom - box.top - rects[0].height * 0.22);
        else {
          // Wrapped text: split it word by word across the line boxes by measured width.
          const words = text.split(" ");
          let w = 0;
          for (const lr of rects) {
            let line = "";
            while (w < words.length && ctx.measureText(line + words[w]).width <= lr.width + 1) line += words[w++] + " ";
            ctx.fillText(line, lr.left - box.left, lr.bottom - box.top - lr.height * 0.22);
          }
        }
      }
    }
  };
  walk(root);
  return cv;
}

const toBlob = (cv: HTMLCanvasElement) => new Promise<Blob>((ok, no) => cv.toBlob((b) => (b ? ok(b) : no(new Error("PNG ENCODE FAILED"))), "image/png"));

/** File name: OpenTerm_<FUNCTION>_<SYMBOL>_<YYYYMMDD-HHMMSS>.png (local time). */
function fileName(id: number): string {
  const p = workspace.get().panels[id];
  const v = p ? currentView(p) : undefined;
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  const stamp = `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
  return ["OpenTerm", v?.fn, v?.security?.symbol, stamp].filter(Boolean).join("_").replace(/[^A-Za-z0-9_.-]/g, "-") + ".png";
}

/** `GRAB [SAVE | VIA TG,EMAIL]` on panel `id`. */
export async function grabCommand(id: number, args: string[]): Promise<void> {
  const el = document.querySelector<HTMLElement>(`[data-panel="${id}"]`);
  if (!el) return void fail(`NO PANEL ${id} ON SCREEN`);
  const word = (args[0] ?? "").toUpperCase();
  try {
    const cv = capture(el);
    const blob = await toBlob(cv);
    const name = fileName(id);
    if (word === "SAVE") {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = name;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 10_000);
      return void info(`SAVED ${name}`);
    }
    if (word === "VIA") {
      const via = (args[1] ?? "").toUpperCase().split(",").filter(Boolean);
      if (!via.length) return void fail("GRAB VIA TG,EMAIL (CHANNELS SET UP IN DLVR)");
      const b64 = cv.toDataURL("image/png").split(",", 2)[1];
      const r = await deliveryApi.sendPicture(via, name, b64);
      return void info(`PICTURE ${name}: ${r.results.map((x) => `${x.channel} ${x.status}`).join(", ")}`);
    }
    if (word) return void fail("GRAB [SAVE | VIA TG,EMAIL]");
    // Copy needs a secure page (localhost counts) and the browser's clipboard permission.
    await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
    info(`PANEL ${id} COPIED AS A PICTURE · GRAB SAVE DOWNLOADS IT`);
  } catch (e) {
    fail(`GRAB FAILED: ${e instanceof Error ? e.message : String(e)}`);
  }
}
