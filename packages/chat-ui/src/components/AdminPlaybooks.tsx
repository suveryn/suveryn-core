/**
 * Administration › Playbooks (docs/design/admin.md): every installed playbook with a switch.
 * Off, it leaves every case's composer menu and can't be started; runs already made stay. The
 * switch applies at once (PUT /v1/admin/playbooks/{slug}); a failure shows and the switch goes back.
 */
import { AlertCircle, AlertTriangle, Check } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { listAdminPlaybooks, setPlaybookActive, type PlaybookInfo } from "../api";
import { useT } from "../i18n";
import { caseTypeLabel } from "./CaseDialogs";
import { InlineNotice, Switch } from "../ui";

export function AdminPlaybooks() {
  const m = useT();
  const [playbooks, setPlaybooks] = useState<PlaybookInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(async () => {
    try { setPlaybooks(await listAdminPlaybooks()); setError(null); } catch (e) { setError((e as Error).message); }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);
  const flip = async (p: PlaybookInfo, active: boolean) => {
    setPlaybooks((ps) => ps && ps.map((x) => (x.id === p.id ? { ...x, active } : x)));
    try { const changed = await setPlaybookActive(p.slug, active); setPlaybooks((ps) => ps && ps.map((x) => (x.id === p.id ? changed : x))); setError(null); }
    catch (e) { setError(m.playbookChangeFailed((e as Error).message)); refresh(); }
  };
  return (
    <>
      <p className="view-intro">{m.adminPlaybooksIntro}</p>
      {error && <InlineNotice icon={<AlertCircle size={14} />} tone="error" alert>{error}</InlineNotice>}
      {playbooks && playbooks.length === 0 && <p className="caption">{m.playbooksEmpty}</p>}
      {playbooks && playbooks.length > 0 && (
        <ul className="item-list">
          {playbooks.map((p) => (
            <li key={p.id} className="item item-static">
              <span className="item-open">
                <span className="item-name">{p.name} <span className="item-dim">{p.version} · {p.pack}</span></span>
                <span className="item-meta">{m.playbookFor((p.case_types ?? []).map((t) => caseTypeLabel(t, m)).join(", "))} · {p.covered
                  ? <span className="status-ok"><Check size={13} aria-hidden /> {m.covered}</span>
                  : <span className="status-warn"><AlertTriangle size={13} aria-hidden /> {m.notCovered}</span>}</span>
              </span>
              <Switch label={m.playbookActive} checked={p.active !== false} onChange={(v) => flip(p, v)} />
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
