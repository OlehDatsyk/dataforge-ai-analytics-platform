import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { AreaChart as AreaIcon, BarChart3, Boxes, ChartScatter, CircleDot, Donut, LineChart as LineIcon, PieChart as PieIcon, Save, Sparkles, Trash2 } from "lucide-react";
import { ChartView } from "../components/ChartView";
import { completeFilters, FilterBuilder } from "../components/FilterBuilder";
import { RequireDataset } from "../components/RequireDataset";
import { Badge, Button, Card, ConfirmDialog, Dialog, EmptyState, ErrorNote, Field, Select, Skeleton, cx } from "../components/ui";
import { api } from "../lib/api";
import { useAuth, useToast } from "../lib/context";
import { formatInt, timeAgo } from "../lib/format";
import { useAsync, useDebounced } from "../lib/hooks";
import type { ChartResult, ChartSpec, ChartType, Column, Dataset, Filter, Visualisation } from "../lib/types";

const CHART_TYPES: { id: ChartType; label: string; icon: typeof BarChart3 }[] = [
  { id: "bar", label: "Bar", icon: BarChart3 }, { id: "line", label: "Line", icon: LineIcon }, { id: "area", label: "Area", icon: AreaIcon }, { id: "pie", label: "Pie", icon: PieIcon },
  { id: "donut", label: "Donut", icon: Donut }, { id: "scatter", label: "Scatter", icon: ChartScatter }, { id: "histogram", label: "Histogram", icon: CircleDot }, { id: "box", label: "Box plot", icon: Boxes },
];
const AGGREGATIONS = [["sum", "Sum"], ["avg", "Average"], ["count", "Count"], ["min", "Minimum"], ["max", "Maximum"], ["median", "Median"]] as const;

const isNumeric = (c: Column) => c.type === "integer" || c.type === "float";
const isCategory = (c: Column) => c.type === "category" || c.type === "text" || c.type === "boolean";

function defaultSpec(columns: Column[]): ChartSpec {
  const category = columns.find((c) => c.type === "category");
  const measures = columns.filter((c) => isNumeric(c) && !/(^|_)id$/i.test(c.name));
  const numeric = measures.find((c) => /(^|_)(revenue|sales|amount|total|value|profit|sessions)($|_)/i.test(c.name)) ?? measures[0];
  return { chart_type: "bar", x: category?.name ?? columns[0]?.name, y: numeric?.name ?? null, aggregation: numeric ? "sum" : "count", sort: "value_desc", time_grain: "auto", limit: 30, bins: 20 };
}

