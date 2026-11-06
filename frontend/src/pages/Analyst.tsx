import { useEffect, useRef, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { AlertTriangle, Bot, Calculator, ChevronDown, Database, FlaskConical, Lightbulb, MessageSquarePlus, Send, ShieldCheck, Trash2, User as UserIcon } from "lucide-react";
import { ChartView } from "../components/ChartView";
import { RequireDataset } from "../components/RequireDataset";
import { Badge, Button, Card, ConfirmDialog, EmptyState, ErrorNote, Notice, Skeleton, cx } from "../components/ui";
import { api } from "../lib/api";
import { useAuth, useDatasets, useToast } from "../lib/context";
import { formatCell, timeAgo, titleCase } from "../lib/format";
import { useAsync } from "../lib/hooks";
import type { AIMessage, AIStatus, AnalystResponse, Conversation } from "../lib/types";

const STARTERS = ["Summarise this dataset", "What are the main trends?", "Are there unusual changes over time?", "Which chart should I use for this data?"];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <div><h4 className="mb-1 text-2xs font-semibold uppercase tracking-wide text-muted">{title}</h4>{children}</div>;
}

export function AnswerCard({ answer, onFollowUp }: { answer: AnalystResponse; onFollowUp?: (question: string) => void }) {
  const [showData, setShowData] = useState(true);
  const { supporting_data: table, provenance } = answer;
  return (
    <div className="space-y-3 rounded-lg border border-line bg-surface p-3.5 shadow-card">
      <div className="flex flex-wrap items-center gap-1.5">
        {answer.mode === "demonstration"
          ? <Badge tone="violet" title="Questions are parsed by rules, and text comes from templates. No AI model was used."><FlaskConical size={11} />Demonstration mode: no AI model</Badge>
          : <Badge tone="cyan"><Bot size={11} />{answer.narrated_by === "ai" ? `Explained by ${answer.provider} (${answer.model})` : `Planned by ${answer.provider}; summary from the engine`}</Badge>}
        {answer.status === "answered" ? <Badge tone="good"><Calculator size={11} />Calculated from your data</Badge> : <Badge tone="warn"><AlertTriangle size={11} />Could not be answered</Badge>}
      </div>
      {answer.notices.map((n) => <Notice key={n} tone="warn" icon={AlertTriangle}>{n}</Notice>)}
      <p className="text-sm font-medium leading-relaxed">{answer.direct_answer}</p>
      {answer.assumptions.length > 0 && <Notice icon={Lightbulb}>{answer.assumptions.map((a) => <p key={a}>Assumption: {a}</p>)}</Notice>}
      {answer.chart && answer.chart.rows.length > 0 && <div className="rounded-md border border-line p-3"><p className="mb-2 text-xs font-medium text-muted">{answer.chart.title}</p><ChartView chart={answer.chart} height={240} /></div>}
      {answer.key_findings.length > 0 && <Section title="Key findings"><ul className="list-disc space-y-0.5 pl-4 text-[13px] marker:text-faint">{answer.key_findings.map((f) => <li key={f}>{f}</li>)}</ul></Section>}
      {table.rows.length > 0 && (
        <div>
          <button className="mb-1 flex items-center gap-1 text-2xs font-semibold uppercase tracking-wide text-muted hover:text-ink" aria-expanded={showData} onClick={() => setShowData(!showData)}>Supporting data <ChevronDown size={12} className={cx("transition-transform", !showData && "-rotate-90")} /></button>
          {showData && (
            <div className="max-h-64 overflow-auto rounded-md border border-line">
              <table className="data-table">
                <thead><tr>{table.columns.map((c) => <th key={c} className={cx(typeof table.rows[0]?.[c] === "number" && "text-right")}>{titleCase(c)}</th>)}</tr></thead>
                <tbody>{table.rows.map((row, i) => <tr key={i}>{table.columns.map((c) => <td key={c} className={cx("max-w-[320px] truncate", typeof row[c] === "number" && "num text-right")} title={String(row[c] ?? "")}>{formatCell(row[c])}</td>)}</tr>)}</tbody>
              </table>
            </div>
          )}
          {table.total_rows > table.rows.length && <p className="mt-1 text-xs text-faint">Showing {table.rows.length} of {table.total_rows} result rows.</p>}
        </div>
      )}
      {answer.interpretation && <Section title="Interpretation"><p className="text-[13px] text-slate-300">{answer.interpretation}</p></Section>}
      {answer.limitations.length > 0 && <Section title="Limitations"><ul className="list-disc space-y-0.5 pl-4 text-[13px] text-muted marker:text-faint">{answer.limitations.map((l) => <li key={l}>{l}</li>)}</ul></Section>}
      {answer.follow_ups.length > 0 && onFollowUp && (
        <Section title="Suggested follow-up analysis">
          <div className="flex flex-wrap gap-1.5">{answer.follow_ups.map((q) => <button key={q} className="rounded-full border border-line px-2.5 py-0.5 text-xs text-blue-200 transition-colors hover:border-primary hover:bg-primary-soft" onClick={() => onFollowUp(q)}>{q}</button>)}</div>
        </Section>
      )}
      <details className="rounded-md border border-line bg-canvas/60 px-3 py-2 text-xs text-muted">
        <summary className="cursor-pointer font-medium text-muted hover:text-ink">How this was calculated</summary>
        <dl className="mt-2 grid gap-x-4 gap-y-1.5 sm:grid-cols-2">
          <div><dt className="text-faint">Dataset</dt><dd className="text-ink">{provenance.dataset} (version {provenance.version})</dd></div>
          <div><dt className="text-faint">Rows used</dt><dd className="num text-ink">{provenance.rows_used.toLocaleString("en-GB")}</dd></div>
          <div className="sm:col-span-2"><dt className="text-faint">Calculation</dt><dd className="text-ink">{provenance.calculation || "None"}</dd></div>
          <div><dt className="text-faint">Columns</dt><dd className="text-ink">{provenance.columns.join(", ") || "None"}</dd></div>
          <div><dt className="text-faint">Filters</dt><dd className="text-ink">{provenance.filters.join("; ") || "None"}</dd></div>
          {provenance.time_range && <div><dt className="text-faint">Time range</dt><dd className="text-ink">{provenance.time_range}</dd></div>}
          <div className="sm:col-span-2"><dt className="text-faint">Sent to an AI provider</dt><dd className="text-ink">{answer.data_shared_with_ai ? `Column names and types${answer.data_shared_with_ai.category_labels ? ", common category labels" : ""}, and ${answer.data_shared_with_ai.aggregated_result_rows} aggregated result rows. No raw records.` : "Nothing. This answer was produced locally."}</dd></div>
        </dl>
      </details>
    </div>
  );
}

