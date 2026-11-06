export type DataType = "integer" | "float" | "boolean" | "date" | "category" | "text";

export interface WorkspaceRef { id: string; name: string; role: "owner" | "admin" | "member" | "viewer" }
export interface User { id: string; email: string; full_name: string; created_at: string; workspaces: WorkspaceRef[] }

export interface Column { name: string; type: DataType; missing: number; unique: number }
export interface Version {
  id: string; version_number: number; label: string; row_count: number; column_count: number;
  size_bytes: number; parent_version_id: string | null; created_at: string; is_current: boolean;
}
export interface Dataset {
  id: string; name: string; description: string | null; original_filename: string | null; file_format: string;
  file_size: number; source_type: "upload" | "connection" | "derived" | "demo"; is_demo: boolean;
  status: "queued" | "processing" | "ready" | "failed"; stage: string | null; progress: number; error_message: string | null;
  ingest_notes: string[]; row_count: number; column_count: number; project_id: string | null; project_name: string | null;
  current_version_id: string | null; parent_dataset_id: string | null; created_at: string; updated_at: string; last_analysed_at: string | null;
  versions?: Version[]; columns?: Column[];
}
export interface Project { id: string; name: string; dataset_count: number }

export type FilterOp = "eq" | "ne" | "gt" | "gte" | "lt" | "lte" | "between" | "in" | "contains" | "not_contains" | "starts_with" | "ends_with" | "is_null" | "not_null";
export interface Filter { column: string; op: FilterOp; value?: string | number | boolean | null; values?: (string | number)[] | null }

export interface RowsResult { columns: string[]; rows: Record<string, unknown>[]; total: number; page: number; page_size: number; page_count: number }

export interface ColumnProfile {
  name: string; type: DataType; count: number; missing: number; missing_pct: number; unique: number;
  mean?: number; median?: number; min?: number; max?: number; std?: number | null; q1?: number; q3?: number; skewness?: number | null;
  zero_count?: number; negative_count?: number; histogram?: { start: number; end: number; count: number }[];
  top_values?: { value: unknown; count: number; share: number }[];
  earliest?: string; latest?: string; range_days?: number; frequency?: string | null;
  true_count?: number; false_count?: number; empty_count?: number; average_length?: number; min_length?: number; max_length?: number;
}
export interface QualityIssue {
  id: string; check: string; severity: "critical" | "warning" | "info"; title: string; detail: string; column: string | null; count: number;
  suggested_fix: Record<string, unknown> | null;
}
export interface ProfileResult {
  version: Version; columns: Column[];
  profile: { row_count: number; column_count: number; duplicate_rows: number; missing_cells: number; total_cells: number; missing_pct: number; columns: ColumnProfile[] };
  quality: { score: number; issue_count: number; issues: QualityIssue[] };
}

export type ChartType = "bar" | "line" | "area" | "pie" | "donut" | "scatter" | "histogram" | "box";
export interface ChartSpec {
  chart_type: ChartType; x?: string | null; y?: string | null; group?: string | null;
  aggregation?: "sum" | "avg" | "count" | "min" | "max" | "median"; filters?: Filter[];
  time_grain?: "auto" | "day" | "week" | "month" | "quarter" | "year"; sort?: "value_desc" | "value_asc" | "x";
  limit?: number; bins?: number; title?: string | null; x_label?: string | null; y_label?: string | null;
}
export interface ChartResult {
  chart_type: ChartType; title: string; rows: Record<string, any>[]; series: string[]; x_type?: string; x_label?: string; y_label?: string;
  notes?: string[]; filters?: string[]; rows_matched?: number; time_grain?: string | null; aggregation?: string;
}
export interface Visualisation { id: string; name: string; dataset_id: string; dataset_name: string | null; spec: ChartSpec; updated_at: string; created_at: string }

