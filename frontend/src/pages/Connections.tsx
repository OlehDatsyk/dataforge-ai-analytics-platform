import { useState } from "react";
import { Link } from "react-router-dom";
import { CheckCircle2, Database, Download, FileUp, Globe, KeyRound, PlugZap, Plus, ShieldCheck, TestTube2, Trash2, XCircle } from "lucide-react";
import { Badge, Button, Card, ConfirmDialog, Dialog, EmptyState, ErrorNote, Field, Notice, Select, TableSkeleton, cx } from "../components/ui";
import { api } from "../lib/api";
import { useAuth, useDatasets, useToast } from "../lib/context";
import { timeAgo } from "../lib/format";
import { useAsync } from "../lib/hooks";
import type { Connection } from "../lib/types";

const EMPTY = { name: "", kind: "rest_api" as "rest_api" | "postgresql", url: "", records_path: "", header_name: "", header_value: "", host: "", port: "5432", database: "", username: "", password: "", sslmode: "require" };

export default function ConnectionsPage() {
  const { canAdmin, canEdit, workspaceKey } = useAuth();
  const { reloadDatasets } = useDatasets();
  const toast = useToast();
  const list = useAsync(() => api.get<Connection[]>("/connections"), [workspaceKey]);
  const [form, setForm] = useState(EMPTY);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [toDelete, setToDelete] = useState<Connection | null>(null);
  const [importing, setImporting] = useState<Connection | null>(null);
  const [tables, setTables] = useState<{ schema: string; table: string }[]>([]);
  const [tableChoice, setTableChoice] = useState("");
  const [importName, setImportName] = useState("");
  const [importBusy, setImportBusy] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const set = (patch: Partial<typeof EMPTY>) => setForm((f) => ({ ...f, ...patch }));

  const create = async () => {
    setSaving(true);
    setError(null);
    try {
      const body = form.kind === "rest_api"
        ? { name: form.name, kind: form.kind, url: form.url, records_path: form.records_path, ...(form.header_name ? { header_name: form.header_name, header_value: form.header_value } : {}) }
        : { name: form.name, kind: form.kind, host: form.host, port: Number(form.port), database: form.database, username: form.username, password: form.password, sslmode: form.sslmode };
      await api.post("/connections", body);
      setOpen(false);
      setForm(EMPTY);
      void list.reload(true);
      toast("Connection saved. Credentials are stored encrypted.");
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const test = async (connection: Connection) => {
    setTesting(connection.id);
    try {
      const result = await api.post<{ ok: boolean; error?: string; records?: number; tables?: number }>(`/connections/${connection.id}/test`);
      if (result.ok) toast(result.tables !== undefined ? `Connected. ${result.tables} tables are visible.` : `Connected. ${result.records} records found.`);
      else toast(result.error ?? "The connection test failed.", "error");
      void list.reload(true);
    } catch (caught) {
      toast((caught as Error).message, "error");
    } finally {
      setTesting(null);
    }
  };

  const startImport = async (connection: Connection) => {
    setImportError(null);
    setImportName("");
    setTables([]);
    setImporting(connection);
    if (connection.kind === "postgresql") {
      try {
        const found = await api.get<{ schema: string; table: string }[]>(`/connections/${connection.id}/tables`);
        setTables(found);
        setTableChoice(found[0] ? `${found[0].schema}.${found[0].table}` : "");
      } catch (caught) {
        setImportError((caught as Error).message);
      }
    }
  };

  const runImport = async () => {
    if (!importing) return;
    setImportBusy(true);
    setImportError(null);
    try {
      const selected = tables.find((t) => `${t.schema}.${t.table}` === tableChoice);
      await api.post(`/connections/${importing.id}/import`, { name: importName || undefined, schema_name: selected?.schema, table: selected?.table });
      toast("Import started. The dataset appears in My Datasets when it is ready.", "info");
      setImporting(null);
      reloadDatasets();
    } catch (caught) {
      setImportError((caught as Error).message);
    } finally {
      setImportBusy(false);
    }
  };

  const remove = async () => {
    if (!toDelete) return;
    await api.delete(`/connections/${toDelete.id}`);
    setToDelete(null);
    void list.reload(true);
    toast("Connection deleted. Datasets imported from it remain.");
  };

  return (
    <div className="space-y-3">
      <Notice icon={ShieldCheck}>Imports take a one-time copy, labelled Connected in My Datasets. Credentials are encrypted and never returned to the browser. Addresses on private or internal networks are blocked by default, and PostgreSQL sessions are read-only.</Notice>
      <div className="grid gap-3 md:grid-cols-3">
        <Card bodyClass="p-3.5"><div className="flex items-start gap-3"><span className="rounded border border-line bg-raised p-2 text-muted"><FileUp size={16} /></span><div className="min-w-0"><h3 className="text-[13px] font-semibold">File uploads</h3><p className="mt-0.5 text-xs text-muted">CSV, TSV, XLSX, XLS, and JSON files.</p><Link className="mt-1 inline-block text-xs font-medium text-blue-300 hover:underline" to="/datasets?upload=1">Upload a file</Link></div></div></Card>
        <Card bodyClass="p-3.5"><div className="flex items-start gap-3"><span className="rounded border border-line bg-raised p-2 text-muted"><Database size={16} /></span><div className="min-w-0"><h3 className="text-[13px] font-semibold">PostgreSQL</h3><p className="mt-0.5 text-xs text-muted">Copy a table or view through a read-only session.</p></div></div></Card>
        <Card bodyClass="p-3.5"><div className="flex items-start gap-3"><span className="rounded border border-line bg-raised p-2 text-muted"><Globe size={16} /></span><div className="min-w-0"><h3 className="text-[13px] font-semibold">REST API</h3><p className="mt-0.5 text-xs text-muted">Import records from a JSON endpoint on the public internet.</p></div></div></Card>
      </div>
      <Card title="Configured connections" actions={canAdmin && <Button variant="primary" icon={Plus} onClick={() => { setError(null); setOpen(true); }}>Add connection</Button>} bodyClass="overflow-x-auto">
        {list.error && <div className="p-3"><ErrorNote message={list.error} /></div>}
        {list.loading && !list.data ? <TableSkeleton rows={3} /> : !list.data?.length ? (
          <EmptyState icon={PlugZap} title="No connections yet" actions={canAdmin ? <Button variant="primary" icon={Plus} onClick={() => setOpen(true)}>Add connection</Button> : undefined}>{canAdmin ? "Connect a PostgreSQL database or a REST API to import its data." : "A workspace admin can add connections."}</EmptyState>
        ) : (
          <table className="data-table">
            <thead><tr><th>Name</th><th>Type</th><th>Target</th><th>Credentials</th><th>Last test</th><th /></tr></thead>
            <tbody>
              {list.data.map((c) => (
                <tr key={c.id}>
                  <td className="font-medium">{c.name}</td>
                  <td><Badge tone="cyan">{c.kind === "postgresql" ? "PostgreSQL" : "REST API"}</Badge></td>
                  <td className="max-w-[300px] truncate text-muted" title={String(c.config.url ?? `${c.config.host}/${c.config.database}`)}>{c.kind === "postgresql" ? `${c.config.username}@${c.config.host}:${c.config.port}/${c.config.database}` : String(c.config.url)}</td>
                  <td className="text-muted">{c.has_secret ? <span className="flex items-center gap-1"><KeyRound size={12} />Stored encrypted</span> : "None"}</td>
                  <td>
                    {!c.last_tested_at ? <span className="text-faint">Not tested</span> : (
                      <span title={c.last_error ?? undefined} className={cx("flex items-center gap-1", c.last_status === "ok" ? "text-green-300" : "text-red-300")}>
                        {c.last_status === "ok" ? <CheckCircle2 size={13} /> : <XCircle size={13} />}{c.last_status === "ok" ? "Passed" : "Failed"} <span className="text-faint">{timeAgo(c.last_tested_at)}</span>
                      </span>
                    )}
                  </td>
                  <td>
                    <div className="flex justify-end gap-1">
                      {canEdit && <Button size="sm" icon={TestTube2} loading={testing === c.id} onClick={() => void test(c)}>Test</Button>}
                      {canEdit && <Button size="sm" icon={Download} onClick={() => void startImport(c)}>Import</Button>}
                      {canAdmin && <button aria-label={`Delete ${c.name}`} className="rounded p-1.5 text-muted hover:bg-bad/20 hover:text-red-300" onClick={() => setToDelete(c)}><Trash2 size={14} /></button>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Dialog open={open} title="Add a data connection" onClose={() => setOpen(false)} footer={<><Button onClick={() => setOpen(false)}>Cancel</Button><Button variant="primary" loading={saving} disabled={!form.name.trim()} onClick={() => void create()}>Save connection</Button></>}>
        <div className="space-y-3">
          {error && <ErrorNote message={error} />}
          <div className="grid grid-cols-2 gap-3">
            <Field label="Name"><input className="field" maxLength={120} value={form.name} onChange={(e) => set({ name: e.target.value })} /></Field>
            <Field label="Type"><Select value={form.kind} onChange={(e) => set({ kind: e.target.value as typeof form.kind })}><option value="rest_api">REST API</option><option value="postgresql">PostgreSQL</option></Select></Field>
          </div>
          {form.kind === "rest_api" ? (
            <>
              <Field label="URL" hint="HTTPS is recommended. Allowed ports: 80, 443, 8080, and 8443."><input className="field" type="url" placeholder="https://api.example.com/orders" value={form.url} onChange={(e) => set({ url: e.target.value })} /></Field>
              <Field label="Records path (optional)" hint="Dotted path to the list of records in the response, such as data.items."><input className="field" value={form.records_path} onChange={(e) => set({ records_path: e.target.value })} /></Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Secret header name (optional)"><input className="field" placeholder="Authorization" value={form.header_name} onChange={(e) => set({ header_name: e.target.value })} /></Field>
                <Field label="Secret header value"><input className="field" type="password" autoComplete="off" value={form.header_value} onChange={(e) => set({ header_value: e.target.value })} /></Field>
              </div>
            </>
          ) : (
            <>
              <div className="grid grid-cols-[1fr_90px] gap-3">
                <Field label="Host"><input className="field" value={form.host} onChange={(e) => set({ host: e.target.value })} /></Field>
                <Field label="Port"><input className="field" type="number" value={form.port} onChange={(e) => set({ port: e.target.value })} /></Field>
              </div>
              <Field label="Database"><input className="field" value={form.database} onChange={(e) => set({ database: e.target.value })} /></Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Username"><input className="field" autoComplete="off" value={form.username} onChange={(e) => set({ username: e.target.value })} /></Field>
                <Field label="Password"><input className="field" type="password" autoComplete="new-password" value={form.password} onChange={(e) => set({ password: e.target.value })} /></Field>
              </div>
              <Field label="SSL mode"><Select value={form.sslmode} onChange={(e) => set({ sslmode: e.target.value })}><option value="require">Require</option><option value="verify-full">Verify full</option><option value="prefer">Prefer</option><option value="disable">Disable</option></Select></Field>
            </>
          )}
        </div>
      </Dialog>

      <Dialog open={!!importing} title={`Import from ${importing?.name ?? ""}`} width="max-w-md" onClose={() => setImporting(null)} footer={<><Button onClick={() => setImporting(null)}>Cancel</Button><Button variant="primary" icon={Download} loading={importBusy} disabled={importing?.kind === "postgresql" && !tableChoice} onClick={() => void runImport()}>Import</Button></>}>
        <div className="space-y-3">
          {importError && <ErrorNote message={importError} />}
          {importing?.kind === "postgresql" && <Field label="Table"><Select value={tableChoice} onChange={(e) => setTableChoice(e.target.value)}>{tables.map((t) => <option key={`${t.schema}.${t.table}`} value={`${t.schema}.${t.table}`}>{t.schema}.{t.table}</option>)}</Select></Field>}
          <Field label="Dataset name (optional)"><input className="field" maxLength={200} value={importName} onChange={(e) => setImportName(e.target.value)} /></Field>
          <p className="text-xs text-muted">This copies the current data once. Later changes at the source are not synchronised.</p>
        </div>
      </Dialog>
      <ConfirmDialog open={!!toDelete} danger title="Delete this connection?" confirmLabel="Delete connection" body={<>“{toDelete?.name}” and its stored credentials will be removed. Datasets already imported remain.</>} onClose={() => setToDelete(null)} onConfirm={() => void remove()} />
    </div>
  );
}
