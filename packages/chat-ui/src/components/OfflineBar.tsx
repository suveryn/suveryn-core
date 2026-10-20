/**
 * The server can't be reached (docs/design/sidebar.md §5, artboard 09): a bar at the top of the pane
 * that says so, that nothing is lost, when sūveryn tries again, and *Try now*. The composer keeps the
 * typed text and says why it can't send (App.tsx). The title is announced once; the countdown isn't.
 */
import { RefreshCw, WifiOff } from "lucide-react";
import { useEffect, useState } from "react";
import { useT } from "../i18n";
import { Button } from "../ui";

export function OfflineBar({ nextCheck, onTryNow }: { nextCheck: number; onTryNow: () => void }) {
  const m = useT();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  const seconds = Math.max(0, Math.ceil((nextCheck - now) / 1000));
  return (
    <div className="offline-bar">
      <WifiOff size={18} aria-hidden />
      <p className="offline-bar-text">
        <strong role="alert">{m.offlineTitle}</strong> {m.offlineKept} <span>{m.offlineRetry(seconds)}</span>
      </p>
      <Button size="small" onPress={onTryNow}><RefreshCw size={14} aria-hidden /> {m.tryNow}</Button>
    </div>
  );
}
