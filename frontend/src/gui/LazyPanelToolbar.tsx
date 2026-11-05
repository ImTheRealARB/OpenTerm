import { useEffect, useState, type ComponentProps } from "react";

/**
 * PanelToolbar loaded as its own chunk. It imports gpArgs, the indicator list and the chart types, which made the
 * startup file ~3 KB gzip bigger for a row of buttons that only GUI mode shows.
 *
 * Same idea as LazyGui.tsx (no React.lazy/Suspense: it delays reveals by ~300 ms), but this one passes props through.
 * Until the chunk arrives we render an empty `.pt` row, which has the same min-height, border and padding as the real
 * toolbar, so the panel body does not jump when the buttons appear.
 */
type Props = ComponentProps<typeof import("./PanelToolbar").PanelToolbar>;
type Comp = (p: Props) => React.ReactElement;

// Remembered once downloaded, so every later panel renders the toolbar on its first frame.
let loaded: Comp | undefined;
let loading: Promise<void> | undefined;

function load(): Promise<void> {
  loading ??= import("./PanelToolbar").then((m) => {
    loaded = m.PanelToolbar as Comp;
  });
  return loading;
}

export function LazyPanelToolbar(props: Props) {
  const [Comp, setComp] = useState<Comp | undefined>(() => loaded); // wrapped: a bare function value would be called as a lazy initializer
  useEffect(() => {
    if (Comp) return;
    let alive = true;
    // A failed download is left to the next mount to retry: forget the rejected promise.
    void load().then(
      () => alive && setComp(() => loaded),
      () => {
        loading = undefined;
      },
    );
    return () => {
      alive = false;
    };
  }, [Comp]);
  return Comp ? <Comp {...props} /> : <div className="pt" aria-hidden="true" />;
}
