import { useState, useEffect } from 'react';

// Current time in ms, refreshed on an interval, so "updated 3m ago" labels
// keep ticking without any data being refetched.
export default function useNow(intervalMs = 30000) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);

  return now;
}
