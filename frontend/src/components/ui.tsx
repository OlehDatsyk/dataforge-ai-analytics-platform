import { useEffect, useRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { AlertCircle, ChevronLeft, ChevronRight, Info, Loader2, X, type LucideIcon } from "lucide-react";

const cx = (...parts: (string | false | null | undefined)[]) => parts.filter(Boolean).join(" ");
export { cx };

type Variant = "primary" | "secondary" | "ghost" | "danger";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-primary text-white hover:bg-primary-hover",
  secondary: "border border-line bg-raised text-ink hover:border-faint",
  ghost: "text-muted hover:bg-raised hover:text-ink",
  danger: "bg-bad/90 text-white hover:bg-bad",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant; icon?: LucideIcon; loading?: boolean; size?: "sm" | "md" | "icon";
}
export function Button({ variant = "secondary", icon: Icon, loading, size = "md", className, children, disabled, type = "button", ...rest }: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      className={cx(
        "inline-flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-md font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        size === "md" && "h-8 px-3 text-[13px]",
        size === "sm" && "h-7 px-2 text-xs",
        size === "icon" && "h-8 w-8",
        VARIANTS[variant],
        className,
      )}
      {...rest}
    >
      {loading ? <Loader2 size={14} className="animate-spin" /> : Icon ? <Icon size={14} /> : null}
      {children}
    </button>
  );
}

export function Card({ title, subtitle, actions, children, className, bodyClass, id }: { title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClass?: string; id?: string }) {
  return (
    <section id={id} className={cx("rounded-lg border border-line bg-surface shadow-card", className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-2.5">
          <div className="min-w-0">
            {title && <h2 className="text-[13px] font-semibold">{title}</h2>}
            {subtitle && <p className="text-xs text-muted">{subtitle}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={bodyClass ?? "p-4"}>{children}</div>
    </section>
  );
}

type Tone = "neutral" | "blue" | "cyan" | "violet" | "good" | "warn" | "bad";
const TONES: Record<Tone, string> = {
  neutral: "border-line bg-raised text-muted",
  blue: "border-primary/30 bg-primary/10 text-blue-300",
  cyan: "border-accent/30 bg-accent/10 text-cyan-300",
  violet: "border-violet/30 bg-violet/10 text-violet-300",
  good: "border-good/30 bg-good/10 text-green-300",
  warn: "border-warn/30 bg-warn/10 text-amber-300",
  bad: "border-bad/30 bg-bad/10 text-red-300",
};
export function Badge({ tone = "neutral", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return <span title={title} className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded border px-1.5 py-px text-2xs font-medium", TONES[tone])}>{children}</span>;
}

const STATUS_TONE: Record<string, Tone> = { ready: "good", completed: "good", failed: "bad", queued: "neutral", processing: "blue", unsupported: "warn", open: "warn", investigating: "blue", expected: "neutral", resolved: "good", high: "bad", medium: "warn", low: "neutral", critical: "bad", warning: "warn", info: "blue", ok: "good" };
export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={STATUS_TONE[status] ?? "neutral"}>{status.charAt(0).toUpperCase() + status.slice(1)}</Badge>;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("animate-shimmer rounded bg-raised", className)} />;
}
export function TableSkeleton({ rows = 6 }: { rows?: number }) {
  return <div className="space-y-2 p-4" aria-label="Loading">{Array.from({ length: rows }, (_, i) => <Skeleton key={i} className="h-7 w-full" />)}</div>;
}

export function EmptyState({ icon: Icon, title, children, actions }: { icon: LucideIcon; title: string; children?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-6 py-10 text-center">
      <div className="mb-3 rounded-lg border border-line bg-raised p-2.5 text-muted"><Icon size={20} /></div>
      <h3 className="text-sm font-semibold">{title}</h3>
      {children && <p className="mt-1 max-w-md text-[13px] text-muted">{children}</p>}
      {actions && <div className="mt-4 flex flex-wrap justify-center gap-2">{actions}</div>}
    </div>
  );
}

export function ErrorNote({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-bad/30 bg-bad/10 px-3 py-2 text-[13px] text-red-200" role="alert">
      <AlertCircle size={15} className="mt-0.5 shrink-0" />
      <span className="flex-1">{message}</span>
      {onRetry && <button className="font-medium underline" onClick={onRetry}>Try again</button>}
    </div>
  );
}

export function Notice({ tone = "blue", icon: Icon = Info, children }: { tone?: "blue" | "warn" | "violet"; icon?: LucideIcon; children: ReactNode }) {
  const styles = { blue: "border-primary/25 bg-primary/10 text-blue-100", warn: "border-warn/25 bg-warn/10 text-amber-100", violet: "border-violet/30 bg-violet/10 text-violet-100" };
  return <div className={cx("flex items-start gap-2 rounded-md border px-3 py-2 text-[13px]", styles[tone])}><Icon size={15} className="mt-0.5 shrink-0" /><div className="min-w-0 flex-1">{children}</div></div>;
}

export function Tooltip({ text, children }: { text: string; children: ReactNode }) {
  return (
    <span className="group relative inline-flex">
      {children}
      <span role="tooltip" className="pointer-events-none absolute bottom-full left-1/2 z-40 mb-1.5 w-max max-w-[260px] -translate-x-1/2 rounded border border-line bg-raised px-2 py-1 text-xs text-ink opacity-0 shadow-pop transition-opacity delay-200 group-focus-within:opacity-100 group-hover:opacity-100">{text}</span>
    </span>
  );
}

export function Dialog({ open, title, subtitle, onClose, children, footer, width = "max-w-lg" }: { open: boolean; title: string; subtitle?: string; onClose: () => void; children: ReactNode; footer?: ReactNode; width?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); previous?.focus?.(); };
  }, [open]); // eslint-disable-line
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title} className={cx("flex max-h-[90vh] w-full animate-rise flex-col rounded-lg border border-line bg-surface shadow-pop focus:outline-none", width)}>
        <header className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
          <div><h2 className="text-sm font-semibold">{title}</h2>{subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}</div>
          <button aria-label="Close" onClick={onClose} className="text-faint hover:text-ink"><X size={16} /></button>
        </header>
        <div className="min-h-0 flex-1 overflow-auto p-4">{children}</div>
        {footer && <footer className="flex flex-wrap justify-end gap-2 border-t border-line px-4 py-3">{footer}</footer>}
      </div>
    </div>
  );
}

