import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { AlertCircle, CheckCircle2, Copy, Database, FileUp, FlaskConical, FolderPlus, Info, Loader2, Pencil, RotateCcw, Search, Table2, Trash2, Upload } from "lucide-react";
import { Badge, Button, Card, ConfirmDialog, Dialog, EmptyState, ErrorNote, Field, Notice, Select, StatusBadge, SyntheticBadge, TableSkeleton, Tooltip, cx } from "../components/ui";
import { api, uploadFile } from "../lib/api";
import { useAuth, useDatasets, useToast } from "../lib/context";
import { formatBytes, formatCell, formatDate, formatDateTime, formatInt, timeAgo } from "../lib/format";
import { useAsync, useDebounced, useInterval } from "../lib/hooks";
import type { Dataset, Project, RowsResult } from "../lib/types";

const ACCEPT = ".csv,.tsv,.xlsx,.xls,.json";
const MAX_MB_HINT = "CSV, TSV, XLSX, XLS, or JSON, up to the server's upload limit (100 MB by default).";

interface UploadItem { key: number; file: File; progress: number; dataset: Dataset | null; error: string | null }

function UploadDialog({ open, projectId, onClose, onChanged }: { open: boolean; projectId?: string; onClose: () => void; onChanged: () => void }) {
  const [items, setItems] = useState<UploadItem[]>([]);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<{ name: string; rows: RowsResult } | null>(null);
  const update = (key: number, patch: Partial<UploadItem>) => setItems((all) => all.map((i) => (i.key === key ? { ...i, ...patch } : i)));
  const pending = items.some((i) => i.dataset && (i.dataset.status === "queued" || i.dataset.status === "processing"));

  useInterval(async () => {
    for (const item of items) {
      if (item.dataset && (item.dataset.status === "queued" || item.dataset.status === "processing")) {
        const fresh = await api.get<Dataset>(`/datasets/${item.dataset.id}`);
        update(item.key, { dataset: fresh });
        if (fresh.status === "ready" || fresh.status === "failed") onChanged();
      }
    }
  }, pending ? 700 : null);

  const start = (files: FileList | File[]) => {
    Array.from(files).forEach((file, index) => {
      const key = Date.now() + index;
      setItems((all) => [...all, { key, file, progress: 0, dataset: null, error: null }]);
      uploadFile<Dataset>(file, (progress) => update(key, { progress }), projectId)
        .then((dataset) => { update(key, { dataset, progress: 100 }); onChanged(); })
        .catch((caught: Error) => update(key, { error: caught.message }));
    });
  };

  const showPreview = async (dataset: Dataset) => {
    setPreview({ name: dataset.name, rows: await api.post<RowsResult>(`/datasets/${dataset.id}/rows`, { page_size: 8 }) });
  };

  return (
    <Dialog open={open} title="Upload datasets" subtitle="Files are validated, then processed in the background. You can close this window." width="max-w-2xl" onClose={() => { onClose(); setItems([]); setPreview(null); }}
      footer={<Button onClick={() => { onClose(); setItems([]); setPreview(null); }}>Done</Button>}>
      <div className="space-y-3">
        <button type="button" onClick={() => input.current?.click()} onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={(e) => { e.preventDefault(); setDragging(false); start(e.dataTransfer.files); }}
          className={cx("flex w-full flex-col items-center rounded-lg border border-dashed px-4 py-8 text-center transition-colors", dragging ? "border-primary bg-primary-soft" : "border-line bg-canvas hover:border-faint")}>
          <FileUp size={22} className="mb-2 text-muted" />
          <span className="text-[13px] font-medium">Drag files here, or click to browse</span>
          <span className="mt-1 text-xs text-muted">{MAX_MB_HINT}</span>
        </button>
        <input ref={input} data-testid="file-input" type="file" accept={ACCEPT} multiple className="hidden" onChange={(e) => { if (e.target.files) start(e.target.files); e.target.value = ""; }} />
        <p className="flex items-start gap-1.5 text-xs text-faint"><Info size={13} className="mt-0.5 shrink-0" />Macros are rejected and formulas are never evaluated. The original file is kept unchanged.</p>
        {items.map((item) => {
          const d = item.dataset;
          const uploading = !d && !item.error;
          return (
            <div key={item.key} className="rounded-md border border-line bg-raised px-3 py-2">
              <div className="flex items-center gap-2">
                {item.error || d?.status === "failed" ? <AlertCircle size={15} className="shrink-0 text-bad" /> : d?.status === "ready" ? <CheckCircle2 size={15} className="shrink-0 text-good" /> : <Loader2 size={15} className="shrink-0 animate-spin text-primary" />}
                <span className="min-w-0 flex-1 truncate text-[13px] font-medium">{item.file.name}</span>
                <span className="num text-xs text-muted">{formatBytes(item.file.size)}</span>
                {d?.status === "ready" && <Button size="sm" variant="ghost" onClick={() => void showPreview(d)}>Preview</Button>}
                {d?.status === "ready" && <Link to={`/explorer?dataset=${d.id}`}><Button size="sm" tabIndex={-1}>Explore</Button></Link>}
              </div>
              {(uploading || (d && d.status !== "ready" && d.status !== "failed")) && (
                <div className="mt-2">
                  <div className="h-1 overflow-hidden rounded bg-canvas"><div className="h-full bg-primary transition-all" style={{ width: `${uploading ? item.progress : Math.max(d?.progress ?? 0, 8)}%` }} /></div>
                  <p className="mt-1 text-xs text-muted">{uploading ? `Uploading ${item.progress}%` : d?.stage ?? "Queued"}</p>
                </div>
              )}
              {d?.status === "ready" && <p className="num mt-1 text-xs text-muted">{formatInt(d.row_count)} rows, {d.column_count} columns</p>}
              {(item.error || d?.status === "failed") && <p className="mt-1 text-xs text-red-300">{item.error ?? d?.error_message}</p>}
            </div>
          );
        })}
        {preview && (
          <div>
            <p className="mb-1 text-xs font-medium text-muted">Preview: {preview.name}</p>
            <div className="max-h-56 overflow-auto rounded-md border border-line">
              <table className="data-table">
                <thead><tr>{preview.rows.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
                <tbody>{preview.rows.rows.map((r) => <tr key={String(r.__row_id)}>{preview.rows.columns.map((c) => <td key={c}>{formatCell(r[c])}</td>)}</tr>)}</tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </Dialog>
  );
}

function DetailsDialog({ datasetId, projects, onClose, onChanged }: { datasetId: string | null; projects: Project[]; onClose: () => void; onChanged: () => void }) {
  const { canEdit } = useAuth();
  const toast = useToast();
  const { data, reload } = useAsync(() => (datasetId ? api.get<Dataset>(`/datasets/${datasetId}`) : Promise.resolve(null)), [datasetId]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [project, setProject] = useState("");
  useEffect(() => {
    if (data) { setName(data.name); setDescription(data.description ?? ""); setProject(data.project_id ?? ""); }
  }, [data]);
  const save = async () => {
    try {
      await api.patch(`/datasets/${datasetId}`, { name, description, ...(project ? { project_id: project } : { clear_project: true }) });
      toast("Dataset updated.");
      onChanged();
      onClose();
    } catch (caught) {
      toast((caught as Error).message, "error");
    }
  };
  const activate = async (versionId: string, number: number) => {
    await api.post(`/datasets/${datasetId}/versions/${versionId}/activate`);
    toast(`Version ${number} is now active.`);
    void reload(true);
    onChanged();
  };
  return (
    <Dialog open={!!datasetId} title="Dataset details" width="max-w-2xl" onClose={onClose} footer={<><Button onClick={onClose}>Close</Button>{canEdit && <Button variant="primary" onClick={() => void save()}>Save changes</Button>}</>}>
      {data && (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Name"><input className="field" maxLength={200} disabled={!canEdit} value={name} onChange={(e) => setName(e.target.value)} /></Field>
            <Field label="Project"><Select disabled={!canEdit} value={project} onChange={(e) => setProject(e.target.value)}><option value="">No project</option>{projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select></Field>
          </div>
          <Field label="Description"><textarea className="field !h-16 py-1.5" maxLength={2000} disabled={!canEdit} value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-[13px] sm:grid-cols-3">
            {([["Original file", data.original_filename ?? "-"], ["Format", data.file_format.toUpperCase()], ["File size", formatBytes(data.file_size)], ["Source", data.source_type], ["Uploaded", formatDateTime(data.created_at)], ["Last analysed", formatDateTime(data.last_analysed_at)]] as const).map(([k, v]) => <div key={k}><dt className="text-xs text-muted">{k}</dt><dd className="truncate">{v}</dd></div>)}
          </dl>
          {!!data.ingest_notes.length && <Notice>{data.ingest_notes.map((n) => <p key={n}>{n}</p>)}</Notice>}
          <div>
            <h3 className="mb-1.5 text-xs font-medium text-muted">Versions</h3>
            <div className="overflow-x-auto rounded-md border border-line">
              <table className="data-table">
                <thead><tr><th>Version</th><th>Description</th><th className="text-right">Rows</th><th>Created</th><th /></tr></thead>
                <tbody>
                  {data.versions?.map((v) => (
                    <tr key={v.id}>
                      <td className="num">v{v.version_number} {v.is_current && <Badge tone="blue">Active</Badge>}</td>
                      <td className="max-w-[260px] truncate text-muted" title={v.label}>{v.label}</td>
                      <td className="num text-right">{formatInt(v.row_count)}</td>
                      <td className="text-muted">{formatDate(v.created_at)}</td>
                      <td className="text-right">{!v.is_current && canEdit && <Button size="sm" variant="ghost" icon={RotateCcw} onClick={() => void activate(v.id, v.version_number)}>Restore</Button>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </Dialog>
  );
}

export default function DatasetsPage() {
  const { canEdit, workspaceKey } = useAuth();
  const { reloadDatasets } = useDatasets();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState("");
  const [projectFilter, setProjectFilter] = useState("");
  const [uploadOpen, setUploadOpen] = useState(params.get("upload") === "1");
  const [details, setDetails] = useState<string | null>(null);
  const [toDelete, setToDelete] = useState<Dataset | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [projectOpen, setProjectOpen] = useState(false);
  const [projectName, setProjectName] = useState("");
  const [demoBusy, setDemoBusy] = useState(false);
  const debounced = useDebounced(search);

  const query = new URLSearchParams();
  if (debounced) query.set("search", debounced);
  if (projectFilter) query.set("project_id", projectFilter);
  const { data, loading, error, reload } = useAsync(() => api.get<Dataset[]>(`/datasets?${query}`), [debounced, projectFilter, workspaceKey]);
  const projects = useAsync(() => api.get<Project[]>("/projects"), [workspaceKey]);
  const processing = data?.some((d) => d.status === "queued" || d.status === "processing");
  useInterval(() => void reload(true), processing ? 1000 : null);

  const changed = () => { void reload(true); void projects.reload(true); reloadDatasets(); };

  const remove = async () => {
    if (!toDelete) return;
    setDeleting(true);
    try {
      await api.delete(`/datasets/${toDelete.id}`);
      toast(`'${toDelete.name}' was deleted.`);
      changed();
    } catch (caught) {
      toast((caught as Error).message, "error");
    } finally {
      setDeleting(false);
      setToDelete(null);
    }
  };

  const loadDemo = async () => {
    setDemoBusy(true);
    try {
      const created = await api.post<Dataset[]>("/datasets/demo");
      toast(created.length ? `${created.length} synthetic datasets are being processed.` : "Demonstration datasets are already loaded.", "info");
      changed();
    } catch (caught) {
      toast((caught as Error).message, "error");
    } finally {
      setDemoBusy(false);
    }
  };

  const createProject = async () => {
    try {
      await api.post("/projects", { name: projectName });
      setProjectName("");
      setProjectOpen(false);
      void projects.reload(true);
      toast("Project created.");
    } catch (caught) {
      toast((caught as Error).message, "error");
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[200px] flex-1 sm:max-w-xs">
          <Search size={14} className="pointer-events-none absolute left-2.5 top-2 text-faint" />
          <input aria-label="Search datasets" className="field !pl-8" placeholder="Search by name or file" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <Select aria-label="Filter by project" className="!w-44" value={projectFilter} onChange={(e) => setProjectFilter(e.target.value)}>
          <option value="">All projects</option>
          {projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.dataset_count})</option>)}
        </Select>
        <div className="ml-auto flex flex-wrap gap-2">
          {canEdit && <Button icon={FolderPlus} onClick={() => setProjectOpen(true)}>New project</Button>}
          {canEdit && <Button icon={FlaskConical} loading={demoBusy} onClick={() => void loadDemo()}>Load demo data</Button>}
          {canEdit && <Button variant="primary" icon={Upload} onClick={() => setUploadOpen(true)}>Upload dataset</Button>}
        </div>
      </div>

      {error && <ErrorNote message={error} onRetry={() => void reload()} />}

      <Card bodyClass="overflow-x-auto">
        {loading && !data ? <TableSkeleton /> : !data?.length ? (
          <EmptyState icon={Database} title={debounced || projectFilter ? "No datasets match" : "No datasets yet"} actions={!debounced && !projectFilter && canEdit ? <Button variant="primary" icon={Upload} onClick={() => setUploadOpen(true)}>Upload dataset</Button> : undefined}>
            {debounced || projectFilter ? "Try a different search or project." : "Upload a CSV, Excel, or JSON file to begin."}
          </EmptyState>
        ) : (
          <table className="data-table">
            <thead><tr><th>Dataset</th><th>Project</th><th>Type</th><th className="text-right">Rows</th><th className="text-right">Cols</th><th className="text-right">Size</th><th>Uploaded</th><th>Status</th><th>Last analysed</th><th><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>
              {data.map((d) => (
                <tr key={d.id}>
                  <td className="max-w-[300px]">
                    <span className="flex items-center gap-1.5">
                      {d.status === "ready" ? <Link className="truncate font-medium hover:text-blue-300" to={`/explorer?dataset=${d.id}`}>{d.name}</Link> : <span className="truncate font-medium">{d.name}</span>}
                      {d.is_demo && <SyntheticBadge />}
                      {d.source_type === "connection" && <Badge tone="cyan">Connected</Badge>}
                      {d.source_type === "derived" && <Badge tone="neutral">Derived</Badge>}
                    </span>
                  </td>
                  <td className="text-muted">{d.project_name ?? "-"}</td>
                  <td className="uppercase text-muted">{d.file_format}</td>
                  <td className="num text-right">{d.status === "ready" ? formatInt(d.row_count) : "-"}</td>
                  <td className="num text-right">{d.status === "ready" ? d.column_count : "-"}</td>
                  <td className="num text-right text-muted">{formatBytes(d.file_size)}</td>
                  <td className="text-muted">{formatDate(d.created_at)}</td>
                  <td>
                    {d.status === "failed" ? <Tooltip text={d.error_message ?? "Processing failed"}><StatusBadge status="failed" /></Tooltip> : d.status === "ready" ? <StatusBadge status="ready" /> : (
                      <span className="flex items-center gap-1.5 text-xs text-muted"><Loader2 size={12} className="animate-spin text-primary" />{d.stage ?? "Queued"}</span>
                    )}
                  </td>
                  <td className="text-muted">{timeAgo(d.last_analysed_at)}</td>
                  <td>
                    <div className="flex justify-end gap-0.5">
                      {d.status === "ready" && <Tooltip text="Explore"><Link aria-label={`Explore ${d.name}`} className="rounded p-1.5 text-muted hover:bg-raised hover:text-ink" to={`/explorer?dataset=${d.id}`}><Table2 size={14} /></Link></Tooltip>}
                      <Tooltip text="Details and versions"><button aria-label={`Details for ${d.name}`} className="rounded p-1.5 text-muted hover:bg-raised hover:text-ink" onClick={() => setDetails(d.id)}><Pencil size={14} /></button></Tooltip>
                      {canEdit && d.status === "ready" && <Tooltip text="Duplicate"><button aria-label={`Duplicate ${d.name}`} className="rounded p-1.5 text-muted hover:bg-raised hover:text-ink" onClick={async () => { try { await api.post(`/datasets/${d.id}/duplicate`); toast("Dataset duplicated."); changed(); } catch (caught) { toast((caught as Error).message, "error"); } }}><Copy size={14} /></button></Tooltip>}
                      {canEdit && <Tooltip text="Delete"><button aria-label={`Delete ${d.name}`} className="rounded p-1.5 text-muted hover:bg-bad/20 hover:text-red-300" onClick={() => setToDelete(d)}><Trash2 size={14} /></button></Tooltip>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <UploadDialog open={uploadOpen} projectId={projectFilter || undefined} onChanged={changed} onClose={() => { setUploadOpen(false); if (params.get("upload")) { params.delete("upload"); setParams(params, { replace: true }); } }} />
      <DetailsDialog datasetId={details} projects={projects.data ?? []} onClose={() => setDetails(null)} onChanged={changed} />
      <ConfirmDialog open={!!toDelete} danger title="Delete this dataset?" confirmLabel="Delete dataset" loading={deleting} onClose={() => setToDelete(null)} onConfirm={() => void remove()}
        body={<>This permanently deletes <strong className="text-ink">{toDelete?.name}</strong>, its original file, all versions, and its saved charts, anomaly scans, reports, and conversations. This cannot be undone.</>} />
      <Dialog open={projectOpen} title="New project" width="max-w-sm" onClose={() => setProjectOpen(false)} footer={<><Button onClick={() => setProjectOpen(false)}>Cancel</Button><Button variant="primary" disabled={!projectName.trim()} onClick={() => void createProject()}>Create project</Button></>}>
        <Field label="Project name" hint="Projects group related datasets. Move a dataset into one from its details."><input autoFocus className="field" maxLength={120} value={projectName} onChange={(e) => setProjectName(e.target.value)} /></Field>
      </Dialog>
    </div>
  );
}
