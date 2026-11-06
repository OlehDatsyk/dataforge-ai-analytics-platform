import { Suspense, useCallback, useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  AlertOctagon, BarChart3, Bell, Bot, Brush, ChevronDown, Database, FileText, FolderOpen, LayoutDashboard, LogOut, Menu, PlugZap, Search, Settings, Table2, UserCog, X, type LucideIcon,
} from "lucide-react";
import { api } from "../lib/api";
import { useAuth, useDatasets, useToast } from "../lib/context";
import { timeAgo } from "../lib/format";
import { useAsync, useClickOutside, useDebounced, useInterval } from "../lib/hooks";
import type { NotificationItem } from "../lib/types";
import { Badge, Select, Skeleton, cx } from "./ui";

interface NavItem { to: string; label: string; icon: LucideIcon; usesDataset?: boolean }
const NAV: NavItem[] = [
  { to: "/", label: "Overview", icon: LayoutDashboard },
  { to: "/datasets", label: "My Datasets", icon: FolderOpen },
  { to: "/explorer", label: "Data Explorer", icon: Table2, usesDataset: true },
  { to: "/analyst", label: "AI Data Analyst", icon: Bot, usesDataset: true },
  { to: "/visualisations", label: "Visualisations", icon: BarChart3, usesDataset: true },
  { to: "/cleaning", label: "Data Cleaning", icon: Brush, usesDataset: true },
  { to: "/anomalies", label: "Anomaly Detection", icon: AlertOctagon, usesDataset: true },
  { to: "/reports", label: "Reports", icon: FileText },
  { to: "/connections", label: "Data Connections", icon: PlugZap },
  { to: "/settings", label: "Settings", icon: Settings },
];

export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <span className="flex items-center gap-2">
      <span className="flex h-7 w-7 items-center justify-center rounded-md border border-line bg-surface">
        <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M5 19v-7M10 19V7M15 19v-5M20 19V9" stroke="#3B82F6" strokeWidth="2.4" strokeLinecap="round" fill="none" /><circle cx="20" cy="4.5" r="1.8" fill="#22D3EE" /></svg>
      </span>
      {!compact && <span className="text-sm font-semibold tracking-tight">DataForge <span className="text-accent">AI</span></span>}
    </span>
  );
}

function initials(name: string) {
  return name.split(/\s+/).map((p) => p[0]).slice(0, 2).join("").toUpperCase();
}

function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { user, workspace, switchWorkspace, logout } = useAuth();
  const navigate = useNavigate();
  const { search } = useLocation();
  const keepDataset = new URLSearchParams(search).get("dataset");
  return (
    <>
      {open && <div className="fixed inset-0 z-30 bg-black/50 lg:hidden" onClick={onClose} />}
      <aside className={cx("fixed inset-y-0 left-0 z-40 flex w-56 flex-col border-r border-line bg-sidebar transition-transform lg:translate-x-0", open ? "translate-x-0" : "-translate-x-full")}>
        <div className="flex h-12 items-center justify-between border-b border-line px-3.5">
          <Link to="/" onClick={onClose}><Logo /></Link>
          <button aria-label="Close menu" className="text-muted lg:hidden" onClick={onClose}><X size={16} /></button>
        </div>
        <nav aria-label="Main" className="flex-1 space-y-0.5 overflow-y-auto p-2">
          {NAV.map(({ to, label, icon: Icon, usesDataset }) => (
            <NavLink key={to} to={usesDataset && keepDataset ? `${to}?dataset=${keepDataset}` : to} end={to === "/"} onClick={onClose}
              className={({ isActive }) => cx("flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] font-medium transition-colors", isActive ? "bg-primary-soft text-blue-200" : "text-muted hover:bg-surface hover:text-ink")}>
              <Icon size={15} />{label}
            </NavLink>
          ))}
        </nav>
        <div className="space-y-2 border-t border-line p-2.5">
          <label className="block">
            <span className="mb-1 block px-0.5 text-2xs font-medium uppercase tracking-wide text-faint">Workspace</span>
            <Select aria-label="Workspace" value={workspace?.id ?? ""} onChange={(e) => { switchWorkspace(e.target.value); navigate("/"); onClose(); }}>
              {user?.workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </Select>
          </label>
          <div className="flex items-center gap-2 rounded-md px-1 py-1">
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-raised text-2xs font-semibold text-blue-200">{initials(user?.full_name ?? "?")}</span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-medium">{user?.full_name}</p>
              <p className="truncate text-2xs text-faint">{user?.email}</p>
            </div>
            <Link aria-label="Account settings" title="Account settings" to="/settings" onClick={onClose} className="rounded p-1 text-faint hover:bg-surface hover:text-ink"><UserCog size={14} /></Link>
            <button aria-label="Log out" title="Log out" onClick={() => void logout()} className="rounded p-1 text-faint hover:bg-surface hover:text-ink"><LogOut size={14} /></button>
          </div>
        </div>
      </aside>
    </>
  );
}

