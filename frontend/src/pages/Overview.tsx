import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Activity, BarChart3, Bot, Database, FileText, FlaskConical, Table2, Upload } from "lucide-react";
import { tooltipStyle } from "../components/ChartView";
import { Badge, Button, Card, EmptyState, ErrorNote, Notice, Skeleton, Stat, StatusBadge, SyntheticBadge, TableSkeleton, cx } from "../components/ui";
import { api } from "../lib/api";
import { useAuth, useDatasets, useToast } from "../lib/context";
import { formatDate, formatInt, timeAgo, titleCase } from "../lib/format";
import { useAsync } from "../lib/hooks";
import type { OverviewData } from "../lib/types";

const RANGES = [{ id: "24h", label: "Last 24 hours" }, { id: "7d", label: "Last 7 days" }, { id: "30d", label: "Last 30 days" }] as const;
type Range = (typeof RANGES)[number]["id"];

const periodLabel = (value: string, unit: string) => {
  const date = new Date(unit === "hour" ? `${value}:00Z` : `${value}T00:00:00Z`);
  return unit === "hour" ? date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }) : date.toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
};

export default function OverviewPage() {
  const [range, setRange] = useState<Range>("7d");
  const { workspaceKey, canEdit } = useAuth();
  const { reloadDatasets } = useDatasets();
  const navigate = useNavigate();
  const toast = useToast();
  const [loadingDemo, setLoadingDemo] = useState(false);
  const { data, loading, error, reload } = useAsync(() => api.get<OverviewData>(`/overview?activity_range=${range}`), [range, workspaceKey]);

  const loadDemo = async () => {
    setLoadingDemo(true);
    try {
      const created = await api.post<unknown[]>("/datasets/demo");
      toast(created.length ? "Demonstration datasets are being processed." : "Demonstration datasets are already loaded.", "info");
      reloadDatasets();
      navigate("/datasets");
    } catch (caught) {
      toast((caught as Error).message, "error");
    } finally {
      setLoadingDemo(false);
    }
  };

  if (error && !data) return <ErrorNote message={error} onRetry={() => void reload()} />;
  const metrics = data?.metrics;
  const empty = metrics?.total_datasets === 0;

  const quickActions = [
    { label: "Upload Dataset", icon: Upload, to: "/datasets?upload=1", primary: true },
    { label: "Explore Data", icon: Table2, to: "/explorer" },
    { label: "Ask AI Analyst", icon: Bot, to: "/analyst" },
    { label: "Generate Report", icon: FileText, to: "/reports?new=1" },
    { label: "Create Visualisation", icon: BarChart3, to: "/visualisations" },
  ];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {quickActions.map(({ label, icon, to, primary }) => <Link key={label} to={to}><Button variant={primary ? "primary" : "secondary"} icon={icon} tabIndex={-1}>{label}</Button></Link>)}
      </div>

      {!!metrics?.demo_datasets && <Notice tone="violet" icon={FlaskConical}>This workspace includes {metrics.demo_datasets} synthetic demonstration dataset{metrics.demo_datasets === 1 ? "" : "s"}. They are generated data, not real business information, and they count toward the figures below.</Notice>}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {loading && !metrics ? Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-[76px]" />) : metrics && (
          <>
            <Stat label="Total datasets" value={formatInt(metrics.total_datasets)} />
            <Stat label="Records analysed" value={formatInt(metrics.records_analysed)} />
            <Stat label="Total analyses" value={formatInt(metrics.total_analyses)} />
            <Stat label="Active reports" value={formatInt(metrics.active_reports)} />
            <Stat label="Detected anomalies" value={formatInt(metrics.detected_anomalies)} sub="Open or under review" />
            <Stat label="Recent activity" value={formatInt(metrics.recent_activity)} sub="Analyses in 24 hours" />
          </>
        )}
      </div>

      {empty ? (
        <Card>
          <EmptyState icon={Database} title="Start with some data" actions={<>
            <Link to="/datasets?upload=1"><Button variant="primary" icon={Upload} tabIndex={-1} disabled={!canEdit}>Upload a dataset</Button></Link>
            <Button icon={FlaskConical} loading={loadingDemo} disabled={!canEdit} onClick={() => void loadDemo()}>Load demonstration data</Button>
          </>}>
            Upload a CSV, Excel, or JSON file, or load five synthetic datasets to try every feature with generated data.
          </EmptyState>
        </Card>
      ) : (
        <>
          <Card title="Analysis activity" subtitle="Completed analyses, scans, reports, and questions" actions={
            <div role="group" aria-label="Activity range" className="flex rounded-md border border-line p-0.5">
              {RANGES.map(({ id, label }) => <button key={id} aria-pressed={range === id} onClick={() => setRange(id)} className={cx("rounded px-2 py-0.5 text-xs font-medium transition-colors", range === id ? "bg-raised text-ink" : "text-muted hover:text-ink")}>{label}</button>)}
            </div>
          }>
            <div className="h-52">
              {data && (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={data.activity.points.map((p) => ({ ...p, label: periodLabel(p.period, data.activity.unit) }))} margin={{ left: -18, right: 8, top: 6 }}>
                    <CartesianGrid stroke="#263449" strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="label" stroke="#263449" tickLine={false} tick={{ fill: "#94A3B8", fontSize: 11 }} minTickGap={24} />
                    <YAxis allowDecimals={false} stroke="#263449" tickLine={false} axisLine={false} tick={{ fill: "#94A3B8", fontSize: 11 }} />
                    <Tooltip {...tooltipStyle} formatter={(v) => [formatInt(v as number), "Analyses"]} />
                    <Area type="linear" dataKey="count" stroke="#3B82F6" strokeWidth={2} fill="#3B82F6" fillOpacity={0.15} isAnimationActive={false} />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </div>
          </Card>

          <div className="grid gap-3 min-[1700px]:grid-cols-2">
            <Card title="Recent datasets" actions={<Link className="text-xs text-blue-300 hover:underline" to="/datasets">View all</Link>} bodyClass="overflow-x-auto">
              {loading && !data ? <TableSkeleton rows={4} /> : (
                <table className="data-table">
                  <thead><tr><th>Dataset</th><th>Type</th><th className="text-right">Records</th><th className="text-right">Columns</th><th>Uploaded</th><th>Status</th><th>Last analysed</th></tr></thead>
                  <tbody>
                    {data?.datasets.map((d) => (
                      <tr key={d.id}>
                        <td className="max-w-[220px]"><span className="flex items-center gap-1.5"><Link className="truncate font-medium hover:text-blue-300" to={`/explorer?dataset=${d.id}`}>{d.name}</Link>{d.is_demo && <SyntheticBadge />}{d.source_type === "connection" && <Badge tone="cyan">Connected</Badge>}</span></td>
                        <td className="uppercase text-muted">{d.file_format}</td>
                        <td className="num text-right">{formatInt(d.row_count)}</td>
                        <td className="num text-right">{formatInt(d.column_count)}</td>
                        <td className="text-muted">{formatDate(d.created_at)}</td>
                        <td><StatusBadge status={d.status} /></td>
                        <td className="text-muted">{timeAgo(d.last_analysed_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>
            <Card title="Recent analysis activity" bodyClass="overflow-x-auto">
              {data && !data.analyses.length ? <EmptyState icon={Activity} title="No analyses yet">Ask a question or run a scan to see it here.</EmptyState> : (
                <table className="data-table">
                  <thead><tr><th>Analysis</th><th>Dataset</th><th>Type</th><th>Date</th><th>Status</th><th><span className="sr-only">Actions</span></th></tr></thead>
                  <tbody>
                    {data?.analyses.map((a) => (
                      <tr key={a.id}>
                        <td className="max-w-[240px] truncate font-medium" title={a.name}>{a.name}</td>
                        <td className="max-w-[160px] truncate text-muted">{a.dataset_name ?? "-"}</td>
                        <td className="text-muted">{a.analysis_type === "ai_question" ? "AI question" : titleCase(a.analysis_type)}</td>
                        <td className="text-muted">{timeAgo(a.created_at)}</td>
                        <td><StatusBadge status={a.status} /></td>
                        <td className="text-right">{a.link && <Link className="text-xs font-medium text-blue-300 hover:underline" to={a.link}>Open</Link>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