export interface AnalystResponse {
  status: "answered" | "unsupported"; mode: "live" | "demonstration"; provider: string | null; model: string | null; narrated_by: "ai" | "engine";
  direct_answer: string; key_findings: string[]; interpretation: string; follow_ups: string[]; limitations: string[]; assumptions: string[]; notices: string[];
  supporting_data: { columns: string[]; rows: Record<string, unknown>[]; total_rows: number };
  chart: ChartResult | null;
  provenance: { dataset: string; version: number; columns: string[]; filters: string[]; time_range: string | null; calculation: string; rows_used: number };
  grounding: { numbers_from_engine: boolean; ai_figures_rejected: string[] };
  data_shared_with_ai: { schema: boolean; category_labels: boolean; aggregated_result_rows: number; raw_rows: boolean } | null;
}
export interface AIMessage { id: string; role: "user" | "assistant"; content: string; response: AnalystResponse | null; created_at: string }
export interface Conversation { id: string; title: string; dataset_id: string; dataset_name?: string; updated_at?: string; messages?: AIMessage[] }
export interface AIStatus { mode: "live" | "demonstration"; provider: string | null; model: string | null; problem: string | null; shares_category_values: boolean; external_processing: boolean }

export interface AnomalyMethod { column: string; method: string; reason: string; flagged: number; listed: number | null; expected_low?: number; expected_high?: number }
export interface AnomalyRun {
  id: string; dataset_id: string; dataset_name: string | null; created_at: string; status: string;
  summary: {
    total: number; by_severity: { high: number; medium: number; low: number }; methods: AnomalyMethod[]; skipped: string[];
    series: Record<string, { column: string; kind: string; label: string }>; date_column: string | null; rows_checked: number; disclaimer: string;
  };
}
export interface AnomalyResult {
  id: string; run_id: string; dataset_id: string; row_id: number | null; period: string | null; column_name: string; kind: string; method: string; observed: string | null;
  observed_value: number | null; expected_low: number | null; expected_high: number | null; baseline: number | null; score: number; severity: "low" | "medium" | "high";
  explanation: string; status: "open" | "investigating" | "expected" | "resolved"; created_at: string;
}

export interface ReportTable { title: string; columns: string[]; rows: Record<string, unknown>[] }
export interface ReportSection { heading: string; text: string | null; findings: string[]; table: ReportTable | null; chart: ChartResult | null }
export interface ReportContent {
  title: string; report_type: string; report_type_label: string; workspace: string; dataset: string; version: number; is_demo: boolean;
  ai: { mode: string; provider: string | null; model: string | null } | null; generated_at: string; executive_summary: string[];
  overview: { rows: number; columns: number; missing_pct: number; duplicate_rows: number; quality_score: number };
  methodology: string[]; sections: ReportSection[]; recommendations: string[]; limitations: string[];
}
export interface ReportSummary { id: string; title: string; report_type: string; report_type_label: string; dataset_id: string; dataset_name: string | null; status: string; is_demo: boolean; created_at: string; content?: ReportContent }

export interface Connection {
  id: string; name: string; kind: "postgresql" | "rest_api"; config: Record<string, string | number>; has_secret: boolean;
  last_tested_at: string | null; last_status: string | null; last_error: string | null; created_at: string;
}
export interface Member { id: string; user_id: string; email: string; full_name: string; role: WorkspaceRef["role"]; joined_at: string }
export interface AuditEntry { id: string; action: string; entity_type: string | null; entity_id: string | null; detail: Record<string, unknown>; ip_address: string | null; user_email: string | null; created_at: string }
export interface NotificationItem { id: string; kind: "info" | "success" | "warning" | "error"; title: string; body: string | null; link: string | null; read: boolean; created_at: string }

export interface OverviewData {
  metrics: { total_datasets: number; records_analysed: number; total_analyses: number; active_reports: number; detected_anomalies: number; recent_activity: number; demo_datasets: number };
  activity: { range: string; unit: string; points: { period: string; count: number }[] };
  datasets: Pick<Dataset, "id" | "name" | "file_format" | "row_count" | "column_count" | "created_at" | "status" | "last_analysed_at" | "is_demo" | "source_type">[];
  analyses: { id: string; name: string; dataset_name: string | null; dataset_id: string | null; analysis_type: string; status: string; created_at: string; link: string | null }[];
}
