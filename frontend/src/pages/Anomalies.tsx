import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis, ZAxis } from "recharts";
import { AlertOctagon, Eye, Info, Play } from "lucide-react";
import { tooltipStyle } from "../components/ChartView";
import { RequireDataset } from "../components/RequireDataset";
import { Badge, Button, Card, Dialog, EmptyState, ErrorNote, Notice, Pagination, Select, Skeleton, Stat, StatusBadge, TableSkeleton, cx } from "../components/ui";
import { api } from "../lib/api";
import { useAuth, useDatasets, useToast } from "../lib/context";
import { formatCell, formatCompact, formatDateTime, formatInt, formatNumber, titleCase } from "../lib/format";
import { useAsync } from "../lib/hooks";
import type { AnomalyResult, AnomalyRun, RowsResult } from "../lib/types";

const FLAG = "#F59E0B";
const NORMAL = "#3B82F6";
const axis = { stroke: "#263449", tickLine: false, tick: { fill: "#94A3B8", fontSize: 11 } };
const KINDS: Record<string, string> = { outlier: "Outlier", time_change: "Change over time", frequency_change: "Frequency change", missing_pattern: "Missing data pattern", rare_category: "Rare category" };

function AnomalyChart({ runId, item }: { runId: string; item: AnomalyResult }) {
  const { data, loading } = useAsync(() => api.get<any>(`/anomalies/runs/${runId}/chart?column=${encodeURIComponent(item.column_name)}&kind=${item.kind}`), [runId, item.column_name, item.kind]);
  if (loading && !data) return <Skeleton className="h-64" />;
  if (!data || data.type === "none") return <p className="py-8 text-center text-[13px] text-muted">{item.kind === "rare_category" ? "Rare categories are listed in the table. Open the records to review them." : "No chart applies to this finding. Open the records to review it."}</p>;
  if (data.type === "series") {
    const rows = data.points.map((p: any) => ({ ...p, flaggedValue: p.flagged ? p.value : null }));
    return (
      <div>
        <p className="mb-2 text-xs text-muted">{data.label} per period. Blue is observed, grey is the rolling baseline, amber points are flagged.</p>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={rows}>
              <CartesianGrid stroke="#263449" strokeDasharray="3 3" vertical={false} />
              <XAxis {...axis} dataKey="period" minTickGap={28} />
              <YAxis {...axis} width={54} tickFormatter={formatCompact} axisLine={false} />
              <Tooltip {...tooltipStyle} formatter={(v, name) => [formatNumber(v as number), name === "value" ? "Observed" : name === "baseline" ? "Baseline" : "Flagged"]} />
              <Line dataKey="baseline" stroke="#64748B" strokeWidth={1.5} dot={false} strokeDasharray="4 3" isAnimationActive={false} connectNulls />
              <Line dataKey="value" stroke={NORMAL} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls />
              <Scatter dataKey="flaggedValue" fill={FLAG} stroke="#111B2B" strokeWidth={1.5} isAnimationActive={false} />
              <ZAxis range={[60, 60]} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>
    );
  }
  return (
    <div>
      <p className="mb-2 text-xs text-muted">Distribution of {data.column}. Values outside the expected range ({formatNumber(data.expected_low)} to {formatNumber(data.expected_high)}) are amber; {formatInt(data.flagged_points.length)} are listed for review.</p>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data.histogram} barCategoryGap={1}>
            <CartesianGrid stroke="#263449" strokeDasharray="3 3" vertical={false} />
            <XAxis {...axis} dataKey="label" minTickGap={24} />
            <YAxis {...axis} width={54} tickFormatter={formatCompact} axisLine={false} />
            <Tooltip {...tooltipStyle} formatter={(v, _n, entry) => [formatInt(v as number), (entry.payload as any).flagged ? "Outside expected range" : "Within expected range"]} cursor={{ fill: "rgba(148,163,184,0.08)" }} />
            <ReferenceLine y={0} stroke="#263449" />
            <Bar dataKey="count" radius={[2, 2, 0, 0]} isAnimationActive={false}>
              {data.histogram.map((bin: any, i: number) => <Cell key={i} fill={bin.flagged ? FLAG : NORMAL} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function RecordsDialog({ item, onClose }: { item: AnomalyResult | null; onClose: () => void }) {
  const { data, loading, error } = useAsync(() => (item ? api.get<RowsResult>(`/anomalies/results/${item.id}/records`) : Promise.resolve(null)), [item?.id]);
  return (
    <Dialog open={!!item} title="Original records" subtitle={item ? `${item.column_name}: ${item.period ?? (item.row_id ? `row ${item.row_id}` : item.observed ?? "")}` : ""} width="max-w-5xl" onClose={onClose} footer={<Button onClick={onClose}>Close</Button>}>
      {item && <p className="mb-3 text-[13px] text-muted">{item.explanation}</p>}
      {error && <ErrorNote message={error} />}
      {loading && !data ? <TableSkeleton rows={3} /> : data && (
        <div className="max-h-[50vh] overflow-auto rounded border border-line">
          <table className="data-table">
            <thead><tr><th>#</th>{data.columns.map((c) => <th key={c} className={cx(c === item?.column_name && "!text-amber-300")}>{c}</th>)}</tr></thead>
            <tbody>{data.rows.map((row) => <tr key={String(row.__row_id)}><td className="num text-faint">{String(row.__row_id)}</td>{data.columns.map((c) => <td key={c} className={cx("max-w-[240px] truncate", c === item?.column_name && "font-medium text-amber-200")}>{row[c] === null ? <span className="text-faint">null</span> : formatCell(row[c])}</td>)}</tr>)}</tbody>
          </table>
        </div>
      )}
      {data && data.total > data.rows.length && <p className="mt-2 text-xs text-faint">Showing {data.rows.length} of {formatInt(data.total)} records for this period.</p>}
    </Dialog>
  );
}

function Content({ datasetId }: { datasetId: string }) {
  const { canEdit } = useAuth();
  const { reloadDatasets } = useDatasets();
  const toast = useToast();
  const runs = useAsync(() => api.get<AnomalyRun[]>(`/anomalies/runs?dataset_id=${datasetId}`), [datasetId]);
  const [runId, setRunId] = useState<string | null>(null);
  const run = runs.data?.find((r) => r.id === runId) ?? runs.data?.[0] ?? null;
  const [scanning, setScanning] = useState(false);
  const [filters, setFilters] = useState({ column: "", method: "", severity: "", status: "", date_from: "", date_to: "" });
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<AnomalyResult | null>(null);
  const [inspect, setInspect] = useState<AnomalyResult | null>(null);

  useEffect(() => setPage(1), [JSON.stringify(filters), run?.id]);
  useEffect(() => setSelected(null), [run?.id]);

  const query = new URLSearchParams({ page: String(page), page_size: "15" });
  Object.entries(filters).forEach(([k, v]) => { if (v) query.set(k, v); });
  const results = useAsync(() => (run ? api.get<{ items: AnomalyResult[]; total: number }>(`/anomalies/runs/${run.id}/results?${query}`) : Promise.resolve(null)), [run?.id, query.toString()]);
  const shown = selected ?? results.data?.items[0] ?? null;

  const scan = async () => {
    setScanning(true);
    try {
      const created = await api.post<AnomalyRun>("/anomalies/run", { dataset_id: datasetId });
      setRunId(created.id);
      await runs.reload(true);
      reloadDatasets();
      toast(`Scan finished: ${formatInt(created.summary.total)} items flagged for review.`, created.summary.by_severity.high ? "warning" : "success");
    } catch (caught) {
      toast((caught as Error).message, "error");
    } finally {
      setScanning(false);
    }
  };

  const setStatus = async (item: AnomalyResult, status: string) => {
    try {
      await api.patch(`/anomalies/results/${item.id}`, { status });
      void results.reload(true);
    } catch (caught) {
      toast((caught as Error).message, "error");
    }
  };

  const columnsInRun = [...new Set(run?.summary.methods.map((m) => m.column) ?? [])];
  const methodsInRun = [...new Set(run?.summary.methods.map((m) => m.method) ?? [])];
  const update = (key: keyof typeof filters, value: string) => setFilters((f) => ({ ...f, [key]: value }));

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {canEdit && <Button variant="primary" icon={Play} loading={scanning} onClick={() => void scan()}>Run anomaly scan</Button>}
        {!!runs.data?.length && (
          <label className="flex items-center gap-1.5 text-xs text-muted">Scan
            <Select className="!h-8 !w-72" value={run?.id ?? ""} onChange={(e) => setRunId(e.target.value)}>{runs.data.map((r) => <option key={r.id} value={r.id}>{formatDateTime(r.created_at)} ({formatInt(r.summary.total)} flagged)</option>)}</Select>
          </label>
        )}
      </div>
      <Notice tone="warn" icon={Info}>Statistical anomalies are unusual values relative to the rest of the data. They are not automatically errors or evidence of fraud, and they need review in context.</Notice>

      {runs.loading && !runs.data ? <Skeleton className="h-64" /> : !run ? (
        <Card><EmptyState icon={AlertOctagon} title="No scan has been run" actions={canEdit ? <Button variant="primary" icon={Play} loading={scanning} onClick={() => void scan()}>Run anomaly scan</Button> : undefined}>A scan chooses suitable statistical methods for each column based on its type and shape.</EmptyState></Card>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Items listed for review" value={formatInt(run.summary.total)} sub={`${formatInt(run.summary.rows_checked)} rows checked`} />
            <Stat label="High severity" value={formatInt(run.summary.by_severity.high)} tone={run.summary.by_severity.high ? "bad" : undefined} />
            <Stat label="Medium severity" value={formatInt(run.summary.by_severity.medium)} tone={run.summary.by_severity.medium ? "warn" : undefined} />
            <Stat label="Low severity" value={formatInt(run.summary.by_severity.low)} />
          </div>

          <Card bodyClass="p-3">
            <div className="flex flex-wrap items-end gap-2">
              <label className="flex flex-col text-xs text-muted">Column<Select className="mt-1 !w-44" value={filters.column} onChange={(e) => update("column", e.target.value)}><option value="">All columns</option>{columnsInRun.map((c) => <option key={c}>{c}</option>)}</Select></label>
              <label className="flex flex-col text-xs text-muted">Method<Select className="mt-1 !w-56" value={filters.method} onChange={(e) => update("method", e.target.value)}><option value="">All methods</option>{methodsInRun.map((m) => <option key={m}>{m}</option>)}</Select></label>
              <label className="flex flex-col text-xs text-muted">Severity<Select className="mt-1 !w-28" value={filters.severity} onChange={(e) => update("severity", e.target.value)}><option value="">All</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></Select></label>
              <label className="flex flex-col text-xs text-muted">Status<Select className="mt-1 !w-32" value={filters.status} onChange={(e) => update("status", e.target.value)}><option value="">All</option><option value="open">Open</option><option value="investigating">Investigating</option><option value="expected">Expected</option><option value="resolved">Resolved</option></Select></label>
              <label className="flex flex-col text-xs text-muted">Period from<input type="date" className="field mt-1 !w-36" value={filters.date_from} onChange={(e) => update("date_from", e.target.value)} /></label>
              <label className="flex flex-col text-xs text-muted">Period to<input type="date" className="field mt-1 !w-36" value={filters.date_to} onChange={(e) => update("date_to", e.target.value)} /></label>
            </div>
          </Card>

          <Card bodyClass="">
            <div className="overflow-x-auto">
              {results.loading && !results.data ? <TableSkeleton /> : (
                <table className={cx("data-table", results.loading && "opacity-60")}>
                  <thead><tr><th>Record or period</th><th>Column</th><th>Type</th><th className="text-right">Observed</th><th className="text-right">Expected or baseline</th><th>Method</th><th>Severity</th><th className="text-right">Score</th><th>Status</th><th /></tr></thead>
                  <tbody>
                    {results.data?.items.map((item) => (
                      <tr key={item.id} onClick={() => setSelected(item)} className={cx("cursor-pointer", shown?.id === item.id && "bg-primary-soft")}>
                        <td className="num">{item.period ?? (item.row_id ? `Row ${formatInt(item.row_id)}` : "Category")}</td>
                        <td className="max-w-[140px] truncate font-medium">{item.column_name}</td>
                        <td className="text-muted">{KINDS[item.kind] ?? titleCase(item.kind)}</td>
                        <td className="num max-w-[180px] truncate text-right" title={item.observed ?? ""}>{item.observed}</td>
                        <td className="num text-right text-muted">{item.expected_low !== null && item.expected_high !== null ? `${formatNumber(item.expected_low)} to ${formatNumber(item.expected_high)}` : item.baseline !== null ? `≈ ${formatNumber(item.baseline)}` : "-"}</td>
                        <td className="max-w-[170px] truncate text-muted" title={item.method}>{item.method}</td>
                        <td><StatusBadge status={item.severity} /></td>
                        <td className="num text-right">{formatNumber(item.score)}</td>
                        <td onClick={(e) => e.stopPropagation()}>
                          <Select aria-label="Investigation status" disabled={!canEdit} className="!h-7 !w-28 text-xs" value={item.status} onChange={(e) => void setStatus(item, e.target.value)}>
                            <option value="open">Open</option><option value="investigating">Investigating</option><option value="expected">Expected</option><option value="resolved">Resolved</option>
                          </Select>
                        </td>
                        <td onClick={(e) => e.stopPropagation()}><Button size="sm" variant="ghost" icon={Eye} onClick={() => setInspect(item)}>Inspect</Button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {results.data && !results.data.items.length && <EmptyState icon={AlertOctagon} title="Nothing to show">{run.summary.total ? "No findings match these filters." : "This scan flagged nothing unusual."}</EmptyState>}
            </div>
            {results.data && <Pagination page={page} pageCount={Math.ceil(results.data.total / 15)} total={results.data.total} onPage={setPage} label="findings" />}
          </Card>

          <div className="grid gap-3 xl:grid-cols-2">
            <Card title={shown ? `${shown.column_name}: normal and flagged observations` : "Observations"} subtitle={shown?.explanation}>
              {shown ? <AnomalyChart runId={run.id} item={shown} /> : <p className="py-8 text-center text-[13px] text-muted">Select a finding to chart it.</p>}
            </Card>
            <Card title="Methods applied" subtitle="Chosen for each column from its type and shape" bodyClass="max-h-80 overflow-auto">
              <ul>
                {run.summary.methods.map((m, i) => (
                  <li key={i} className="border-b border-line/60 px-4 py-2 last:border-0">
                    <p className="flex flex-wrap items-center gap-1.5 text-[13px]"><span className="font-medium">{m.column}</span><Badge tone="blue">{m.method}</Badge><span className="num text-xs text-muted">{formatInt(m.flagged)} flagged{m.listed !== null && m.listed < m.flagged ? `, most significant ${formatInt(m.listed)} listed` : ""}</span></p>
                    <p className="text-xs text-muted">{m.reason}</p>
                  </li>
                ))}
                {run.summary.skipped.map((s) => <li key={s} className="border-b border-line/60 px-4 py-2 text-xs text-faint last:border-0">{s}</li>)}
              </ul>
            </Card>
          </div>
        </>
      )}
      <RecordsDialog item={inspect} onClose={() => setInspect(null)} />
    </div>
  );
}

export default function AnomaliesPage() {
  return <RequireDataset>{(id) => <Content key={id} datasetId={id} />}</RequireDataset>;
}
