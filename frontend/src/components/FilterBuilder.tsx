import { Plus, X } from "lucide-react";
import type { Column, Filter, FilterOp } from "../lib/types";
import { Button, Select } from "./ui";

const LABELS: Record<FilterOp, string> = {
  eq: "equals", ne: "does not equal", gt: "greater than", gte: "at least", lt: "less than", lte: "at most", between: "between", in: "is one of",
  contains: "contains", not_contains: "does not contain", starts_with: "starts with", ends_with: "ends with", is_null: "is missing", not_null: "is not missing",
};

export function operatorsFor(type: Column["type"]): FilterOp[] {
  if (type === "integer" || type === "float" || type === "date") return ["eq", "ne", "gt", "gte", "lt", "lte", "between", "is_null", "not_null"];
  if (type === "boolean") return ["eq", "ne", "is_null", "not_null"];
  return ["contains", "not_contains", "eq", "ne", "starts_with", "ends_with", "in", "is_null", "not_null"];
}

/** Numbers are sent as text; the server validates them against the column's type. */
export const completeFilters = (filters: Filter[]) =>
  filters.filter((f) => {
    if (f.op === "is_null" || f.op === "not_null") return true;
    if (f.op === "between") return (f.values ?? []).length === 2 && (f.values ?? []).every((v) => v !== "");
    if (f.op === "in") return (f.values ?? []).length > 0;
    return f.value !== undefined && f.value !== null && f.value !== "";
  });

export function FilterBuilder({ columns, filters, onChange }: { columns: Column[]; filters: Filter[]; onChange: (filters: Filter[]) => void }) {
  const update = (index: number, patch: Partial<Filter>) => onChange(filters.map((f, i) => (i === index ? { ...f, ...patch } : f)));
  const typeOf = (name: string) => columns.find((c) => c.name === name)?.type ?? "text";

  return (
    <div className="space-y-2">
      {filters.map((filter, index) => {
        const type = typeOf(filter.column);
        const inputType = type === "date" ? "date" : type === "integer" || type === "float" ? "number" : "text";
        return (
          <div key={index} className="flex flex-wrap items-center gap-1.5">
            <Select aria-label="Filter column" className="!w-40" value={filter.column} onChange={(e) => { const next = typeOf(e.target.value); onChange(filters.map((f, i) => i === index ? { column: e.target.value, op: operatorsFor(next)[0], value: "", values: null } : f)); }}>
              {columns.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
            </Select>
            <Select aria-label="Filter operator" className="!w-36" value={filter.op} onChange={(e) => update(index, { op: e.target.value as FilterOp, value: "", values: null })}>
              {operatorsFor(type).map((op) => <option key={op} value={op}>{LABELS[op]}</option>)}
            </Select>
            {filter.op === "between" ? (
              <>
                <input aria-label="From" className="field !w-32" type={inputType} value={String(filter.values?.[0] ?? "")} onChange={(e) => update(index, { values: [e.target.value, String(filter.values?.[1] ?? "")] })} />
                <span className="text-xs text-muted">and</span>
                <input aria-label="To" className="field !w-32" type={inputType} value={String(filter.values?.[1] ?? "")} onChange={(e) => update(index, { values: [String(filter.values?.[0] ?? ""), e.target.value] })} />
              </>
            ) : filter.op === "in" ? (
              <input aria-label="Values" className="field !w-56" placeholder="Comma-separated values" value={(filter.values ?? []).join(",")} onChange={(e) => update(index, { values: e.target.value.split(",").map((v) => v.trim()).filter(Boolean) })} />
            ) : filter.op === "is_null" || filter.op === "not_null" ? null : type === "boolean" ? (
              <Select aria-label="Value" className="!w-24" value={String(filter.value ?? "")} onChange={(e) => update(index, { value: e.target.value })}>
                <option value="">Select</option><option value="true">true</option><option value="false">false</option>
              </Select>
            ) : (
              <input aria-label="Value" className="field !w-44" type={inputType} step="any" placeholder="Value" value={String(filter.value ?? "")} onChange={(e) => update(index, { value: e.target.value })} />
            )}
            <button aria-label="Remove filter" className="rounded p-1 text-faint hover:bg-raised hover:text-ink" onClick={() => onChange(filters.filter((_, i) => i !== index))}><X size={14} /></button>
          </div>
        );
      })}
      <Button size="sm" variant="ghost" icon={Plus} disabled={!columns.length} onClick={() => onChange([...filters, { column: columns[0].name, op: operatorsFor(columns[0].type)[0], value: "" }])}>Add filter</Button>
    </div>
  );
}
