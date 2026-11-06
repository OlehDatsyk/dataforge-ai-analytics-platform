import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { completeFilters, FilterBuilder, operatorsFor } from "../components/FilterBuilder";
import { ChartView } from "../components/ChartView";
import { Badge, ConfirmDialog, EmptyState, Pagination, StatusBadge } from "../components/ui";
import { formatBytes, formatCell, formatInt, formatNumber, toCsv } from "../lib/format";
import { AnswerCard } from "../pages/Analyst";
import { Database } from "lucide-react";
import type { AnalystResponse, Column } from "../lib/types";

describe("format helpers", () => {
  it("formats numbers and missing values", () => {
    expect(formatInt(1234567)).toBe("1,234,567");
    expect(formatInt(null)).toBe("-");
    expect(formatNumber(1234.5678)).toBe("1,234.57");
    expect(formatNumber(0.12345)).toBe("0.1235");
    expect(formatBytes(2048)).toBe("2.0 KB");
  });

  it("formats table cells", () => {
    expect(formatCell(null)).toBe("");
    expect(formatCell(true)).toBe("true");
    expect(formatCell("2024-03-01T00:00:00")).toBe("2024-03-01");
    expect(formatCell("2024-03-01T10:30:00")).toBe("2024-03-01 10:30:00");
  });

  it("neutralises spreadsheet formulas in client-side CSV", () => {
    const csv = toCsv(["a", "b"], [{ a: "=SUM(A1)", b: -5 }, { a: "-12.5", b: 'quote"d' }, { a: "+cmd", b: "@x" }]);
    const lines = csv.split("\r\n");
    expect(lines[1]).toBe("'=SUM(A1),-5");
    expect(lines[2]).toBe('-12.5,"quote""d"');
    expect(lines[3]).toBe("'+cmd,'@x");
  });
});

describe("filters", () => {
  const columns: Column[] = [{ name: "revenue", type: "float", missing: 0, unique: 9 }, { name: "region", type: "category", missing: 0, unique: 3 }];

  it("offers operators suited to each type", () => {
    expect(operatorsFor("float")).toContain("gt");
    expect(operatorsFor("float")).not.toContain("contains");
    expect(operatorsFor("text")).toContain("contains");
    expect(operatorsFor("text")).not.toContain("gt");
    expect(operatorsFor("date")).toContain("between");
  });

  it("only sends filters that are complete", () => {
    expect(completeFilters([{ column: "a", op: "gt", value: "" }])).toHaveLength(0);
    expect(completeFilters([{ column: "a", op: "gt", value: "5" }])).toHaveLength(1);
    expect(completeFilters([{ column: "a", op: "is_null" }])).toHaveLength(1);
    expect(completeFilters([{ column: "a", op: "between", values: ["1"] }])).toHaveLength(0);
    expect(completeFilters([{ column: "a", op: "between", values: ["1", "2"] }])).toHaveLength(1);
  });

  it("adds a filter and resets the operator when the column type changes", () => {
    const onChange = vi.fn();
    const { rerender } = render(<FilterBuilder columns={columns} filters={[]} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Add filter" }));
    expect(onChange).toHaveBeenCalledWith([{ column: "revenue", op: "eq", value: "" }]);
    rerender(<FilterBuilder columns={columns} filters={[{ column: "revenue", op: "gt", value: "5" }]} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("Filter column"), { target: { value: "region" } });
    expect(onChange).toHaveBeenLastCalledWith([{ column: "region", op: "contains", value: "", values: null }]);
  });
});

describe("UI components", () => {
  it("disables pagination at the boundaries", () => {
    const onPage = vi.fn();
    render(<Pagination page={1} pageCount={3} total={120} onPage={onPage} />);
    expect(screen.getByLabelText("Previous page")).toBeDisabled();
    fireEvent.click(screen.getByLabelText("Next page"));
    expect(onPage).toHaveBeenCalledWith(2);
    expect(screen.getByText("120 rows")).toBeInTheDocument();
  });

  it("requires confirmation and can be cancelled", () => {
    const onConfirm = vi.fn();
    const onClose = vi.fn();
    render(<ConfirmDialog open danger title="Delete?" body="Sure?" confirmLabel="Delete it" onConfirm={onConfirm} onClose={onClose} />);
    expect(onConfirm).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Cancel"));
    expect(onClose).toHaveBeenCalled();
    fireEvent.click(screen.getByText("Delete it"));
    expect(onConfirm).toHaveBeenCalled();
  });

  it("renders status and empty states", () => {
    render(<><StatusBadge status="ready" /><Badge>Tag</Badge><EmptyState icon={Database} title="Nothing here">Help text</EmptyState></>);
    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
  });

  it("shows a helpful message when a chart has no data", () => {
    render(<ChartView chart={{ chart_type: "bar", title: "T", rows: [], series: ["S"] }} />);
    expect(screen.getByText("No values match the current filters.")).toBeInTheDocument();
  });
});

const ANSWER: AnalystResponse = {
  status: "answered", mode: "demonstration", provider: null, model: null, narrated_by: "engine",
  direct_answer: "North has the highest total revenue, at 500.00.", key_findings: ["North: 500.00"], interpretation: "This compares 2 groups.", follow_ups: ["Show the trend"], limitations: ["Totals reflect volume."], assumptions: ["'revenue' was used."], notices: [],
  supporting_data: { columns: ["region", "total revenue"], rows: [{ region: "North", "total revenue": 500 }], total_rows: 1 }, chart: null,
  provenance: { dataset: "Sales", version: 1, columns: ["region", "revenue"], filters: ["year = 2024"], time_range: null, calculation: "SUM of revenue grouped by region", rows_used: 8 },
  grounding: { numbers_from_engine: true, ai_figures_rejected: [] }, data_shared_with_ai: null,
};

describe("analyst answers", () => {
  it("shows every required section and labels demonstration mode", () => {
    const onFollowUp = vi.fn();
    render(<MemoryRouter><AnswerCard answer={ANSWER} onFollowUp={onFollowUp} /></MemoryRouter>);
    expect(screen.getByText(/Demonstration mode: no AI model/)).toBeInTheDocument();
    expect(screen.getByText(ANSWER.direct_answer)).toBeInTheDocument();
    expect(screen.getByText("Key findings")).toBeInTheDocument();
    expect(screen.getByText("Supporting data")).toBeInTheDocument();
    expect(screen.getByText("Interpretation")).toBeInTheDocument();
    expect(screen.getByText("Limitations")).toBeInTheDocument();
    expect(screen.getByText("SUM of revenue grouped by region")).toBeInTheDocument();
    expect(screen.getByText("year = 2024")).toBeInTheDocument();
    expect(screen.getByText(/Nothing. This answer was produced locally/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Show the trend"));
    expect(onFollowUp).toHaveBeenCalledWith("Show the trend");
  });

  it("labels unanswered questions and live AI differently", () => {
    render(<MemoryRouter><AnswerCard answer={{ ...ANSWER, status: "unsupported", mode: "live", provider: "anthropic", model: "m", narrated_by: "ai", data_shared_with_ai: { schema: true, category_labels: false, aggregated_result_rows: 1, raw_rows: false } }} /></MemoryRouter>);
    expect(screen.getByText("Could not be answered")).toBeInTheDocument();
    expect(screen.getByText(/Explained by anthropic/)).toBeInTheDocument();
    expect(screen.getByText(/No raw records/)).toBeInTheDocument();
  });
});
