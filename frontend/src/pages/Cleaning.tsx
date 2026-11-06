import { useEffect, useState } from "react";
import { ArrowRight, CheckCircle2, Eye, History, Plus, Save, ShieldCheck, Sparkles, Trash2, Wand2 } from "lucide-react";
import { FilterBuilder, completeFilters } from "../components/FilterBuilder";
import { RequireDataset } from "../components/RequireDataset";
import { Badge, Button, Card, Dialog, EmptyState, ErrorNote, Field, Notice, Select, Skeleton, StatusBadge, cx } from "../components/ui";
import { api } from "../lib/api";
import { useAuth, useDatasets, useToast } from "../lib/context";
import { formatCell, formatDateTime, formatInt } from "../lib/format";
import { useAsync } from "../lib/hooks";
import type { Column, Dataset, Filter, ProfileResult } from "../lib/types";

type Operation = Record<string, any> & { op: string };

const OPERATIONS: { id: string; label: string; hint: string }[] = [
  { id: "remove_duplicates", label: "Remove duplicate rows", hint: "Keeps the first copy of each identical row." },
  { id: "fill_missing", label: "Fill missing values", hint: "Replaces blank cells in one column." },
  { id: "drop_missing", label: "Remove rows with missing values", hint: "Removes rows with blanks in the chosen column." },
  { id: "rename_column", label: "Rename column", hint: "Changes a column's name." },
  { id: "change_type", label: "Change data type", hint: "Converts values. Values that cannot convert become missing." },
  { id: "trim_whitespace", label: "Trim whitespace", hint: "Removes extra spaces in all text columns." },
  { id: "standardise_text", label: "Standardise text", hint: "Applies consistent case and spacing to a text column." },
  { id: "filter_rows", label: "Filter rows", hint: "Keeps or removes rows matching conditions." },
  { id: "drop_column", label: "Remove column", hint: "Removes a column from the new version." },
  { id: "derive_column", label: "Create derived column", hint: "Calculates a new column from numeric columns." },
];

const describe = (op: Operation): string => {
  switch (op.op) {
    case "remove_duplicates": return "Remove duplicate rows";
    case "fill_missing": return `Fill missing in ${op.column} (${op.strategy}${op.strategy === "value" ? `: ${op.value}` : ""})`;
    case "drop_missing": return `Remove rows missing ${(op.columns ?? []).join(", ")}`;
    case "rename_column": return `Rename ${op.column} to ${op.new_name}`;
    case "change_type": return `Convert ${op.column} to ${op.to}`;
    case "trim_whitespace": return `Trim whitespace${op.columns ? ` in ${op.columns.join(", ")}` : " in all text columns"}`;
    case "standardise_text": return `Standardise ${op.column} (${op.case} case)`;
    case "filter_rows": return `${op.mode === "remove" ? "Remove" : "Keep"} rows where ${op.filters.map((f: Filter) => `${f.column} ${f.op} ${f.value ?? f.values ?? ""}`).join(" and ")}`;
    case "drop_column": return `Remove column ${op.column}`;
    case "derive_column": return `Create ${op.name} = ${op.left} ${op.operator} ${op.right_column ?? op.right_value}`;
    default: return op.op;
  }
};

