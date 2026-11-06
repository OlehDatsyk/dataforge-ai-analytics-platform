import { useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ChevronsUpDown, Columns3, Download, Search, SlidersHorizontal, Table2, Sigma } from "lucide-react";
import { completeFilters, FilterBuilder } from "../components/FilterBuilder";
import { RequireDataset } from "../components/RequireDataset";
import { Badge, Button, Card, Dialog, EmptyState, ErrorNote, Notice, Pagination, Select, Skeleton, Stat, SyntheticBadge, TableSkeleton, Tabs, cx } from "../components/ui";
import { api, download, remember } from "../lib/api";
import { useDatasets, useToast } from "../lib/context";
import { formatCell, formatDate, formatInt, formatNumber } from "../lib/format";
import { useAsync, useDebounced } from "../lib/hooks";
import type { ColumnProfile, DataType, Dataset, Filter, ProfileResult, RowsResult } from "../lib/types";

const TYPE_TONE: Record<DataType, "blue" | "cyan" | "violet" | "neutral" | "good"> = { integer: "blue", float: "blue", date: "cyan", category: "violet", boolean: "good", text: "neutral" };
export const TypeBadge = ({ type }: { type: DataType }) => <Badge tone={TYPE_TONE[type]}>{type}</Badge>;

function RecordsTab({ datasetId, profile, versionId }: { datasetId: string; profile: ProfileResult; versionId: string }) {
  const toast = useToast();
  const allColumns = profile.columns;
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [sort, setSort] = useState<{ column: string; direction: "asc" | "desc" } | null>(null);
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<Filter[]>([]);
  const [hidden, setHidden] = useState<string[]>([]);
  const [columnsOpen, setColumnsOpen] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [exporting, setExporting] = useState(false);
  const debouncedSearch = useDebounced(search);
  const active = completeFilters(useDebounced(filters, 350));
  const visible = allColumns.filter((c) => !hidden.includes(c.name));

  useEffect(() => setPage(1), [debouncedSearch, JSON.stringify(active), pageSize, sort, versionId]);
  useEffect(() => { setFilters([]); setHidden([]); setSort(null); setSearch(""); }, [datasetId]);

  const body = { page, page_size: pageSize, sort: sort ? [sort] : [], filters: active, search: debouncedSearch || null, columns: visible.map((c) => c.name), version_id: versionId };
  const { data, loading, error } = useAsync(() => api.post<RowsResult>(`/datasets/${datasetId}/rows`, body), [datasetId, JSON.stringify(body)]);

  const toggleSort = (column: string) => setSort((current) => {
    if (current?.column !== column) return { column, direction: "asc" };
    return current.direction === "asc" ? { column, direction: "desc" } : null;
  });

  const exportCsv = async () => {
    setExporting(true);
    try {
      await download(`/datasets/${datasetId}/export`, "dataset.csv", { ...body, page: 1, page_size: 50 });
      toast("Export downloaded. Spreadsheet formulas are neutralised.", "success");
    } catch (caught) {
      toast((caught as Error).message, "error");
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[180px] flex-1 sm:max-w-xs">
          <Search size={14} className="pointer-events-none absolute left-2.5 top-2 text-faint" />
          <input aria-label="Search rows" className="field !pl-8" placeholder="Search text columns" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <Button icon={SlidersHorizontal} onClick={() => setFiltersOpen(!filtersOpen)} aria-expanded={filtersOpen}>Filters{active.length ? ` (${active.length})` : ""}</Button>
        <Button icon={Columns3} onClick={() => setColumnsOpen(true)}>Columns ({visible.length}/{allColumns.length})</Button>
        <div className="ml-auto flex items-center gap-2">
          <label className="flex items-center gap-1.5 text-xs text-muted">Rows per page
            <Select className="!h-7 !w-[72px] text-xs" value={pageSize} onChange={(e) => setPageSize(Number(e.target.value))}>{[25, 50, 100, 250].map((n) => <option key={n}>{n}</option>)}</Select>
          </label>
          <Button icon={Download} loading={exporting} onClick={() => void exportCsv()}>Export CSV</Button>
        </div>
      </div>
      {filtersOpen && <Card bodyClass="p-3"><FilterBuilder columns={allColumns} filters={filters} onChange={setFilters} /></Card>}
      {error && <ErrorNote message={error} />}
      <Card bodyClass="">
        <div className="max-h-[62vh] overflow-auto">
          {loading && !data ? <TableSkeleton rows={10} /> : data && (
            <table className={cx("data-table", loading && "opacity-60")}>
              <thead>
                <tr>
                  <th className="text-right">#</th>
                  {visible.map((c) => (
                    <th key={c.name} aria-sort={sort?.column === c.name ? (sort.direction === "asc" ? "ascending" : "descending") : "none"}>
                      <button className="flex items-center gap-1 normal-case tracking-normal hover:text-ink" onClick={() => toggleSort(c.name)}>
                        <span className="text-[12px] font-semibold">{c.name}</span>
                        {sort?.column === c.name ? (sort.direction === "asc" ? <ArrowUp size={12} /> : <ArrowDown size={12} />) : <ChevronsUpDown size={12} className="text-faint" />}
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <tr key={String(row.__row_id)}>
                    <td className="num text-right text-faint">{formatInt(row.__row_id as number)}</td>
                    {visible.map((c) => {
                      const value = row[c.name];
                      const numeric = c.type === "integer" || c.type === "float";
                      return <td key={c.name} className={cx("max-w-[280px] truncate", numeric && "num text-right")} title={value === null ? "Missing" : String(value)}>{value === null || value === undefined ? <span className="text-faint">null</span> : formatCell(value)}</td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {data && !data.rows.length && <EmptyState icon={Table2} title="No rows match">Adjust the search or filters.</EmptyState>}
        </div>
        {data && <Pagination page={data.page} pageCount={data.page_count} total={data.total} onPage={setPage} />}
      </Card>
      <Dialog open={columnsOpen} title="Choose columns" width="max-w-md" onClose={() => setColumnsOpen(false)} footer={<><Button onClick={() => setHidden([])}>Show all</Button><Button variant="primary" onClick={() => setColumnsOpen(false)}>Done</Button></>}>
        <div className="space-y-1">
          {allColumns.map((c) => (
            <label key={c.name} className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 hover:bg-raised">
              <input type="checkbox" className="accent-primary" checked={!hidden.includes(c.name)} disabled={visible.length === 1 && !hidden.includes(c.name)} onChange={(e) => setHidden(e.target.checked ? hidden.filter((h) => h !== c.name) : [...hidden, c.name])} />
              <span className="flex-1 truncate text-[13px]">{c.name}</span><TypeBadge type={c.type} />
            </label>
          ))}
        </div>
      </Dialog>
    </div>
  );
}

function Bars({ items }: { items: { label: string; value: number; share?: number }[] }) {
  const max = Math.max(...items.map((i) => i.value), 1);
  return (
    <div className="space-y-1.5">
      {items.map((item) => (
        <div key={item.label} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)_auto] items-center gap-2 text-xs">
          <span className="truncate" title={item.label}>{item.label}</span>
          <span className="h-1.5 overflow-hidden rounded-sm bg-raised"><span className="block h-full rounded-sm bg-primary" style={{ width: `${(item.value / max) * 100}%` }} /></span>
          <span className="num text-right text-muted">{formatInt(item.value)}{item.share !== undefined ? ` · ${(item.share * 100).toFixed(1)}%` : ""}</span>
        </div>
      ))}
    </div>
  );
}

function Histogram({ bins }: { bins: { start: number; end: number; count: number }[] }) {
  const max = Math.max(...bins.map((b) => b.count), 1);
  return (
    <div>
      <div className="flex h-24 items-end gap-0.5" role="img" aria-label="Value distribution">
        {bins.map((b, i) => <div key={i} title={`${formatNumber(b.start)} to ${formatNumber(b.end)}: ${formatInt(b.count)}`} className="flex-1 rounded-t-sm bg-primary/80 transition-colors hover:bg-primary" style={{ height: `${Math.max((b.count / max) * 100, b.count ? 2 : 0)}%` }} />)}
      </div>
      <div className="num mt-1 flex justify-between text-2xs text-faint"><span>{formatNumber(bins[0]?.start)}</span><span>{formatNumber(bins[bins.length - 1]?.end)}</span></div>
    </div>
  );
}

function ColumnDetail({ column }: { column: ColumnProfile }) {
  const numeric = column.type === "integer" || column.type === "float";
  const stats: [string, string][] = [["Values", formatInt(column.count)], ["Missing", `${formatInt(column.missing)} (${column.missing_pct}%)`], ["Unique", formatInt(column.unique)]];
  if (numeric) stats.push(["Mean", formatNumber(column.mean)], ["Median", formatNumber(column.median)], ["Minimum", formatNumber(column.min)], ["Maximum", formatNumber(column.max)], ["Std. deviation", formatNumber(column.std)], ["Lower quartile", formatNumber(column.q1)], ["Upper quartile", formatNumber(column.q3)], ["Zeros", formatInt(column.zero_count)]);
  if (column.type === "date") stats.push(["Earliest", formatDate(column.earliest)], ["Latest", formatDate(column.latest)], ["Range", `${formatInt(column.range_days)} days`], ["Frequency", column.frequency ?? "Not determined"]);
  if (column.type === "boolean") stats.push(["True", formatInt(column.true_count)], ["False", formatInt(column.false_count)]);
  if (column.type === "text") stats.push(["Empty", formatInt(column.empty_count)], ["Average length", formatNumber(column.average_length)], ["Shortest", formatInt(column.min_length)], ["Longest", formatInt(column.max_length)]);
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2"><h3 className="text-sm font-semibold">{column.name}</h3><TypeBadge type={column.type} /></div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2.5 sm:grid-cols-3 lg:grid-cols-4">
        {stats.map(([k, v]) => <div key={k}><dt className="text-xs text-muted">{k}</dt><dd className="num text-[13px] font-medium">{v}</dd></div>)}
      </dl>
      {column.histogram && column.histogram.length > 1 && <div><h4 className="mb-2 text-xs font-medium text-muted">Distribution</h4><Histogram bins={column.histogram} /></div>}
      {column.top_values && column.top_values.length > 0 && <div><h4 className="mb-2 text-xs font-medium text-muted">Most common values</h4><Bars items={column.top_values.map((t) => ({ label: String(t.value), value: t.count, share: t.share }))} /></div>}
    </div>
  );
}

function ProfileTab({ profile }: { profile: ProfileResult }) {
  const [selected, setSelected] = useState(profile.profile.columns[0]?.name);
  const column = profile.profile.columns.find((c) => c.name === selected) ?? profile.profile.columns[0];
  return (
    <div className="grid gap-3 lg:grid-cols-[300px_minmax(0,1fr)]">
      <Card bodyClass="max-h-[66vh] overflow-auto p-1.5">
        {profile.profile.columns.map((c) => (
          <button key={c.name} onClick={() => setSelected(c.name)} aria-current={c.name === column?.name} className={cx("flex w-full items-center gap-2 rounded px-2 py-1.5 text-left transition-colors", c.name === column?.name ? "bg-primary-soft" : "hover:bg-raised")}>
            <span className="min-w-0 flex-1 truncate text-[13px] font-medium">{c.name}</span>
            {c.missing > 0 && <span className="num text-2xs text-amber-300" title="Missing values">{c.missing_pct}%</span>}
            <TypeBadge type={c.type} />
          </button>
        ))}
      </Card>
      <Card>{column && <ColumnDetail column={column} />}</Card>
    </div>
  );
}

function ExplorerContent({ datasetId, dataset }: { datasetId: string; dataset: Dataset | null }) {
  const key = "dataforge.explorer.tab";
  const [tab, setTabState] = useState<"records" | "profile">((remember.get(key) as "records" | "profile") ?? "records");
  const setTab = (next: "records" | "profile") => { setTabState(next); remember.set(key, next); };
  const [versionId, setVersionId] = useState<string | null>(null);
  const details = useAsync(() => api.get<Dataset>(`/datasets/${datasetId}`), [datasetId, dataset?.current_version_id]);
  useEffect(() => setVersionId(null), [datasetId, dataset?.current_version_id]);
  const current = versionId ?? dataset?.current_version_id ?? "";
  const { data: profile, loading, error, reload } = useAsync(() => api.get<ProfileResult>(`/datasets/${datasetId}/profile${current ? `?version_id=${current}` : ""}`), [datasetId, current]);
  const summary = useMemo(() => profile?.profile, [profile]);

  if (error) return <ErrorNote message={error} onRetry={() => void reload()} />;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {dataset?.is_demo && <SyntheticBadge />}
        {dataset?.source_type === "connection" && <Badge tone="cyan">Imported from a data connection</Badge>}
        {!!details.data?.versions && details.data.versions.length > 1 && (
          <label className="ml-auto flex items-center gap-1.5 text-xs text-muted">Version
            <Select className="!h-7 !w-64 text-xs" value={current} onChange={(e) => setVersionId(e.target.value)}>
              {details.data.versions.map((v) => <option key={v.id} value={v.id}>v{v.version_number}{v.is_current ? " (active)" : ""}: {v.label}</option>)}
            </Select>
          </label>
        )}
      </div>
      {dataset?.is_demo && <Notice tone="violet">This dataset is synthetic demonstration data. Its values were generated and do not describe a real business.</Notice>}
      {loading && !profile ? <div className="grid grid-cols-2 gap-3 md:grid-cols-5">{Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-[72px]" />)}</div> : summary && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          <Stat label="Rows" value={formatInt(summary.row_count)} />
          <Stat label="Columns" value={formatInt(summary.column_count)} />
          <Stat label="Missing cells" value={`${summary.missing_pct}%`} sub={`${formatInt(summary.missing_cells)} of ${formatInt(summary.total_cells)}`} tone={summary.missing_pct > 5 ? "warn" : undefined} />
          <Stat label="Duplicate rows" value={formatInt(summary.duplicate_rows)} tone={summary.duplicate_rows ? "warn" : undefined} />
          <Stat label="Quality score" value={`${profile?.quality.score}/100`} sub={`${profile?.quality.issue_count} issue(s) found`} />
        </div>
      )}
      <Tabs tabs={[{ id: "records", label: "Records", icon: Table2 }, { id: "profile", label: "Column profile", icon: Sigma }]} value={tab} onChange={setTab} />
      {profile && (tab === "records" ? <RecordsTab datasetId={datasetId} profile={profile} versionId={profile.version.id} /> : <ProfileTab profile={profile} />)}
    </div>
  );
}

export default function ExplorerPage() {
  const { dataset } = useDatasets();
  return <RequireDataset>{(id) => <ExplorerContent key={id} datasetId={id} dataset={dataset} />}</RequireDataset>;
}
