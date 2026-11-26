/** Follows a Phase 27 SCAN / MRR task: polls it once a second until it is done or failed (the server keeps no socket
 * channel for these tasks; a cold scan of 500 names takes about a minute, so one small GET a second is cheap). */
import { useEffect, useState } from "react";
import type { ScanTask } from "../net/types";
import { errText } from "../net/errText";

export function useTaskPoll<R>(start: (() => Promise<ScanTask<R>>) | null, poll: (id: string) => Promise<ScanTask<R>>, key: unknown) {
  const [task, setTask] = useState<ScanTask<R> | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setTask(null);
    setError(null);
    if (!start) return;
    let stop = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const follow = (t: ScanTask<R>) => {
      if (stop) return;
      setTask(t);
      if (t.state === "done" || t.state === "error") return;
      timer = setTimeout(() => poll(t.id).then(follow, (e) => !stop && setError(errText(e))), 1000);
    };
    start().then(follow, (e) => !stop && setError(errText(e)));
    return () => {
      stop = true;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `key` identifies the command; start/poll are new closures each render
  }, [key]);
  return { task, error };
}
