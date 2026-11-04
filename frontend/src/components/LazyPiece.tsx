import { useEffect, useState, type ComponentType } from "react";

/**
 * Renders a component that lives in its own chunk (kept out of the startup bundle).
 * No React.lazy/Suspense on purpose (Suspense delays a reveal by ~300 ms, see CLAUDE.md): we call the loader
 * ourselves, remember the result in `cache`, and render nothing until the chunk has arrived.
 * Pieces that are usually opened by a key press are also fetched while the browser is idle (see main.tsx),
 * so by the time a person asks for them the chunk is normally already here.
 */
type Loader = () => Promise<ComponentType>;

// Already downloaded components, keyed by their loader function, so a second open is synchronous.
const cache = new Map<Loader, ComponentType>();

export function LazyPiece({ load }: { load: Loader }) {
  const [Comp, setComp] = useState<ComponentType | undefined>(() => cache.get(load));
  useEffect(() => {
    if (Comp) return;
    let alive = true;
    load()
      .then((c) => {
        cache.set(load, c);
        if (alive) setComp(() => c); // `() => c` because setState would call a bare component as an updater
      })
      .catch(() => {}); // a failed download: nothing shows, the next open retries
    return () => {
      alive = false;
    };
  }, [Comp, load]);
  return Comp ? <Comp /> : null;
}