function OperationForm({ columns, onAdd }: { columns: Column[]; onAdd: (op: Operation) => void }) {
  const [kind, setKind] = useState("remove_duplicates");
  const [column, setColumn] = useState(columns[0]?.name ?? "");
  const [strategy, setStrategy] = useState("median");
  const [value, setValue] = useState("");
  const [newName, setNewName] = useState("");
  const [to, setTo] = useState("float");
  const [textCase, setTextCase] = useState("title");
  const [filters, setFilters] = useState<Filter[]>([]);
  const [mode, setMode] = useState("keep");
  const [operator, setOperator] = useState("multiply");
  const [rightColumn, setRightColumn] = useState("");
  const [rightValue, setRightValue] = useState("");
  const numeric = columns.filter((c) => c.type === "integer" || c.type === "float");
  const text = columns.filter((c) => c.type === "category" || c.type === "text");
  const usable = kind === "standardise_text" ? text : kind === "derive_column" ? numeric : columns;

  useEffect(() => {
    if (!usable.some((c) => c.name === column)) setColumn(usable[0]?.name ?? "");
  }, [kind, columns]); // eslint-disable-line

  const build = (): Operation | null => {
    switch (kind) {
      case "remove_duplicates": return { op: kind };
      case "fill_missing": return strategy === "value" && !value ? null : { op: kind, column, strategy, ...(strategy === "value" ? { value } : {}) };
      case "drop_missing": return { op: kind, columns: [column] };
      case "rename_column": return newName.trim() ? { op: kind, column, new_name: newName.trim() } : null;
      case "change_type": return { op: kind, column, to };
      case "trim_whitespace": return { op: kind };
      case "standardise_text": return { op: kind, column, case: textCase };
      case "filter_rows": { const done = completeFilters(filters); return done.length ? { op: kind, filters: done, mode } : null; }
      case "drop_column": return { op: kind, column };
      case "derive_column": return newName.trim() && (rightColumn || rightValue !== "") ? { op: kind, name: newName.trim(), left: column, operator, ...(rightColumn ? { right_column: rightColumn } : { right_value: Number(rightValue) }) } : null;
      default: return null;
    }
  };
  const operation = build();
  const needsColumn = !["remove_duplicates", "trim_whitespace", "filter_rows"].includes(kind);
  return (
    <div className="space-y-3">
      <Field label="Operation" hint={OPERATIONS.find((o) => o.id === kind)?.hint}>
        <Select value={kind} onChange={(e) => setKind(e.target.value)}>{OPERATIONS.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}</Select>
      </Field>
      {needsColumn && <Field label="Column"><Select value={column} onChange={(e) => setColumn(e.target.value)}>{usable.map((c) => <option key={c.name} value={c.name}>{c.name} ({c.type})</option>)}</Select></Field>}
      {kind === "fill_missing" && (
        <Field label="Fill with"><Select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
          <option value="median">Median (numbers)</option><option value="mean">Mean (numbers)</option><option value="mode">Most common value</option><option value="value">A specific value</option><option value="forward">Previous row's value</option><option value="backward">Next row's value</option>
        </Select></Field>
      )}
      {kind === "fill_missing" && strategy === "value" && <Field label="Value"><input className="field" value={value} onChange={(e) => setValue(e.target.value)} /></Field>}
      {kind === "rename_column" && <Field label="New name"><input className="field" maxLength={200} value={newName} onChange={(e) => setNewName(e.target.value)} /></Field>}
      {kind === "change_type" && <Field label="New type"><Select value={to} onChange={(e) => setTo(e.target.value)}>{["float", "integer", "date", "boolean", "category", "text"].map((t) => <option key={t}>{t}</option>)}</Select></Field>}
      {kind === "standardise_text" && <Field label="Case"><Select value={textCase} onChange={(e) => setTextCase(e.target.value)}><option value="title">Title Case</option><option value="upper">UPPER CASE</option><option value="lower">lower case</option><option value="keep">Keep case, tidy spacing only</option></Select></Field>}
      {kind === "filter_rows" && (
        <>
          <Field label="Action"><Select value={mode} onChange={(e) => setMode(e.target.value)}><option value="keep">Keep rows that match</option><option value="remove">Remove rows that match</option></Select></Field>
          <FilterBuilder columns={columns} filters={filters} onChange={setFilters} />
        </>
      )}
      {kind === "derive_column" && (
        <>
          <Field label="New column name"><input className="field" maxLength={200} value={newName} onChange={(e) => setNewName(e.target.value)} /></Field>
          <Field label="Calculation"><Select value={operator} onChange={(e) => setOperator(e.target.value)}><option value="multiply">Multiply by</option><option value="divide">Divide by</option><option value="add">Add</option><option value="subtract">Subtract</option></Select></Field>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Second column"><Select value={rightColumn} onChange={(e) => { setRightColumn(e.target.value); setRightValue(""); }}><option value="">Use a constant</option>{numeric.map((c) => <option key={c.name}>{c.name}</option>)}</Select></Field>
            <Field label="Constant"><input className="field" type="number" step="any" disabled={!!rightColumn} value={rightValue} onChange={(e) => setRightValue(e.target.value)} /></Field>
          </div>
        </>
      )}
      <Button icon={Plus} disabled={!operation} onClick={() => { if (operation) { onAdd(operation); setNewName(""); setValue(""); setFilters([]); } }}>Add to plan</Button>
    </div>
  );
}

