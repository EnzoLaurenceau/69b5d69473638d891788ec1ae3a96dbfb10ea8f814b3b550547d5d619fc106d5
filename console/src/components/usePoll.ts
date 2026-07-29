import { useEffect, useRef, useState } from "react";

// Polling léger pour les endpoints de lecture. Squelette plat côté vue pendant `loading`
// (règle DS §6 : jamais un spinner isolé). Réf. temps réel fort → WS, pas ce hook.
export function usePoll<T>(fn: () => Promise<T>, intervalMs = 4000): {
  data: T | null;
  error: unknown;
  loading: boolean;
} {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const d = await fnRef.current();
        if (alive) {
          setData(d);
          setError(null);
        }
      } catch (e) {
        if (alive) setError(e);
      } finally {
        if (alive) setLoading(false);
      }
    };
    tick();
    const id = setInterval(tick, intervalMs);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [intervalMs]);

  return { data, error, loading };
}