function Studio({ datasetId }: { datasetId: string }) {
  const { canEdit } = useAuth();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const details = useAsync(() => api.get<Dataset>(`/datasets/${datasetId}`), [datasetId]);
  const columns = details.data?.columns ?? [];
  const [spec, setSpec] = useState<ChartSpec | null>(null);
  const [filters, setFilters] = useState<Filter[]>([]);
  const [saveOpen, setSaveOpen] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [saving, setSaving] = useState(false);
  const [activeSaved, setActiveSaved] = useState<Visualisation | null>(null);
  const [toDelete, setToDelete] = useState<Visualisation | null>(null);
  const saved = useAsync(() => api.get<Visualisation[]>(`/visualisations?dataset_id=${datasetId}`), [datasetId]);
  const suggestions = useAsync(() => api.get<{ source: string; suggestions: { spec: ChartSpec; title: string; reason: string }[] }>(`/charts/recommendations?dataset_id=${datasetId}`), [datasetId]);

  useEffect(() => {
    if (columns.length && !spec) setSpec(defaultSpec(columns));
  }, [columns.length]); // eslint-disable-line

  useEffect(() => {
    const id = params.get("saved");
    if (id && saved.data) {
      const match = saved.data.find((v) => v.id === id);
      if (match) load(match);
      const next = new URLSearchParams(params);
      next.delete("saved");
      setParams(next, { replace: true });
    }
  }, [saved.data]); // eslint-disable-line

  const load = (viz: Visualisation) => {
    setSpec({ ...defaultSpec(columns), ...viz.spec });
    setFilters(viz.spec.filters ?? []);
    setActiveSaved(viz);
    setSaveName(viz.name);
  };

  const patch = (changes: Partial<ChartSpec>) => setSpec((current) => (current ? { ...current, ...changes } : current));
  const fullSpec: ChartSpec | null = spec && { ...spec, filters: completeFilters(filters), y: spec.y || null, x: spec.x || null, group: spec.group || null };
  const debounced = useDebounced(JSON.stringify(fullSpec), 250);
  const chart = useAsync<ChartResult | null>(() => (debounced && debounced !== "null" ? api.post<ChartResult>("/charts/run", { dataset_id: datasetId, spec: JSON.parse(debounced) }) : Promise.resolve(null)), [debounced, datasetId]);

  const save = async () => {
    if (!fullSpec) return;
    setSaving(true);
    try {
      const body = { dataset_id: datasetId, name: saveName, spec: fullSpec };
      const result = activeSaved ? await api.put<Visualisation>(`/visualisations/${activeSaved.id}`, body) : await api.post<Visualisation>("/visualisations", body);
      setActiveSaved(result);
      setSaveOpen(false);
      void saved.reload(true);
      toast("Visualisation saved.");
    } catch (caught) {
      toast((caught as Error).message, "error");
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!toDelete) return;
    await api.delete(`/visualisations/${toDelete.id}`);
    if (activeSaved?.id === toDelete.id) setActiveSaved(null);
    setToDelete(null);
    void saved.reload(true);
    toast("Visualisation deleted.");
  };

  if (details.loading && !details.data) return <Skeleton className="h-96" />;
  if (!spec) return null;

  const type = spec.chart_type;
  const usesAgg = ["bar", "line", "area", "pie", "donut"].includes(type);
  const xOptions = type === "scatter" || type === "histogram" ? columns.filter(isNumeric) : type === "line" || type === "area" ? columns.filter((c) => c.type === "date" || isNumeric(c)) : type === "pie" || type === "donut" || type === "box" ? columns.filter(isCategory) : columns;
  const xIsDate = columns.find((c) => c.name === spec.x)?.type === "date";
  const showY = type !== "histogram" && !(usesAgg && spec.aggregation === "count");
  const aggOptions = type === "pie" || type === "donut" ? AGGREGATIONS.filter(([id]) => id === "sum" || id === "count") : AGGREGATIONS;

  const changeType = (next: ChartType) => {
    const nextSpec: ChartSpec = { ...spec, chart_type: next };
    const pick = (test: (c: Column) => boolean) => columns.find(test)?.name ?? null;
    const pickCategory = () => pick((c) => c.type === "category") ?? pick(isCategory);
    if (next === "bar" && (!spec.x || ["histogram", "scatter"].includes(type))) {
      nextSpec.x = pickCategory() ?? pick(() => true);
      nextSpec.y = spec.y ?? pick(isNumeric);
    }
    if ((next === "line" || next === "area") && !columns.some((c) => c.name === spec.x && (c.type === "date" || isNumeric(c)))) nextSpec.x = pick((c) => c.type === "date") ?? pick(isNumeric);
    if ((next === "pie" || next === "donut") && !columns.some((c) => c.name === spec.x && c.type === "category")) nextSpec.x = pickCategory();
    if (next === "pie" || next === "donut") { nextSpec.group = null; if (!["sum", "count"].includes(spec.aggregation ?? "")) nextSpec.aggregation = "sum"; }
    if (next === "histogram" && !columns.some((c) => c.name === spec.x && isNumeric(c))) nextSpec.x = spec.y ?? pick(isNumeric);
    if (next === "scatter") { nextSpec.x = columns.some((c) => c.name === spec.x && isNumeric(c)) ? spec.x : pick(isNumeric); nextSpec.y = columns.find((c) => isNumeric(c) && c.name !== nextSpec.x)?.name ?? nextSpec.y; }
    if (next === "box") { nextSpec.x = columns.some((c) => c.name === spec.x && isCategory(c)) ? spec.x : null; nextSpec.y = spec.y ?? pick(isNumeric); }
    setSpec(nextSpec);
  };

  return (
    <div className="grid gap-3 xl:grid-cols-[290px_minmax(0,1fr)]">
      <div className="space-y-3">
        <Card title="Chart" bodyClass="p-3">
          <div className="grid grid-cols-4 gap-1" role="radiogroup" aria-label="Chart type">
            {CHART_TYPES.map(({ id, label, icon: Icon }) => (
              <button key={id} role="radio" aria-checked={type === id} title={label} onClick={() => changeType(id)} className={cx("flex flex-col items-center gap-0.5 rounded border px-1 py-1.5 text-2xs transition-colors", type === id ? "border-primary bg-primary-soft text-blue-200" : "border-line text-muted hover:border-faint hover:text-ink")}>
                <Icon size={15} />{label}
              </button>
            ))}
          </div>
        </Card>
        <Card title="Configuration" bodyClass="space-y-2.5 p-3">
          {type !== "box" && <Field label={type === "histogram" ? "Field" : "X axis"}><Select value={spec.x ?? ""} onChange={(e) => patch({ x: e.target.value })}>{xOptions.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}</Select></Field>}
          {type === "box" && <Field label="Split by"><Select value={spec.x ?? ""} onChange={(e) => patch({ x: e.target.value })}><option value="">No split</option>{xOptions.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}</Select></Field>}
          {usesAgg && <Field label="Aggregation"><Select value={spec.aggregation} onChange={(e) => patch({ aggregation: e.target.value as ChartSpec["aggregation"] })}>{aggOptions.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</Select></Field>}
          {showY && <Field label="Y axis"><Select value={spec.y ?? ""} onChange={(e) => patch({ y: e.target.value })}><option value="" disabled>Select a numeric field</option>{columns.filter(isNumeric).map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}</Select></Field>}
          {xIsDate && usesAgg && <Field label="Time grouping"><Select value={spec.time_grain} onChange={(e) => patch({ time_grain: e.target.value as ChartSpec["time_grain"] })}>{["auto", "day", "week", "month", "quarter", "year"].map((g) => <option key={g} value={g}>{g === "auto" ? "Automatic" : g[0].toUpperCase() + g.slice(1)}</option>)}</Select></Field>}
          {["bar", "line", "area", "scatter"].includes(type) && <Field label="Group by"><Select value={spec.group ?? ""} onChange={(e) => patch({ group: e.target.value })}><option value="">None</option>{columns.filter(isCategory).map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}</Select></Field>}
          {type === "bar" && !xIsDate && <Field label="Sort"><Select value={spec.sort} onChange={(e) => patch({ sort: e.target.value as ChartSpec["sort"] })}><option value="value_desc">Largest first</option><option value="value_asc">Smallest first</option><option value="x">By X value</option></Select></Field>}
          {usesAgg && type !== "pie" && type !== "donut" && <Field label="Maximum X values"><input className="field" type="number" min={1} max={500} value={spec.limit} onChange={(e) => patch({ limit: Math.min(500, Math.max(1, Number(e.target.value) || 1)) })} /></Field>}
          {type === "histogram" && <Field label="Bins"><input className="field" type="number" min={3} max={100} value={spec.bins} onChange={(e) => patch({ bins: Math.min(100, Math.max(3, Number(e.target.value) || 3)) })} /></Field>}
        </Card>
        <Card title="Labels" bodyClass="space-y-2.5 p-3">
          <Field label="Title"><input className="field" maxLength={200} placeholder={chart.data?.title ?? "Automatic"} value={spec.title ?? ""} onChange={(e) => patch({ title: e.target.value || null })} /></Field>
          <div className="grid grid-cols-2 gap-2">
            <Field label="X label"><input className="field" maxLength={100} value={spec.x_label ?? ""} onChange={(e) => patch({ x_label: e.target.value || null })} /></Field>
            <Field label="Y label"><input className="field" maxLength={100} value={spec.y_label ?? ""} onChange={(e) => patch({ y_label: e.target.value || null })} /></Field>
          </div>
        </Card>
        <Card title="Filters" bodyClass="p-3"><FilterBuilder columns={columns} filters={filters} onChange={setFilters} /></Card>
      </div>

      <div className="min-w-0 space-y-3">
        <Card title={chart.data?.title ?? "Chart"} subtitle={chart.data ? `${formatInt(chart.data.rows_matched)} rows matched${chart.data.filters?.length ? `, filtered by ${chart.data.filters.join("; ")}` : ""}${chart.data.x_label ? ` · X: ${chart.data.x_label}` : ""}${chart.data.y_label ? ` · Y: ${chart.data.y_label}` : ""}` : undefined}
          actions={canEdit && <Button variant="primary" icon={Save} disabled={!chart.data} onClick={() => { setSaveName(activeSaved?.name ?? chart.data?.title ?? ""); setSaveOpen(true); }}>{activeSaved ? "Update" : "Save"}</Button>}>
          {chart.error ? <ErrorNote message={chart.error} /> : chart.loading && !chart.data ? <Skeleton className="h-80" /> : chart.data && <div className={cx(chart.loading && "opacity-60")}><ChartView chart={chart.data} height={380} showExport /></div>}
        </Card>
        <div className="grid gap-3 lg:grid-cols-2">
          <Card title="Saved visualisations" bodyClass="max-h-72 overflow-auto p-1.5">
            {!saved.data?.length ? <EmptyState icon={BarChart3} title="Nothing saved yet">Save a chart to reuse it later.</EmptyState> : saved.data.map((v) => (
              <div key={v.id} className={cx("group flex items-center gap-1 rounded", activeSaved?.id === v.id ? "bg-primary-soft" : "hover:bg-raised")}>
                <button className="min-w-0 flex-1 px-2 py-1.5 text-left" onClick={() => load(v)}><p className="truncate text-[13px] font-medium">{v.name}</p><p className="text-2xs text-faint">{v.spec.chart_type} · updated {timeAgo(v.updated_at)}</p></button>
                {canEdit && <button aria-label={`Delete ${v.name}`} className="mr-1 rounded p-1 text-faint opacity-0 hover:text-red-300 focus:opacity-100 group-hover:opacity-100" onClick={() => setToDelete(v)}><Trash2 size={13} /></button>}
              </div>
            ))}
          </Card>
          <Card title="Recommended charts" subtitle="Based on this dataset's column types" actions={suggestions.data && <Badge tone={suggestions.data.source === "rules" ? "violet" : "cyan"}>{suggestions.data.source === "rules" ? "Rule-based" : `Ranked by ${suggestions.data.source}`}</Badge>} bodyClass="max-h-72 overflow-auto p-1.5">
            {suggestions.data?.suggestions.map((s) => (
              <button key={s.title} className="flex w-full items-start gap-2 rounded px-2 py-1.5 text-left hover:bg-raised" onClick={() => { setSpec({ ...defaultSpec(columns), ...s.spec }); setFilters([]); setActiveSaved(null); }}>
                <Sparkles size={13} className="mt-0.5 shrink-0 text-accent" /><span className="min-w-0"><span className="block truncate text-[13px] font-medium">{s.title}</span><span className="block text-xs text-muted">{s.reason}</span></span>
              </button>
            ))}
            {suggestions.data && !suggestions.data.suggestions.length && <p className="p-2 text-xs text-muted">No suitable charts for these columns.</p>}
          </Card>
        </div>
      </div>
      <Dialog open={saveOpen} title={activeSaved ? "Update visualisation" : "Save visualisation"} width="max-w-sm" onClose={() => setSaveOpen(false)} footer={<><Button onClick={() => setSaveOpen(false)}>Cancel</Button><Button variant="primary" loading={saving} disabled={!saveName.trim()} onClick={() => void save()}>Save</Button></>}>
        <Field label="Name"><input autoFocus className="field" maxLength={200} value={saveName} onChange={(e) => setSaveName(e.target.value)} /></Field>
      </Dialog>
      <ConfirmDialog open={!!toDelete} danger title="Delete this visualisation?" confirmLabel="Delete" body={<>“{toDelete?.name}” will be removed. The dataset is not affected.</>} onClose={() => setToDelete(null)} onConfirm={() => void remove()} />
    </div>
  );
}

export default function VisualisationsPage() {
  return <RequireDataset>{(id) => <Studio key={id} datasetId={id} />}</RequireDataset>;
}