function CleaningContent({ datasetId }: { datasetId: string }) {
  const { canEdit } = useAuth();
  const { dataset, reloadDatasets } = useDatasets();
  const toast = useToast();
  const [plan, setPlan] = useState<Operation[]>([]);
  const [preview, setPreview] = useState<any>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [saveOpen, setSaveOpen] = useState(false);
  const [saveAs, setSaveAs] = useState<"new_version" | "new_dataset">("new_version");
  const [newName, setNewName] = useState("");
  const [saving, setSaving] = useState(false);
  const profile = useAsync(() => api.get<ProfileResult>(`/datasets/${datasetId}/profile`), [datasetId, dataset?.current_version_id]);
  const history = useAsync(() => api.get<any[]>(`/datasets/${datasetId}/cleaning/history`), [datasetId, dataset?.current_version_id]);
  const details = useAsync(() => api.get<Dataset>(`/datasets/${datasetId}`), [datasetId, dataset?.current_version_id]);

  useEffect(() => { setPreview(null); setPreviewError(null); }, [JSON.stringify(plan)]);

  const runPreview = async () => {
    setPreviewing(true);
    setPreviewError(null);
    try {
      setPreview(await api.post(`/datasets/${datasetId}/cleaning/preview`, { operations: plan }));
    } catch (caught) {
      setPreviewError((caught as Error).message);
    } finally {
      setPreviewing(false);
    }
  };

  const apply = async () => {
    setSaving(true);
    try {
      const result = await api.post<{ dataset: Dataset; version: { version_number: number } }>(`/datasets/${datasetId}/cleaning/apply`, { operations: plan, save_as: saveAs, name: saveAs === "new_dataset" ? newName || undefined : undefined });
      toast(saveAs === "new_dataset" ? `Saved as a new dataset: ${result.dataset.name}.` : `Saved as version ${result.version.version_number}. The earlier version is unchanged.`);
      setPlan([]);
      setPreview(null);
      setSaveOpen(false);
      reloadDatasets();
      void history.reload(true);
      void details.reload(true);
      void profile.reload(true);
    } catch (caught) {
      toast((caught as Error).message, "error");
    } finally {
      setSaving(false);
    }
  };

  if (profile.error) return <ErrorNote message={profile.error} onRetry={() => void profile.reload()} />;
  if (!profile.data) return <div className="space-y-3"><Skeleton className="h-40" /><Skeleton className="h-64" /></div>;
  const { quality, columns } = profile.data;
  const score = quality.score;

  return (
    <div className="space-y-3">
      <Notice icon={ShieldCheck}>Cleaning never changes your original upload or any earlier version. Each saved result becomes a new version that you can compare with or restore from.</Notice>
      <div className="grid gap-3 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <Card title="Data quality" subtitle={`Version ${profile.data.version.version_number}: ${profile.data.version.label}`} actions={<span className={cx("num text-lg font-semibold", score >= 85 ? "text-green-300" : score >= 60 ? "text-amber-300" : "text-red-300")}>{score}<span className="text-xs font-normal text-muted">/100</span></span>} bodyClass="max-h-[520px] overflow-auto">
          {!quality.issues.length ? <EmptyState icon={CheckCircle2} title="No issues found">The checks found no missing values, duplicates, or formatting problems.</EmptyState> : (
            <ul>
              {quality.issues.map((issue) => (
                <li key={issue.id} className="flex items-start gap-3 border-b border-line/60 px-4 py-2.5 last:border-0">
                  <div className="min-w-0 flex-1">
                    <p className="flex flex-wrap items-center gap-1.5 text-[13px] font-medium"><StatusBadge status={issue.severity} />{issue.title}{issue.column && <span className="font-mono text-xs text-muted">{issue.column}</span>}</p>
                    <p className="mt-0.5 text-xs text-muted">{issue.detail}</p>
                  </div>
                  {issue.suggested_fix && canEdit && <Button size="sm" icon={Sparkles} onClick={() => { setPlan((all) => [...all, issue.suggested_fix as Operation]); }}>Add fix</Button>}
                </li>
              ))}
            </ul>
          )}
        </Card>
        <div className="space-y-3">
          {canEdit ? <Card title="Add a cleaning operation"><OperationForm columns={columns} onAdd={(op) => setPlan((all) => [...all, op])} /></Card> : <Notice tone="warn">Your role is read-only, so you can review quality but not apply changes.</Notice>}
          <Card title="Cleaning plan" subtitle="Operations run in this order" actions={plan.length > 0 && <Button size="sm" variant="ghost" onClick={() => setPlan([])}>Clear</Button>}>
            {!plan.length ? <p className="text-[13px] text-muted">Add a suggested fix or an operation to build a plan.</p> : (
              <div className="space-y-3">
                <ol className="space-y-1">
                  {plan.map((op, index) => (
                    <li key={index} className="flex items-center gap-2 rounded border border-line bg-raised px-2 py-1 text-[13px]">
                      <span className="num text-xs text-faint">{index + 1}</span><span className="min-w-0 flex-1 truncate" title={describe(op)}>{describe(op)}</span>
                      <button aria-label="Remove operation" className="text-faint hover:text-red-300" onClick={() => setPlan(plan.filter((_, i) => i !== index))}><Trash2 size={13} /></button>
                    </li>
                  ))}
                </ol>
                <div className="flex flex-wrap gap-2">
                  <Button icon={Eye} loading={previewing} onClick={() => void runPreview()}>Preview effect</Button>
                  <Button variant="primary" icon={Save} disabled={!preview} onClick={() => setSaveOpen(true)} title={preview ? undefined : "Preview the effect first"}>Save result</Button>
                </div>
              </div>
            )}
          </Card>
        </div>
      </div>

      {previewError && <ErrorNote message={previewError} />}
      {preview && (
        <Card title="Preview" subtitle="Nothing has been saved yet" actions={<Badge tone="warn">Not saved</Badge>}>
          <div className="space-y-3">
            <p className="num flex flex-wrap items-center gap-2 text-[13px]"><span>{formatInt(preview.rows_before)} rows</span><ArrowRight size={14} className="text-faint" /><strong>{formatInt(preview.rows_after)} rows</strong><span className="text-muted">({preview.columns_before.length} to {preview.columns_after.length} columns)</span></p>
            <ul className="space-y-2">
              {preview.effects.map((effect: any, i: number) => (
                <li key={i} className="rounded border border-line bg-raised p-2.5">
                  <p className="text-[13px]">{effect.description}</p>
                  {effect.examples?.length > 0 && (
                    <div className="mt-1.5 overflow-x-auto">
                      <table className="text-xs">
                        <thead><tr className="text-left text-faint"><th className="pr-4 font-medium">Row</th><th className="pr-4 font-medium">Before</th><th className="font-medium">After</th></tr></thead>
                        <tbody>{effect.examples.map((ex: any, j: number) => <tr key={j}><td className="num pr-4 text-faint">{ex.row}</td><td className="pr-4 text-red-200">{ex.before === null ? <em>missing</em> : `"${formatCell(ex.before)}"`}</td><td className="text-green-200">{ex.after === null ? <em>missing</em> : `"${formatCell(ex.after)}"`}</td></tr>)}</tbody>
                      </table>
                    </div>
                  )}
                </li>
              ))}
            </ul>
            <div>
              <h3 className="mb-1 text-xs font-medium text-muted">First rows of the result</h3>
              <div className="max-h-64 overflow-auto rounded border border-line">
                <table className="data-table">
                  <thead><tr>{preview.columns_after.map((c: string) => <th key={c}>{c}</th>)}</tr></thead>
                  <tbody>{preview.sample.map((row: any, i: number) => <tr key={i}>{preview.columns_after.map((c: string) => <td key={c} className="max-w-[220px] truncate">{row[c] === null ? <span className="text-faint">null</span> : formatCell(row[c])}</td>)}</tr>)}</tbody>
                </table>
              </div>
            </div>
          </div>
        </Card>
      )}

      <div className="grid gap-3 lg:grid-cols-2">
        <Card title="Versions" bodyClass="overflow-x-auto">
          <table className="data-table">
            <thead><tr><th>Version</th><th>Description</th><th className="text-right">Rows</th><th>Created</th></tr></thead>
            <tbody>{details.data?.versions?.map((v) => <tr key={v.id}><td className="num">v{v.version_number} {v.is_current && <Badge tone="blue">Active</Badge>}</td><td className="max-w-[260px] truncate text-muted" title={v.label}>{v.label}</td><td className="num text-right">{formatInt(v.row_count)}</td><td className="text-muted">{formatDateTime(v.created_at)}</td></tr>)}</tbody>
          </table>
        </Card>
        <Card title="Cleaning history" bodyClass="max-h-72 overflow-auto">
          {!history.data?.length ? <EmptyState icon={History} title="No cleaning yet">Saved operations are recorded here.</EmptyState> : (
            <ul>{history.data.map((h) => <li key={h.id} className="border-b border-line/60 px-4 py-2 last:border-0"><p className="text-xs text-faint">{formatDateTime(h.created_at)}: {formatInt(h.summary.rows_before)} to {formatInt(h.summary.rows_after)} rows</p>{h.summary.effects.map((e: any, i: number) => <p key={i} className="text-[13px]">{e.description}</p>)}</li>)}</ul>
          )}
        </Card>
      </div>

      <Dialog open={saveOpen} title="Save the cleaned result" subtitle="The current version stays unchanged either way." width="max-w-md" onClose={() => setSaveOpen(false)} footer={<><Button onClick={() => setSaveOpen(false)}>Cancel</Button><Button variant="primary" icon={Wand2} loading={saving} onClick={() => void apply()}>Confirm and save</Button></>}>
        <div className="space-y-3">
          {preview && <p className="num text-[13px] text-muted">{plan.length} operation(s): {formatInt(preview.rows_before)} rows become {formatInt(preview.rows_after)}.</p>}
          {([["new_version", "New version of this dataset", "It becomes the active version. You can restore earlier versions at any time."], ["new_dataset", "New separate dataset", "This dataset stays as it is, and the result appears as its own dataset."]] as const).map(([id, title, text]) => (
            <label key={id} className={cx("flex cursor-pointer gap-2.5 rounded border p-2.5", saveAs === id ? "border-primary bg-primary-soft" : "border-line")}>
              <input type="radio" name="save-as" className="mt-0.5 accent-primary" checked={saveAs === id} onChange={() => setSaveAs(id)} />
              <span><span className="block text-[13px] font-medium">{title}</span><span className="text-xs text-muted">{text}</span></span>
            </label>
          ))}
          {saveAs === "new_dataset" && <Field label="Name"><input className="field" maxLength={200} placeholder={`${dataset?.name ?? "Dataset"} (cleaned)`} value={newName} onChange={(e) => setNewName(e.target.value)} /></Field>}
        </div>
      </Dialog>
    </div>
  );
}

export default function CleaningPage() {
  return <RequireDataset>{(id) => <CleaningContent key={id} datasetId={id} />}</RequireDataset>;
}
