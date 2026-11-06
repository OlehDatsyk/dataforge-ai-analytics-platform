import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Eye, FileDown, FilePlus2, FileSpreadsheet, FileText, FileType2, Plus, Trash2, X } from "lucide-react";
import { Button, Card, ConfirmDialog, Dialog, EmptyState, ErrorNote, Field, Select, StatusBadge, SyntheticBadge, TableSkeleton } from "../components/ui";
import { api, download } from "../lib/api";
import { useAuth, useDatasets, useToast } from "../lib/context";
import { formatDateTime } from "../lib/format";
import { useAsync } from "../lib/hooks";
import type { ReportSummary } from "../lib/types";

const DESCRIPTIONS: Record<string, string> = {
  dataset_overview: "Structure, column statistics, main patterns, and breakdowns.",
  data_quality: "Missing values, duplicates, and formatting issues, with suggested actions.",
  sales_performance: "Sales totals, monthly trend, and category breakdowns. Needs a date column and a revenue or sales column.",
  trend_analysis: "Numeric columns over time, with period-on-period change. Needs a date column.",
  anomaly_detection: "Statistical anomalies with their methods and explanations.",
  custom_ai: "Your own questions, each answered from calculations on the data.",
};

export function ExportButtons({ reportId, title }: { reportId: string; title: string }) {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const run = async (format: string) => {
    setBusy(format);
    try {
      await download(`/reports/${reportId}/export/${format}`, `${title}.${format}`);
    } catch (caught) {
      toast((caught as Error).message, "error");
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="flex gap-1">
      <Button size="sm" icon={FileType2} loading={busy === "pdf"} onClick={() => void run("pdf")}>PDF</Button>
      <Button size="sm" icon={FileDown} loading={busy === "csv"} onClick={() => void run("csv")}>CSV</Button>
      <Button size="sm" icon={FileSpreadsheet} loading={busy === "xlsx"} onClick={() => void run("xlsx")}>XLSX</Button>
    </div>
  );
}

export default function ReportsPage() {
  const { canEdit, workspaceKey } = useAuth();
  const { datasets, datasetId } = useDatasets();
  const toast = useToast();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [open, setOpen] = useState(params.get("new") === "1");
  const types = useAsync(() => api.get<{ id: string; label: string }[]>("/reports/types"), []);
  const list = useAsync(() => api.get<ReportSummary[]>("/reports"), [workspaceKey]);
  const ready = datasets.filter((d) => d.status === "ready");
  const [form, setForm] = useState({ dataset_id: "", report_type: "dataset_overview", title: "" });
  const [questions, setQuestions] = useState<string[]>([""]);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toDelete, setToDelete] = useState<ReportSummary | null>(null);

  useEffect(() => { if (!form.dataset_id && datasetId) setForm((f) => ({ ...f, dataset_id: datasetId })); }, [datasetId]); // eslint-disable-line

  const close = () => {
    setOpen(false);
    setError(null);
    if (params.get("new")) { params.delete("new"); setParams(params, { replace: true }); }
  };

  const create = async () => {
    setCreating(true);
    setError(null);
    try {
      const report = await api.post<ReportSummary>("/reports", { ...form, title: form.title || undefined, questions: form.report_type === "custom_ai" ? questions.filter((q) => q.trim()) : undefined });
      toast("Report generated.");
      navigate(`/reports/${report.id}`);
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setCreating(false);
    }
  };

  const remove = async () => {
    if (!toDelete) return;
    await api.delete(`/reports/${toDelete.id}`);
    setToDelete(null);
    void list.reload(true);
    toast("Report deleted.");
  };

  return (
    <div className="space-y-3">
      <div className="flex justify-end">{canEdit && <Button variant="primary" icon={FilePlus2} disabled={!ready.length} title={ready.length ? undefined : "A processed dataset is needed first"} onClick={() => setOpen(true)}>Generate report</Button>}</div>
      {list.error && <ErrorNote message={list.error} onRetry={() => void list.reload()} />}
      <Card bodyClass="overflow-x-auto">
        {list.loading && !list.data ? <TableSkeleton /> : !list.data?.length ? (
          <EmptyState icon={FileText} title="No reports yet" actions={canEdit && ready.length ? <Button variant="primary" icon={FilePlus2} onClick={() => setOpen(true)}>Generate report</Button> : undefined}>Reports combine calculated results, charts, methodology, and limitations, and they export to PDF, CSV, and XLSX.</EmptyState>
        ) : (
          <table className="data-table">
            <thead><tr><th>Report</th><th>Type</th><th>Dataset</th><th>Generated</th><th>Status</th><th>Export</th><th /></tr></thead>
            <tbody>
              {list.data.map((r) => (
                <tr key={r.id}>
                  <td className="max-w-[320px]"><span className="flex items-center gap-1.5"><Link className="truncate font-medium hover:text-blue-300" to={`/reports/${r.id}`}>{r.title}</Link>{r.is_demo && <SyntheticBadge />}</span></td>
                  <td className="text-muted">{r.report_type_label}</td>
                  <td className="max-w-[180px] truncate text-muted">{r.dataset_name}</td>
                  <td className="text-muted">{formatDateTime(r.created_at)}</td>
                  <td><StatusBadge status={r.status} /></td>
                  <td><ExportButtons reportId={r.id} title={r.title} /></td>
                  <td>
                    <div className="flex justify-end gap-0.5">
                      <Link aria-label={`Open ${r.title}`} className="rounded p-1.5 text-muted hover:bg-raised hover:text-ink" to={`/reports/${r.id}`}><Eye size={14} /></Link>
                      {canEdit && <button aria-label={`Delete ${r.title}`} className="rounded p-1.5 text-muted hover:bg-bad/20 hover:text-red-300" onClick={() => setToDelete(r)}><Trash2 size={14} /></button>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Dialog open={open} title="Generate a report" subtitle="All figures are calculated from the selected dataset's active version." onClose={close} footer={<><Button onClick={close}>Cancel</Button><Button variant="primary" icon={FilePlus2} loading={creating} disabled={!form.dataset_id} onClick={() => void create()}>Generate</Button></>}>
        <div className="space-y-3">
          {error && <ErrorNote message={error} />}
          <Field label="Dataset"><Select value={form.dataset_id} onChange={(e) => setForm({ ...form, dataset_id: e.target.value })}>{ready.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</Select></Field>
          <Field label="Report type" hint={DESCRIPTIONS[form.report_type]}><Select value={form.report_type} onChange={(e) => setForm({ ...form, report_type: e.target.value })}>{types.data?.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}</Select></Field>
          <Field label="Title (optional)"><input className="field" maxLength={200} placeholder="Automatic" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></Field>
          {form.report_type === "custom_ai" && (
            <div>
              <span className="label">Questions (up to 5)</span>
              <div className="space-y-1.5">
                {questions.map((q, i) => (
                  <div key={i} className="flex gap-1.5">
                    <input aria-label={`Question ${i + 1}`} className="field" maxLength={500} placeholder="Which region generates the most revenue?" value={q} onChange={(e) => setQuestions(questions.map((x, j) => (j === i ? e.target.value : x)))} />
                    {questions.length > 1 && <Button size="icon" variant="ghost" aria-label="Remove question" onClick={() => setQuestions(questions.filter((_, j) => j !== i))}><X size={14} /></Button>}
                  </div>
                ))}
                {questions.length < 5 && <Button size="sm" variant="ghost" icon={Plus} onClick={() => setQuestions([...questions, ""])}>Add question</Button>}
              </div>
            </div>
          )}
        </div>
      </Dialog>
      <ConfirmDialog open={!!toDelete} danger title="Delete this report?" confirmLabel="Delete report" body={<>“{toDelete?.title}” will be removed. The dataset is not affected.</>} onClose={() => setToDelete(null)} onConfirm={() => void remove()} />
    </div>
  );
}