function AnalystContent({ datasetId }: { datasetId: string }) {
  const { canEdit } = useAuth();
  const { dataset, setDatasetId } = useDatasets();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const conversationId = params.get("conversation");
  const [question, setQuestion] = useState("");
  const [sending, setSending] = useState(false);
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [toDelete, setToDelete] = useState<Conversation | null>(null);
  const end = useRef<HTMLDivElement>(null);

  const status = useAsync(() => api.get<AIStatus>("/analyst/status"), []);
  const list = useAsync(() => api.get<Conversation[]>(`/analyst/conversations?dataset_id=${datasetId}`), [datasetId]);
  const conversation = useAsync(() => (conversationId ? api.get<Conversation>(`/analyst/conversations/${conversationId}`) : Promise.resolve(null)), [conversationId]);
  const messages: AIMessage[] = conversation.data?.messages ?? [];

  useEffect(() => {
    if (conversation.data && conversation.data.dataset_id !== datasetId) setDatasetId(conversation.data.dataset_id);
  }, [conversation.data]); // eslint-disable-line

  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [messages.length, pendingQuestion]);

  const setConversation = (id: string | null) => {
    const next = new URLSearchParams(params);
    if (id) next.set("conversation", id); else next.delete("conversation");
    setParams(next);
  };

  const ask = async (text: string) => {
    const value = text.trim();
    if (value.length < 2 || sending) return;
    setSending(true);
    setError(null);
    setPendingQuestion(value);
    setQuestion("");
    try {
      const sameDataset = conversation.data?.dataset_id === datasetId;
      const result = await api.post<{ conversation_id: string }>("/analyst/ask", { dataset_id: datasetId, question: value, conversation_id: sameDataset ? conversationId : undefined });
      if (result.conversation_id !== conversationId) setConversation(result.conversation_id);
      else await conversation.reload(true);
      void list.reload(true);
    } catch (caught) {
      setError((caught as Error).message);
      setQuestion(value);
    } finally {
      setSending(false);
      setPendingQuestion(null);
    }
  };

  const submit = (event: FormEvent) => { event.preventDefault(); void ask(question); };

  const removeConversation = async () => {
    if (!toDelete) return;
    await api.delete(`/analyst/conversations/${toDelete.id}`);
    if (toDelete.id === conversationId) setConversation(null);
    setToDelete(null);
    void list.reload(true);
    toast("Conversation deleted.");
  };

  const showConversation = conversationId && conversation.data && conversation.data.dataset_id === datasetId;

  return (
    <div className="grid gap-3 lg:grid-cols-[250px_minmax(0,1fr)]">
      <div className="space-y-3">
        <Button className="w-full" icon={MessageSquarePlus} onClick={() => setConversation(null)}>New conversation</Button>
        <Card title="History" bodyClass="max-h-[50vh] overflow-auto p-1.5 lg:max-h-[68vh]">
          {list.loading && !list.data ? <Skeleton className="h-16" /> : !list.data?.length ? <p className="p-2 text-xs text-muted">Your questions about this dataset are saved here.</p> : list.data.map((c) => (
            <div key={c.id} className={cx("group flex items-center gap-1 rounded", c.id === conversationId ? "bg-primary-soft" : "hover:bg-raised")}>
              <button className="min-w-0 flex-1 px-2 py-1.5 text-left" onClick={() => setConversation(c.id)}>
                <p className="truncate text-[13px]">{c.title}</p><p className="text-2xs text-faint">{timeAgo(c.updated_at)}</p>
              </button>
              <button aria-label={`Delete conversation: ${c.title}`} className="mr-1 rounded p-1 text-faint opacity-0 hover:text-red-300 focus:opacity-100 group-hover:opacity-100" onClick={() => setToDelete(c)}><Trash2 size={13} /></button>
            </div>
          ))}
        </Card>
      </div>

      <div className="flex min-h-[calc(100vh-7rem)] flex-col gap-3">
        {status.data?.mode === "demonstration" ? (
          <Notice tone="violet" icon={FlaskConical}><strong>Demonstration mode.</strong> No AI provider is configured, so questions are parsed by rules and explained with templates. The calculations are genuine, and no data leaves this server. {status.data.problem ?? "Add an API key to enable a live AI model."}</Notice>
        ) : status.data && (
          <Notice icon={ShieldCheck}><strong>Live AI: {status.data.provider} ({status.data.model}).</strong> Column names and types{status.data.shares_category_values ? ", common category labels," : ""} and aggregated results are sent to this provider. Raw rows are not. All figures come from the data engine.</Notice>
        )}

        <div className="flex-1 space-y-3">
          {!showConversation && !pendingQuestion && (
            <Card>
              <EmptyState icon={Bot} title={`Ask about ${dataset?.name ?? "this dataset"}`}>Answers show the exact values, columns, and filters behind them. If something can't be calculated from this data, the analyst says so.</EmptyState>
              <div className="flex flex-wrap justify-center gap-1.5 pb-2">{STARTERS.map((q) => <button key={q} disabled={!canEdit} className="rounded-full border border-line px-3 py-1 text-xs text-blue-200 transition-colors hover:border-primary hover:bg-primary-soft disabled:opacity-50" onClick={() => void ask(q)}>{q}</button>)}</div>
            </Card>
          )}
          {showConversation && messages.map((m) => m.role === "user" ? (
            <div key={m.id} className="flex items-start justify-end gap-2">
              <p className="max-w-[80%] rounded-lg bg-primary/20 px-3 py-2 text-[13px]">{m.content}</p>
              <span className="mt-0.5 rounded-full bg-raised p-1.5 text-muted"><UserIcon size={13} /></span>
            </div>
          ) : (
            <div key={m.id} className="flex items-start gap-2">
              <span className="mt-0.5 rounded-full bg-raised p-1.5 text-accent"><Bot size={13} /></span>
              <div className="min-w-0 flex-1">{m.response ? <AnswerCard answer={m.response} onFollowUp={canEdit ? (q) => void ask(q) : undefined} /> : <p>{m.content}</p>}</div>
            </div>
          ))}
          {pendingQuestion && (
            <>
              <div className="flex items-start justify-end gap-2"><p className="max-w-[80%] rounded-lg bg-primary/20 px-3 py-2 text-[13px]">{pendingQuestion}</p><span className="mt-0.5 rounded-full bg-raised p-1.5 text-muted"><UserIcon size={13} /></span></div>
              <div className="flex items-start gap-2"><span className="mt-0.5 rounded-full bg-raised p-1.5 text-accent"><Bot size={13} /></span><div className="min-w-0 flex-1 space-y-2 rounded-lg border border-line bg-surface p-3.5"><p className="flex items-center gap-1.5 text-xs text-muted"><Database size={12} />Calculating from your data...</p><Skeleton className="h-4 w-3/4" /><Skeleton className="h-24" /></div></div>
            </>
          )}
          {error && <ErrorNote message={error} />}
          <div ref={end} />
        </div>

        <form onSubmit={submit} className="sticky bottom-2 flex items-end gap-2 rounded-lg border border-line bg-surface p-2 shadow-pop">
          <textarea aria-label="Your question" rows={1} maxLength={1000} disabled={!canEdit} className="max-h-32 min-h-8 flex-1 resize-none bg-transparent px-1.5 py-1.5 text-[13px] placeholder:text-faint focus:outline-none" placeholder={canEdit ? "Ask a question, such as: Which month had the highest revenue?" : "Your role is read-only, so you can't ask questions here."} value={question}
            onChange={(e) => setQuestion(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void ask(question); } }} />
          <Button type="submit" variant="primary" size="icon" aria-label="Send question" loading={sending} disabled={question.trim().length < 2 || !canEdit}><Send size={14} /></Button>
        </form>
      </div>
      <ConfirmDialog open={!!toDelete} danger title="Delete this conversation?" confirmLabel="Delete" body={<>“{toDelete?.title}” and its answers will be removed.</>} onClose={() => setToDelete(null)} onConfirm={() => void removeConversation()} />
    </div>
  );
}

export default function AnalystPage() {
  return <RequireDataset>{(id) => <AnalystContent key={id} datasetId={id} />}</RequireDataset>;
}
