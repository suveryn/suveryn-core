/**
 * Administration (docs/design/admin.md): a side menu in two groups, *Office* and *Appliance*, instead of the
 * tabs that no longer fit (artboard 30). The active item has an ink bar on its left and bold text: navigation,
 * never orange. A triangle beside an item that needs attention. *Status* opens first.
 *
 * Narrow screens (artboard 42): the menu is the first page, a list with the same groups; every page has a back
 * arrow to it.
 *
 * Administrators only: the gateway answers 403 to anyone else on every /v1/admin route.
 */
import {
  AlertTriangle, ArrowLeft, BarChart3, ChevronRight, ClipboardList, Folder, Gauge, HardDrive, Shield, Users,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { getBackups, type BackupStatus } from "../api";
import { useT } from "../i18n";
import { backupAttention } from "../lib/backups";
import { IconButton, NARROW, useMedia } from "../ui";
import { AdminBackups } from "./AdminBackups";
import { AdminCases } from "./AdminCases";
import { AdminPlaybooks } from "./AdminPlaybooks";
import { AdminStatus } from "./AdminStatus";
import { AdminUsers } from "./AdminUsers";
import { AdminUsage } from "./UsageView";

/** The pages built so far; Users, Settings, Updates and models, Network and Licence join as they are built. */
export type AdminPage = "status" | "users" | "cases" | "playbooks" | "usage" | "backups";

type Item = { id: AdminPage; label: string; icon: ReactNode; mark?: ReactNode };

export function AdminView({ me, onBack, initialPage, onLostAdministration }: {
  /** The administrator's own account id (Users: not their own account off). */
  me: string; onBack: () => void; initialPage?: AdminPage;
  /** They removed their own administrator rights: Administration closes for them. */
  onLostAdministration: () => void;
}) {
  const m = useT();
  const narrow = useMedia(NARROW);
  // On a narrow screen null is the menu itself; on a wide one the menu is always there and null is Status.
  const [page, setPage] = useState<AdminPage | null>(initialPage ?? null);
  useEffect(() => { setPage(initialPage ?? null); }, [initialPage]);
  const [backups, setBackups] = useState<BackupStatus | null>(null);
  useEffect(() => { getBackups().then(setBackups).catch(() => setBackups(null)); }, [page]);
  const attention = backupAttention(backups) !== null;

  const groups: { heading: string; items: Item[] }[] = [
    { heading: m.adminOffice, items: [
      { id: "users", label: m.adminUsers, icon: <Users size={16} aria-hidden /> },
      { id: "cases", label: m.adminCases, icon: <Folder size={16} aria-hidden /> },
      { id: "playbooks", label: m.adminPlaybooks, icon: <ClipboardList size={16} aria-hidden /> },
      { id: "usage", label: m.adminUsage, icon: <BarChart3 size={16} aria-hidden /> },
    ] },
    { heading: m.adminAppliance, items: [
      { id: "status", label: m.adminStatus, icon: <Gauge size={16} aria-hidden /> },
      { id: "backups", label: m.adminBackups, icon: <HardDrive size={16} aria-hidden />,
        mark: attention ? <AlertTriangle size={14} aria-label={m.needsAttention} /> : undefined },
    ] },
  ];
  const shown: AdminPage | null = page ?? (narrow ? null : "status");
  const title = groups.flatMap((g) => g.items).find((i) => i.id === shown)?.label ?? m.administration;

  const menu = (
    <nav className="admin-menu" aria-label={m.administration}>
      {groups.map((g) => (
        <div key={g.heading} className="admin-menu-group">
          <h2 className="admin-menu-heading">{g.heading}</h2>
          <ul>
            {g.items.map((i) => (
              <li key={i.id}>
                <button type="button" className="admin-menu-item" aria-current={shown === i.id ? "page" : undefined}
                        onClick={() => setPage(i.id)}>
                  {i.icon}<span className="admin-menu-label">{i.label}</span>
                  {i.mark && <span className="admin-menu-mark">{i.mark}</span>}
                  {narrow && <ChevronRight size={16} aria-hidden className="admin-menu-chevron" />}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  );

  const body = shown === "status" ? <AdminStatus onOpen={setPage} />
    : shown === "users" ? <AdminUsers me={me} onLostAdministration={onLostAdministration} />
    : shown === "cases" ? <AdminCases />
    : shown === "playbooks" ? <AdminPlaybooks />
    : shown === "usage" ? <AdminUsage />
    : shown === "backups" ? <AdminBackups /> : null;

  return (
    <section className="admin" data-narrow={narrow || undefined}>
      {/* On a narrow screen the app's top bar already says Administration: a header only on a page, back to the menu. */}
      {(!narrow || shown !== null) && (
        <header className="admin-head">
          {narrow
            ? <IconButton label={m.administration} onPress={() => setPage(null)}><ArrowLeft size={18} aria-hidden /></IconButton>
            : <IconButton label={m.backToChat} onPress={onBack}><ArrowLeft size={18} aria-hidden /></IconButton>}
          <h1>{narrow ? title : <><Shield size={18} aria-hidden /> {m.administration}</>}</h1>
        </header>
      )}
      <div className="admin-body">
        {(!narrow || shown === null) && menu}
        {shown !== null && (
          <div className="admin-page view">
            {!narrow && <h1 className="admin-page-title">{title}</h1>}
            {body}
          </div>
        )}
      </div>
    </section>
  );
}