function GlobalSearch() {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const debounced = useDebounced(query, 250);
  const navigate = useNavigate();
  const close = useCallback(() => setOpen(false), []);
  const ref = useClickOutside(close);
  const { data, loading } = useAsync(() => (debounced.trim().length >= 2 ? api.get<{ type: string; title: string; link: string }[]>(`/search?q=${encodeURIComponent(debounced.trim())}`) : Promise.resolve([])), [debounced]);
  return (
    <div ref={ref} className="relative hidden w-56 md:block xl:w-72">
      <Search size={14} className="pointer-events-none absolute left-2.5 top-2 text-faint" />
      <input aria-label="Search the workspace" className="field !pl-8" placeholder="Search datasets, reports, charts..." value={query} onFocus={() => setOpen(true)} onChange={(e) => { setQuery(e.target.value); setOpen(true); }} />
      {open && query.trim().length >= 2 && (
        <div className="absolute right-0 top-9 z-40 max-h-80 w-80 overflow-auto rounded-lg border border-line bg-raised p-1 shadow-pop">
          {loading && <Skeleton className="m-1 h-6" />}
          {!loading && !data?.length && <p className="px-3 py-3 text-xs text-muted">No matches in this workspace.</p>}
          {data?.map((item) => (
            <button key={`${item.type}-${item.link}`} className="flex w-full items-center justify-between gap-2 rounded px-2.5 py-1.5 text-left text-[13px] hover:bg-surface" onClick={() => { setOpen(false); setQuery(""); navigate(item.link); }}>
              <span className="truncate">{item.title}</span><Badge>{item.type}</Badge>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function Notifications() {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const { workspaceKey } = useAuth();
  const close = useCallback(() => setOpen(false), []);
  const ref = useClickOutside(close);
  const { data, reload } = useAsync(() => api.get<{ unread: number; items: NotificationItem[] }>("/notifications"), [workspaceKey]);
  useInterval(() => void reload(true), 20000);
  return (
    <div ref={ref} className="relative">
      <button aria-label={`Notifications${data?.unread ? `, ${data.unread} unread` : ""}`} className="relative rounded-md p-1.5 text-muted hover:bg-raised hover:text-ink" onClick={() => { setOpen(!open); void reload(true); }}>
        <Bell size={16} />
        {!!data?.unread && <span className="num absolute -right-0.5 -top-0.5 flex h-3.5 min-w-3.5 items-center justify-center rounded-full bg-primary px-0.5 text-[9px] font-semibold text-white">{data.unread > 9 ? "9+" : data.unread}</span>}
      </button>
      {open && (
        <div className="absolute right-0 top-9 z-40 w-[min(340px,calc(100vw-1.5rem))] rounded-lg border border-line bg-raised shadow-pop">
          <div className="flex items-center justify-between border-b border-line px-3 py-2">
            <h3 className="text-[13px] font-semibold">Notifications</h3>
            <button className="text-xs text-blue-300 hover:underline" onClick={async () => { await api.post("/notifications/read-all"); void reload(true); }}>Mark all read</button>
          </div>
          <div className="max-h-80 overflow-auto">
            {!data?.items.length && <p className="px-3 py-6 text-center text-xs text-muted">Nothing yet. Updates about processing and scans appear here.</p>}
            {data?.items.map((n) => (
              <button key={n.id} className="block w-full border-b border-line/60 px-3 py-2 text-left hover:bg-surface" onClick={async () => { await api.post(`/notifications/${n.id}/read`); void reload(true); setOpen(false); if (n.link) navigate(n.link); }}>
                <p className={cx("text-[13px]", n.read ? "text-muted" : "font-medium")}>{n.title}</p>
                {n.body && <p className="mt-0.5 line-clamp-2 text-xs text-faint">{n.body}</p>}
                <p className="mt-0.5 text-2xs text-faint">{timeAgo(n.created_at)}</p>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function AccountMenu() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  const ref = useClickOutside(close);
  return (
    <div ref={ref} className="relative">
      <button aria-label="Account menu" aria-expanded={open} className="flex items-center gap-1 rounded-md p-1 text-muted hover:bg-raised hover:text-ink" onClick={() => setOpen(!open)}>
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-raised text-2xs font-semibold text-blue-200">{initials(user?.full_name ?? "?")}</span>
        <ChevronDown size={12} />
      </button>
      {open && (
        <div className="absolute right-0 top-9 z-40 w-52 rounded-lg border border-line bg-raised p-1 shadow-pop">
          <div className="border-b border-line px-2.5 py-1.5"><p className="truncate text-[13px] font-medium">{user?.full_name}</p><p className="truncate text-xs text-faint">{user?.email}</p></div>
          <Link to="/settings" onClick={close} className="mt-1 flex items-center gap-2 rounded px-2.5 py-1.5 text-[13px] hover:bg-surface"><UserCog size={14} />Account settings</Link>
          <button onClick={() => void logout()} className="flex w-full items-center gap-2 rounded px-2.5 py-1.5 text-left text-[13px] hover:bg-surface"><LogOut size={14} />Log out</button>
        </div>
      )}
    </div>
  );
}

function DatasetSelector() {
  const { datasets, datasetId, setDatasetId } = useDatasets();
  const ready = datasets.filter((d) => d.status === "ready");
  if (!ready.length) return null;
  return (
    <div className="flex min-w-0 items-center gap-1.5">
      <Database size={14} className="hidden shrink-0 text-faint sm:block" />
      <Select aria-label="Active dataset" className="!h-7 !w-40 text-xs sm:!w-56" value={datasetId ?? ""} onChange={(e) => setDatasetId(e.target.value)}>
        {ready.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
      </Select>
    </div>
  );
}

export function Layout() {
  const [menuOpen, setMenuOpen] = useState(false);
  const { pathname } = useLocation();
  const { workspace } = useAuth();
  const toast = useToast();
  const current = NAV.find((n) => (n.to === "/" ? pathname === "/" : pathname.startsWith(n.to)));

  useEffect(() => {
    document.title = `${current?.label ?? "DataForge AI"} | DataForge AI`;
  }, [current]);

  useEffect(() => {
    const onRejection = (event: PromiseRejectionEvent) => {
      if (event.reason instanceof Error && event.reason.message) toast(event.reason.message, "error");
    };
    window.addEventListener("unhandledrejection", onRejection);
    return () => window.removeEventListener("unhandledrejection", onRejection);
  }, [toast]);

  return (
    <div className="min-h-screen">
      <Sidebar open={menuOpen} onClose={() => setMenuOpen(false)} />
      <div className="lg:pl-56">
        <header className="sticky top-0 z-20 flex h-12 items-center gap-3 border-b border-line bg-canvas/95 px-3 backdrop-blur sm:px-4">
          <button aria-label="Open menu" className="rounded p-1 text-muted hover:text-ink lg:hidden" onClick={() => setMenuOpen(true)}><Menu size={18} /></button>
          <h1 className="truncate text-sm font-semibold">{current?.label ?? "DataForge AI"}</h1>
          <span className="hidden truncate text-xs text-faint xl:inline">{workspace?.name}</span>
          {current?.usesDataset && <DatasetSelector />}
          <div className="ml-auto flex items-center gap-1.5">
            <GlobalSearch />
            <Notifications />
            <AccountMenu />
          </div>
        </header>
        <main className="p-3 sm:p-4">
          <Suspense fallback={<div className="space-y-3"><Skeleton className="h-24" /><Skeleton className="h-64" /></div>}>
            <Outlet />
          </Suspense>
        </main>
      </div>
    </div>
  );
}