export function ConfirmDialog({ open, title, body, confirmLabel, danger, loading, onConfirm, onClose }: { open: boolean; title: string; body: ReactNode; confirmLabel: string; danger?: boolean; loading?: boolean; onConfirm: () => void; onClose: () => void }) {
  return (
    <Dialog open={open} title={title} onClose={onClose} width="max-w-md" footer={<><Button onClick={onClose}>Cancel</Button><Button variant={danger ? "danger" : "primary"} loading={loading} onClick={onConfirm}>{confirmLabel}</Button></>}>
      <div className="text-[13px] text-muted">{body}</div>
    </Dialog>
  );
}

export function Field({ label, hint, children, error }: { label: string; hint?: string; children: ReactNode; error?: string | null }) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      {children}
      {hint && !error && <span className="mt-1 block text-xs text-faint">{hint}</span>}
      {error && <span className="mt-1 block text-xs text-red-300">{error}</span>}
    </label>
  );
}

export function Select({ className, children, ...rest }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={cx("field pr-6", className)} {...rest}>{children}</select>;
}

export function Pagination({ page, pageCount, total, onPage, label = "rows" }: { page: number; pageCount: number; total: number; onPage: (page: number) => void; label?: string }) {
  return (
    <div className="flex items-center justify-between gap-3 border-t border-line px-3 py-2 text-xs text-muted">
      <span className="num">{total.toLocaleString("en-GB")} {label}</span>
      <div className="flex items-center gap-1.5">
        <Button size="icon" variant="ghost" aria-label="Previous page" disabled={page <= 1} onClick={() => onPage(page - 1)} className="!h-7 !w-7"><ChevronLeft size={14} /></Button>
        <span className="num">Page {page.toLocaleString("en-GB")} of {Math.max(pageCount, 1).toLocaleString("en-GB")}</span>
        <Button size="icon" variant="ghost" aria-label="Next page" disabled={page >= pageCount} onClick={() => onPage(page + 1)} className="!h-7 !w-7"><ChevronRight size={14} /></Button>
      </div>
    </div>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: string; icon?: LucideIcon }[]; value: T; onChange: (id: T) => void }) {
  return (
    <div role="tablist" className="flex gap-1 overflow-x-auto border-b border-line">
      {tabs.map(({ id, label, icon: Icon }) => (
        <button key={id} role="tab" aria-selected={value === id} onClick={() => onChange(id)} className={cx("-mb-px flex items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2 text-[13px] font-medium transition-colors", value === id ? "border-primary text-ink" : "border-transparent text-muted hover:text-ink")}>
          {Icon && <Icon size={14} />}{label}
        </button>
      ))}
    </div>
  );
}

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "bad" | "warn" | "good" }) {
  const colour = tone === "bad" ? "text-red-300" : tone === "warn" ? "text-amber-300" : tone === "good" ? "text-green-300" : "text-ink";
  return (
    <div className="rounded-lg border border-line bg-surface px-3.5 py-3 shadow-card">
      <p className="text-xs text-muted">{label}</p>
      <p className={cx("num mt-1 text-xl font-semibold tracking-tight", colour)}>{value}</p>
      {sub && <p className="mt-0.5 truncate text-xs text-faint">{sub}</p>}
    </div>
  );
}

export function SyntheticBadge() {
  return <Badge tone="violet" title="Generated demonstration data, not real business information">Synthetic</Badge>;
}
