import { useEffect, useState, type FormEvent } from "react";
import { Bot, Building2, History, ShieldCheck, Trash2, User as UserIcon, UserPlus } from "lucide-react";
import { Badge, Button, Card, ConfirmDialog, ErrorNote, Field, Notice, Select, TableSkeleton, Tabs } from "../components/ui";
import { api } from "../lib/api";
import { useAuth, useToast } from "../lib/context";
import { formatDate, formatDateTime } from "../lib/format";
import { useAsync } from "../lib/hooks";
import type { AIStatus, AuditEntry, Member, User, WorkspaceRef } from "../lib/types";

type Tab = "profile" | "workspace" | "ai" | "audit";

function ProfileTab() {
  const { user, setUser } = useAuth();
  const toast = useToast();
  const [name, setName] = useState(user?.full_name ?? "");
  const [passwords, setPasswords] = useState({ current_password: "", new_password: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const saveName = async (event: FormEvent) => {
    event.preventDefault();
    try {
      setUser(await api.patch<User>("/auth/me", { full_name: name }));
      toast("Profile updated.");
    } catch (caught) {
      toast((caught as Error).message, "error");
    }
  };
  const savePassword = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/auth/change-password", passwords);
      setPasswords({ current_password: "", new_password: "" });
      toast("Password changed. Other devices have been signed out.");
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <Card title="Profile">
        <form onSubmit={saveName} className="space-y-3">
          <Field label="Full name"><input className="field" required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <Field label="Email" hint="Email is used to sign in and cannot be changed here."><input className="field" disabled value={user?.email ?? ""} /></Field>
          <p className="text-xs text-muted">Member since {formatDate(user?.created_at)}</p>
          <Button type="submit" variant="primary">Save profile</Button>
        </form>
      </Card>
      <Card title="Change password">
        <form onSubmit={savePassword} className="space-y-3">
          {error && <ErrorNote message={error} />}
          <Field label="Current password"><input className="field" type="password" autoComplete="current-password" required value={passwords.current_password} onChange={(e) => setPasswords({ ...passwords, current_password: e.target.value })} /></Field>
          <Field label="New password" hint="At least 10 characters, mixing letters with numbers or symbols."><input className="field" type="password" autoComplete="new-password" required minLength={10} value={passwords.new_password} onChange={(e) => setPasswords({ ...passwords, new_password: e.target.value })} /></Field>
          <Button type="submit" variant="primary" loading={busy}>Change password</Button>
        </form>
      </Card>
    </div>
  );
}

function WorkspaceTab() {
  const { workspace, canAdmin, refreshUser, switchWorkspace, workspaceKey, user } = useAuth();
  const toast = useToast();
  const members = useAsync(() => api.get<Member[]>("/workspaces/current/members"), [workspaceKey]);
  const [name, setName] = useState(workspace?.name ?? "");
  const [newName, setNewName] = useState("");
  const [invite, setInvite] = useState({ email: "", role: "member" });
  const [toRemove, setToRemove] = useState<Member | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  useEffect(() => setName(workspace?.name ?? ""), [workspace?.id, workspace?.name]);

  const handle = async (action: () => Promise<unknown>, message: string) => {
    try {
      await action();
      toast(message);
      return true;
    } catch (caught) {
      toast((caught as Error).message, "error");
      return false;
    }
  };

  return (
    <div className="space-y-3">
      <div className="grid gap-3 lg:grid-cols-2">
        <Card title="Current workspace" subtitle={`Your role: ${workspace?.role}`}>
          <form className="flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); void handle(async () => { await api.patch("/workspaces/current", { name }); await refreshUser(); }, "Workspace renamed."); }}>
            <div className="flex-1"><Field label="Name"><input className="field" required maxLength={120} disabled={!canAdmin} value={name} onChange={(e) => setName(e.target.value)} /></Field></div>
            {canAdmin && <Button type="submit">Rename</Button>}
          </form>
          {workspace?.role === "owner" && (user?.workspaces.length ?? 0) > 1 && <Button className="mt-3" size="sm" variant="ghost" icon={Trash2} onClick={() => setDeleteOpen(true)}>Delete workspace</Button>}
        </Card>
        <Card title="Create a workspace" subtitle="Each workspace keeps its data separate.">
          <form className="flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); void handle(async () => { const created = await api.post<WorkspaceRef>("/workspaces", { name: newName }); await refreshUser(); switchWorkspace(created.id); setNewName(""); }, "Workspace created."); }}>
            <div className="flex-1"><Field label="Name"><input className="field" required maxLength={120} value={newName} onChange={(e) => setNewName(e.target.value)} /></Field></div>
            <Button type="submit" variant="primary">Create</Button>
          </form>
        </Card>
      </div>
      <Card title="Members" subtitle="Viewers can read. Members can analyse and edit data. Admins also manage members and connections." bodyClass="overflow-x-auto">
        {canAdmin && (
          <form className="flex flex-wrap items-end gap-2 border-b border-line p-3" onSubmit={(e) => { e.preventDefault(); void handle(async () => { await api.post("/workspaces/current/members", invite); setInvite({ email: "", role: "member" }); await members.reload(true); }, "Member added."); }}>
            <div className="min-w-[220px] flex-1"><Field label="Email of a registered user"><input className="field" type="email" required value={invite.email} onChange={(e) => setInvite({ ...invite, email: e.target.value })} /></Field></div>
            <div className="w-32"><Field label="Role"><Select value={invite.role} onChange={(e) => setInvite({ ...invite, role: e.target.value })}><option value="viewer">Viewer</option><option value="member">Member</option><option value="admin">Admin</option></Select></Field></div>
            <Button type="submit" icon={UserPlus}>Add member</Button>
          </form>
        )}
        {members.loading && !members.data ? <TableSkeleton rows={2} /> : (
          <table className="data-table">
            <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Joined</th><th /></tr></thead>
            <tbody>
              {members.data?.map((m) => (
                <tr key={m.id}>
                  <td className="font-medium">{m.full_name}{m.user_id === user?.id && <span className="ml-1 text-xs text-faint">(you)</span>}</td>
                  <td className="text-muted">{m.email}</td>
                  <td>
                    {canAdmin && m.role !== "owner" && m.user_id !== user?.id ? (
                      <Select aria-label={`Role for ${m.full_name}`} className="!h-7 !w-28 text-xs" value={m.role} onChange={(e) => void handle(async () => { await api.patch(`/workspaces/current/members/${m.id}`, { role: e.target.value }); await members.reload(true); }, "Role updated.")}>
                        <option value="viewer">Viewer</option><option value="member">Member</option><option value="admin">Admin</option>
                      </Select>
                    ) : <Badge tone={m.role === "owner" ? "blue" : "neutral"}>{m.role}</Badge>}
                  </td>
                  <td className="text-muted">{formatDate(m.joined_at)}</td>
                  <td className="text-right">{canAdmin && m.role !== "owner" && m.user_id !== user?.id && <button aria-label={`Remove ${m.full_name}`} className="rounded p-1.5 text-muted hover:bg-bad/20 hover:text-red-300" onClick={() => setToRemove(m)}><Trash2 size={14} /></button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      <ConfirmDialog open={!!toRemove} danger title="Remove this member?" confirmLabel="Remove member" body={<>{toRemove?.full_name} will lose access to this workspace.</>} onClose={() => setToRemove(null)} onConfirm={() => { void handle(async () => { await api.delete(`/workspaces/current/members/${toRemove?.id}`); setToRemove(null); await members.reload(true); }, "Member removed."); }} />
      <ConfirmDialog open={deleteOpen} danger title="Delete this workspace?" confirmLabel="Delete workspace" body={<>This permanently deletes <strong className="text-ink">{workspace?.name}</strong> and all of its datasets, files, reports, and connections.</>} onClose={() => setDeleteOpen(false)} onConfirm={() => { void handle(async () => { await api.delete("/workspaces/current"); setDeleteOpen(false); const me = await api.get<User>("/auth/me").catch(() => null); const next = user?.workspaces.find((w) => w.id !== workspace?.id); if (next) switchWorkspace(next.id); if (me) await refreshUser(); }, "Workspace deleted."); }} />
    </div>
  );
}

function AITab() {
  const { data, error } = useAsync(() => api.get<AIStatus>("/analyst/status"), []);
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <Card title="AI provider">
        {error && <ErrorNote message={error} />}
        {data && (
          <div className="space-y-3 text-[13px]">
            <p className="flex items-center gap-2">Status <Badge tone={data.mode === "live" ? "cyan" : "violet"}>{data.mode === "live" ? "Live AI" : "Demonstration mode"}</Badge></p>
            {data.mode === "live" && <p>Provider: <strong>{data.provider}</strong>, model: <strong>{data.model}</strong></p>}
            {data.problem && <Notice tone="warn">{data.problem}</Notice>}
            <p className="text-muted">API keys are set by the server administrator in the server's environment. They are never sent to the browser. Use <code className="rounded bg-raised px-1">AI_PROVIDER</code> with <code className="rounded bg-raised px-1">ANTHROPIC_API_KEY</code>, <code className="rounded bg-raised px-1">OPENAI_API_KEY</code>, or <code className="rounded bg-raised px-1">GEMINI_API_KEY</code>.</p>
          </div>
        )}
      </Card>
      <Card title="What is shared with an AI provider" actions={<ShieldCheck size={15} className="text-good" />}>
        <ul className="list-disc space-y-1.5 pl-4 text-[13px] text-slate-300 marker:text-faint">
          <li>In demonstration mode, nothing leaves this server.</li>
          <li>In live mode, the provider receives the question, column names and types, date ranges, and the row count.</li>
          <li>Up to 15 common labels per category column are also shared unless <code className="rounded bg-raised px-1">AI_SHARE_CATEGORY_VALUES</code> is false{data?.mode === "live" ? ` (currently ${data.shares_category_values ? "on" : "off"})` : ""}.</li>
          <li>To write the explanation, it receives up to 40 aggregated result rows.</li>
          <li>Raw dataset records are not sent. Results such as "top products" are aggregates, but their labels can be sensitive, so review your provider's data terms.</li>
        </ul>
      </Card>
    </div>
  );
}

function AuditTab() {
  const { workspaceKey } = useAuth();
  const { data, loading, error } = useAsync(() => api.get<AuditEntry[]>("/audit-logs?limit=200"), [workspaceKey]);
  return (
    <Card title="Audit log" subtitle="Recent operations in this workspace. Entries hold identifiers and counts, not dataset contents." bodyClass="max-h-[70vh] overflow-auto">
      {error && <div className="p-3"><ErrorNote message={error} /></div>}
      {loading && !data ? <TableSkeleton /> : (
        <table className="data-table">
          <thead><tr><th>Time</th><th>User</th><th>Action</th><th>Detail</th><th>IP address</th></tr></thead>
          <tbody>
            {data?.map((entry) => (
              <tr key={entry.id}>
                <td className="text-muted">{formatDateTime(entry.created_at)}</td>
                <td className="text-muted">{entry.user_email ?? "-"}</td>
                <td className="font-mono text-xs">{entry.action}</td>
                <td className="max-w-[320px] truncate font-mono text-xs text-muted" title={JSON.stringify(entry.detail)}>{Object.keys(entry.detail ?? {}).length ? JSON.stringify(entry.detail) : "-"}</td>
                <td className="text-muted">{entry.ip_address ?? "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

export default function SettingsPage() {
  const { canAdmin } = useAuth();
  const [tab, setTab] = useState<Tab>("profile");
  const tabs: { id: Tab; label: string; icon: typeof UserIcon }[] = [
    { id: "profile", label: "Account", icon: UserIcon },
    { id: "workspace", label: "Workspace", icon: Building2 },
    { id: "ai", label: "AI and privacy", icon: Bot },
    ...(canAdmin ? [{ id: "audit" as Tab, label: "Audit log", icon: History }] : []),
  ];
  return (
    <div className="space-y-3">
      <Tabs tabs={tabs} value={tab} onChange={setTab} />
      {tab === "profile" && <ProfileTab />}
      {tab === "workspace" && <WorkspaceTab />}
      {tab === "ai" && <AITab />}
      {tab === "audit" && <AuditTab />}
    </div>
  );
}
