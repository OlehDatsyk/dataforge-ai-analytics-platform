import { Link, useParams } from "react-router-dom";
import { ArrowLeft, FlaskConical } from "lucide-react";
import { ChartView } from "../components/ChartView";
import { Badge, Card, ErrorNote, Notice, Skeleton, Stat, cx } from "../components/ui";
import { api } from "../lib/api";
import { formatCell, formatDateTime, formatInt, titleCase } from "../lib/format";
import { useAsync } from "../lib/hooks";
import type { ReportSummary } from "../lib/types";
import { ExportButtons } from "./Reports";

const List = ({ items, muted }: { items: string[]; muted?: boolean }) => (
  <ul className={cx("list-disc space-y-1 pl-4 text-[13px] marker:text-faint", muted && "text-muted")}>{items.map((item) => <li key={item}>{item}</li>)}</ul>
);

export default function ReportDetailPage() {
  const { reportId } = useParams();
  const { data, loading, error, reload } = useAsync(() => api.get<ReportSummary>(`/reports/${reportId}`), [reportId]);
  if (error) return <ErrorNote message={error} onRetry={() => void reload()} />;
  if (loading || !data?.content) return <div className="space-y-3"><Skeleton className="h-24" /><Skeleton className="h-96" /></div>;
  const c = data.content;
  return (
    <article className="mx-auto max-w-5xl space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link className="flex items-center gap-1 text-xs text-muted hover:text-ink" to="/reports"><ArrowLeft size={13} />All reports</Link>
        <ExportButtons reportId={data.id} title={c.title} />
      </div>
      <header className="rounded-lg border border-line bg-surface p-4 shadow-card">
        <div className="flex flex-wrap items-center gap-1.5"><Badge tone="blue">{c.report_type_label}</Badge>{c.ai && <Badge tone={c.ai.mode === "demonstration" ? "violet" : "cyan"}>{c.ai.mode === "demonstration" ? "Demonstration planner: no AI model" : `AI: ${c.ai.provider}`}</Badge>}</div>
        <h2 className="mt-2 text-lg font-semibold">{c.title}</h2>
        <p className="mt-1 text-xs text-muted">{c.workspace} · {c.dataset} (version {c.version}) · Generated {formatDateTime(c.generated_at)}</p>
      </header>
      {c.is_demo && <Notice tone="violet" icon={FlaskConical}>This report uses a synthetic demonstration dataset. It does not describe a real business.</Notice>}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Rows" value={formatInt(c.overview.rows)} />
        <Stat label="Columns" value={formatInt(c.overview.columns)} />
        <Stat label="Missing cells" value={`${c.overview.missing_pct}%`} />
        <Stat label="Duplicate rows" value={formatInt(c.overview.duplicate_rows)} />
        <Stat label="Quality score" value={`${c.overview.quality_score}/100`} />
      </div>
      <Card title="Executive summary"><List items={c.executive_summary} /></Card>
      <Card title="Analysis methodology"><List items={c.methodology} muted /></Card>
      {c.sections.map((section) => (
        <Card key={section.heading} title={section.heading} subtitle={section.text ?? undefined}>
          <div className="space-y-3">
            {section.chart && <ChartView chart={section.chart} height={260} />}
            {section.findings.length > 0 && <List items={section.findings} />}
            {section.table && section.table.rows.length > 0 && (
              <div className="max-h-96 overflow-auto rounded border border-line">
                <table className="data-table">
                  <thead><tr>{section.table.columns.map((col) => <th key={col}>{titleCase(col)}</th>)}</tr></thead>
                  <tbody>{section.table.rows.map((row, i) => <tr key={i}>{section.table!.columns.map((col) => <td key={col} className={cx("max-w-[360px] truncate", typeof row[col] === "number" && "num text-right")} title={String(row[col] ?? "")}>{formatCell(row[col])}</td>)}</tr>)}</tbody>
                </table>
              </div>
            )}
          </div>
        </Card>
      ))}
      <div className="grid gap-3 md:grid-cols-2">
        <Card title="Recommendations">{c.recommendations.length ? <List items={c.recommendations} /> : <p className="text-[13px] text-muted">No specific actions follow from these results.</p>}</Card>
        <Card title="Limitations"><List items={c.limitations} muted /></Card>
      </div>
      <p className="pb-2 text-xs text-faint">DataForge AI supports analysis. Review its assumptions and verify important decisions independently.</p>
    </article>
  );
}
