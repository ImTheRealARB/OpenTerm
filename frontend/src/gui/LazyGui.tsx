import { useEffect, useState, type ComponentType } from "react";
import { useStore } from "../state/store";
import { helpDrawer } from "./helpState";
import { onboarding } from "./onboarding";

/**
 * GUI pieces that are not visible at first paint (help drawer, welcome card, tour) are separate chunks.
 * We do NOT use React.lazy/Suspense here (Suspense delays a reveal by ~300 ms, see CLAUDE.md): the chunk is
 * fetched with a plain import(), remembered in `done`, and the component is rendered once it has arrived.
 * Each piece also preloads when the browser is idle, so the first real open is usually instant.
 */
type Loader = () => Promise<ComponentType>;

// Components already downloaded, keyed by their loader function.
const done = new Map<Loader, ComponentType>();

function makeLazy(load: Loader, wanted: () => boolean): ComponentType {
  return function LazyPiece() {
    const want = wanted();
    const [Comp, setComp] = useState<ComponentType | undefined>(() => done.get(load));
    useEffect(() => {
      if (Comp) return;
      let alive = true;
      const fetchIt = () =>
        void load()
          .then((c) => {
            done.set(load, c);
            if (alive) setComp(() => c);
          })
          .catch(() => {}); // a failed download: the piece simply stays closed, a later open retries
      if (want) {
        fetchIt();
        return () => {
          alive = false;
        };
      }
      // Not needed yet: fetch while idle.
      const idle = window.requestIdleCallback ?? ((cb: () => void) => window.setTimeout(cb, 300));
      idle(fetchIt);
      return () => {
        alive = false;
      };
    }, [Comp, want]);
    return Comp ? <Comp /> : null;
  };
}

const loadHelp: Loader = () => import("./HelpDrawer").then((m) => m.HelpDrawer);
const loadWelcome: Loader = () => import("./Welcome").then((m) => m.Welcome);
const loadTour: Loader = () => import("./Tour").then((m) => m.Tour);

export const LazyHelpDrawer = makeLazyWithStore(loadHelp, () => !!useStore(helpDrawer, (s) => s));
export const LazyWelcome = makeLazyWithStore(loadWelcome, () => useStore(onboarding, (s) => s.welcome));
export const LazyTour = makeLazyWithStore(loadTour, () => useStore(onboarding, (s) => s.tour !== null));

// `wanted` calls a hook, so it must run inside the component; this alias just documents that.
function makeLazyWithStore(load: Loader, wanted: () => boolean): ComponentType {
  return makeLazy(load, wanted);
}
