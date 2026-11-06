import { useMemo, useRef, useState } from "react";
import { Area, AreaChart, Bar, BarChart, Brush, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Scatter, ScatterChart, Tooltip as ChartTooltip, XAxis, YAxis, ZAxis } from "recharts";
import { Download, FileDown } from "lucide-react";
import { saveBlob } from "../lib/api";
import { formatCompact, formatNumber, toCsv } from "../lib/format";
import type { ChartResult } from "../lib/types";
import { Button } from "./ui";

/** Validated with the palette checker on the #111B2B surface. Order matters for colour-blind separation. */
export const SERIES_COLOURS = ["#3B82F6", "#D97706", "#0891B2", "#DB2777", "#8B5CF6", "#059669"];
const GRID = "#263449";
const AXIS = "#94A3B8";

export const tooltipStyle = {
  contentStyle: { background: "#162235", border: "1px solid #263449", borderRadius: 6, fontSize: 12, color: "#F1F5F9", boxShadow: "0 8px 24px rgba(0,0,0,0.45)" },
  labelStyle: { color: "#94A3B8", marginBottom: 2 },
  itemStyle: { color: "#F1F5F9", padding: 0 },
};

const colourFor = (series: string[], name: string) => SERIES_COLOURS[Math.max(series.indexOf(name), 0) % SERIES_COLOURS.length];

function axisDate(value: unknown): string {
  const text = String(value ?? "");
  if (/^\d{4}-\d{2}-\d{2}T/.test(text)) {
    const date = new Date(text);
    return date.toLocaleDateString("en-GB", { day: date.getDate() === 1 ? undefined : "2-digit", month: "short", year: "2-digit" });
  }
  return text.length > 16 ? `${text.slice(0, 15)}...` : text;
}

function tooltipLabel(value: unknown, grain?: string | null): string {
  const text = String(value ?? "");
  if (/^\d{4}-\d{2}-\d{2}T/.test(text)) {
    const date = new Date(text);
    if (grain === "month") return date.toLocaleDateString("en-GB", { month: "long", year: "numeric" });
    if (grain === "year") return String(date.getFullYear());
    return date.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
  }
  return text;
}

