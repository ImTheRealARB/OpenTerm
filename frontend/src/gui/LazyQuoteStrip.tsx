import { useEffect, useState, type ComponentProps } from "react";

/**
 * QuoteStrip loaded as its own chunk (it pulls in the quote-row helpers and the live-tick readers, which only GUI panels
 * with a security need). Same approach as LazyPanelToolbar: no React.lazy/Suspense (it delays a reveal by ~300 ms); until the
 * chunk arrives we render an empty strip of the same height so the panel body does not jump.
 */
type Props = ComponentProps<typeof import("./QuoteStrip").QuoteStrip>;
type Comp = (p: Props) => React.ReactElement;

let loaded: Comp | undefined;
let loading: Promise<void> | undefined;

function load(): Promise<void> {
  loading ??= import("./QuoteStrip").then((m) => {
    loaded = m.QuoteStrip as Comp;
  });
  return loading;
}

export function LazyQuoteStrip(props: Props) {
  const [Comp, setComp] = useState<Comp | undefined>(() => loaded); // wrapped: a bare function value would be called as a lazy initializer
  useEffect(() => {
    if (Comp) return;
    let alive = true;
    // A failed download is left to the next mount to retry.
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
  return Comp ? <Comp {...props} /> : <div className="qs" aria-hidden="true" />;
}