function BoxPlot({ rows, yLabel }: { rows: Record<string, any>[]; yLabel?: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const width = 820, height = 320, left = 62, right = 12, top = 14, bottom = 42;
  const low = Math.min(...rows.map((r) => r.whisker_low ?? r.min));
  const high = Math.max(...rows.map((r) => r.whisker_high ?? r.max));
  const pad = (high - low || 1) * 0.06;
  const y = (v: number) => top + (1 - (v - (low - pad)) / (high - low + 2 * pad)) * (height - top - bottom);
  const band = (width - left - right) / Math.max(rows.length, 1);
  const ticks = Array.from({ length: 5 }, (_, i) => low - pad + ((high - low + 2 * pad) * i) / 4);
  const active = hover !== null ? rows[hover] : null;
  return (
    <div className="relative">
      <svg viewBox={`0 0 ${width} ${height}`} className="h-auto w-full" role="img" aria-label={`Box plot of ${yLabel ?? "values"}`}>
        <rect width={width} height={height} fill="transparent" />
        {ticks.map((t) => (
          <g key={t}>
            <line x1={left} x2={width - right} y1={y(t)} y2={y(t)} stroke={GRID} strokeDasharray="3 3" />
            <text x={left - 8} y={y(t) + 4} textAnchor="end" fontSize="11" fill={AXIS}>{formatCompact(t)}</text>
          </g>
        ))}
        {rows.map((row, i) => {
          const cx = left + band * (i + 0.5);
          const w = Math.min(band * 0.5, 56);
          return (
            <g key={row.x} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={left + band * i} y={top} width={band} height={height - top - bottom} fill={hover === i ? "rgba(148,163,184,0.06)" : "transparent"} />
              <line x1={cx} x2={cx} y1={y(row.whisker_high ?? row.max)} y2={y(row.whisker_low ?? row.min)} stroke={AXIS} strokeWidth="1.5" />
              <line x1={cx - w / 4} x2={cx + w / 4} y1={y(row.whisker_high ?? row.max)} y2={y(row.whisker_high ?? row.max)} stroke={AXIS} strokeWidth="1.5" />
              <line x1={cx - w / 4} x2={cx + w / 4} y1={y(row.whisker_low ?? row.min)} y2={y(row.whisker_low ?? row.min)} stroke={AXIS} strokeWidth="1.5" />
              <rect x={cx - w / 2} y={y(row.q3)} width={w} height={Math.max(y(row.q1) - y(row.q3), 1)} rx="3" fill="rgba(59,130,246,0.32)" stroke="#3B82F6" strokeWidth="1.5" />
              <line x1={cx - w / 2} x2={cx + w / 2} y1={y(row.median)} y2={y(row.median)} stroke="#F1F5F9" strokeWidth="2" />
              <text x={cx} y={height - bottom + 18} textAnchor="middle" fontSize="11" fill={AXIS}>{String(row.x).slice(0, 16)}</text>
            </g>
          );
        })}
      </svg>
      {active && (
        <div className="pointer-events-none absolute right-2 top-2 rounded-md border border-line bg-raised px-2.5 py-2 text-xs shadow-pop">
          <p className="mb-1 font-medium">{active.x}</p>
          {[["Maximum", active.max], ["Upper quartile", active.q3], ["Median", active.median], ["Lower quartile", active.q1], ["Minimum", active.min]].map(([k, v]) => <p key={k as string} className="num flex justify-between gap-4 text-muted"><span>{k}</span><span className="text-ink">{formatNumber(v)}</span></p>)}
          <p className="num mt-1 flex justify-between gap-4 text-muted"><span>Records</span><span className="text-ink">{formatNumber(active.count)}</span></p>
          <p className="num flex justify-between gap-4 text-muted"><span>Beyond whiskers</span><span className="text-ink">{formatNumber(active.outliers)}</span></p>
        </div>
      )}
    </div>
  );
}

export function ChartView({ chart, height = 320, showExport = false }: { chart: ChartResult; height?: number; showExport?: boolean }) {
  const holder = useRef<HTMLDivElement>(null);
  const { rows, series, chart_type: type } = chart;
  const isDate = chart.x_type === "date";
  const showLegend = series.length >= 2 && type !== "scatter" ? true : type === "scatter" && series.length >= 2;

  const pieData = useMemo(() => (type === "pie" || type === "donut") ? rows.map((r) => ({ name: String(r.x), value: r[series[0]] ?? 0 })) : [], [rows, series, type]);
  const pieTotal = pieData.reduce((sum, item) => sum + (item.value as number), 0);

  const exportPng = () => {
    const svg = holder.current?.querySelector("svg.recharts-surface, svg[role='img']") as SVGSVGElement | null;
    if (!svg) return;
    const box = svg.getBoundingClientRect();
    const clone = svg.cloneNode(true) as SVGSVGElement;
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    clone.setAttribute("width", String(box.width));
    clone.setAttribute("height", String(box.height));
    clone.querySelectorAll("text").forEach((node) => { if (!node.getAttribute("fill")) node.setAttribute("fill", AXIS); node.setAttribute("font-size", node.getAttribute("font-size") ?? "11"); node.setAttribute("font-family", "Segoe UI, sans-serif"); });
    const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(clone)], { type: "image/svg+xml;charset=utf-8" }));
    const image = new Image();
    image.onload = () => {
      const scale = 2, titleSpace = 36;
      const canvas = document.createElement("canvas");
      canvas.width = box.width * scale;
      canvas.height = (box.height + titleSpace) * scale;
      const ctx = canvas.getContext("2d")!;
      ctx.scale(scale, scale);
      ctx.fillStyle = "#111B2B";
      ctx.fillRect(0, 0, box.width, box.height + titleSpace);
      ctx.fillStyle = "#F1F5F9";
      ctx.font = "600 14px Segoe UI, sans-serif";
      ctx.fillText(chart.title ?? "", 12, 22);
      ctx.drawImage(image, 0, titleSpace, box.width, box.height);
      URL.revokeObjectURL(url);
      canvas.toBlob((blob) => { if (blob) saveBlob(blob, `${(chart.title || "chart").replace(/[^\w-]+/g, "_").slice(0, 60)}.png`); });
    };
    image.src = url;
  };

  const exportCsv = () => {
    const columns = rows.length ? Object.keys(rows[0]) : [];
    saveBlob(new Blob(["﻿" + toCsv(columns, rows)], { type: "text/csv" }), `${(chart.title || "chart").replace(/[^\w-]+/g, "_").slice(0, 60)}.csv`);
  };

  const axisProps = { stroke: GRID, tickLine: false, tick: { fill: AXIS, fontSize: 11 } };
  const yAxis = <YAxis {...axisProps} width={56} tickFormatter={formatCompact} axisLine={false} />;
  const grid = <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />;
  const legend = showLegend ? <Legend iconType="circle" iconSize={8} itemSorter={null} wrapperStyle={{ fontSize: 12, paddingTop: 6 }} /> : null;
  const tip = <ChartTooltip {...tooltipStyle} formatter={(v) => formatNumber(v as number)} labelFormatter={(l) => tooltipLabel(l, chart.time_grain)} cursor={{ fill: "rgba(148,163,184,0.08)" }} />;
  const brush = (threshold: number) => rows.length > threshold ? <Brush dataKey="x" height={20} stroke="#475569" fill="#0B1220" travellerWidth={8} tickFormatter={isDate ? axisDate : undefined} /> : null;
  const xAxis = <XAxis {...axisProps} dataKey="x" tickFormatter={axisDate} minTickGap={24} interval="preserveStartEnd" />;

  let body: React.ReactElement;
  if (!rows.length) {
    body = <div className="flex h-full items-center justify-center text-[13px] text-muted">No values match the current filters.</div>;
  } else if (type === "box") {
    return (
      <div ref={holder}>
        {showExport && <ExportBar onPng={exportPng} onCsv={exportCsv} />}
        <BoxPlot rows={rows} yLabel={chart.y_label} />
      </div>
    );
  } else if (type === "bar" || type === "histogram") {
    body = (
      <BarChart data={rows} barCategoryGap={type === "histogram" ? 1 : "22%"} barGap={2}>
        {grid}{xAxis}{yAxis}{tip}{legend}
        {series.map((name) => <Bar key={name} dataKey={name} fill={colourFor(series, name)} radius={type === "histogram" ? [2, 2, 0, 0] : [4, 4, 0, 0]} maxBarSize={72} isAnimationActive={false} />)}
        {brush(40)}
      </BarChart>
    );
  } else if (type === "line") {
    body = (
      <LineChart data={rows}>
        {grid}{xAxis}{yAxis}{tip}{legend}
        {series.map((name) => <Line key={name} dataKey={name} stroke={colourFor(series, name)} strokeWidth={2} dot={rows.length <= 2 ? { r: 4 } : false} activeDot={{ r: 4, stroke: "#111B2B", strokeWidth: 2 }} connectNulls isAnimationActive={false} />)}
        {brush(36)}
      </LineChart>
    );
  } else if (type === "area") {
    body = (
      <AreaChart data={rows}>
        {grid}{xAxis}{yAxis}{tip}{legend}
        {series.map((name) => <Area key={name} dataKey={name} stroke={colourFor(series, name)} strokeWidth={2} fill={colourFor(series, name)} fillOpacity={0.18} connectNulls isAnimationActive={false} />)}
        {brush(36)}
      </AreaChart>
    );
  } else if (type === "pie" || type === "donut") {
    body = (
      <PieChart>
        <Pie data={pieData} dataKey="value" nameKey="name" innerRadius={type === "donut" ? "58%" : 0} outerRadius="82%" paddingAngle={1} stroke="#111B2B" strokeWidth={2} isAnimationActive={false}
          label={({ percent }) => (percent ?? 0) >= 0.05 ? `${((percent ?? 0) * 100).toFixed(0)}%` : ""} labelLine={false}>
          {pieData.map((item, i) => <Cell key={item.name} fill={item.name === "Other" ? "#64748B" : SERIES_COLOURS[i % SERIES_COLOURS.length]} />)}
        </Pie>
        <ChartTooltip {...tooltipStyle} formatter={(v, name) => [`${formatNumber(v as number)} (${pieTotal ? (((v as number) / pieTotal) * 100).toFixed(1) : 0}%)`, name as string]} />
        <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12 }} />
      </PieChart>
    );
  } else {
    const groups = series.length > 1 ? series.map((name) => ({ name, data: rows.filter((r) => r.group === name) })) : [{ name: series[0], data: rows }];
    body = (
      <ScatterChart>
        <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
        <XAxis {...axisProps} type="number" dataKey="x" name={chart.x_label} tickFormatter={formatCompact} domain={["auto", "auto"]} />
        <YAxis {...axisProps} type="number" dataKey="y" name={chart.y_label} tickFormatter={formatCompact} width={56} domain={["auto", "auto"]} axisLine={false} />
        <ZAxis range={[28, 28]} />
        <ChartTooltip {...tooltipStyle} formatter={(v) => formatNumber(v as number)} cursor={{ strokeDasharray: "3 3", stroke: "#475569" }} />
        {legend}
        {groups.map((group, i) => <Scatter key={group.name} name={group.name} data={group.data} fill={SERIES_COLOURS[i % SERIES_COLOURS.length]} fillOpacity={0.65} isAnimationActive={false} />)}
      </ScatterChart>
    );
  }

  return (
    <div ref={holder}>
      {showExport && <ExportBar onPng={exportPng} onCsv={exportCsv} />}
      <div style={{ height }}>
        {rows.length ? <ResponsiveContainer width="100%" height="100%">{body}</ResponsiveContainer> : body}
      </div>
      {chart.notes && chart.notes.length > 0 && <p className="mt-2 text-xs text-faint">{chart.notes.join(" ")}</p>}
    </div>
  );
}

function ExportBar({ onPng, onCsv }: { onPng: () => void; onCsv: () => void }) {
  return (
    <div className="mb-2 flex justify-end gap-1.5">
      <Button size="sm" variant="ghost" icon={Download} onClick={onPng}>PNG</Button>
      <Button size="sm" variant="ghost" icon={FileDown} onClick={onCsv}>CSV</Button>
    </div>
  );
}
