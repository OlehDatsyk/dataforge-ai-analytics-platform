import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";
import { api, getWorkspaceId, remember, setUnauthorisedHandler, setWorkspaceId } from "./api";
import { useAsync, useInterval } from "./hooks";
import type { Dataset, User, WorkspaceRef } from "./types";

/* ---------- Toasts ---------- */
type ToastKind = "success" | "error" | "info" | "warning";
interface Toast { id: number; kind: ToastKind; message: string }
const ToastContext = createContext<(message: string, kind?: ToastKind) => void>(() => undefined);
export const useToast = () => useContext(ToastContext);
const TOAST_ICON = { success: CheckCircle2, error: XCircle, info: Info, warning: AlertTriangle };
const TOAST_COLOUR = { success: "text-good", error: "text-bad", info: "text-primary", warning: "text-warn" };

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((message: string, kind: ToastKind = "success") => {
    const id = Date.now() + Math.random();
    setToasts((all) => [...all.slice(-3), { id, kind, message }]);
    setTimeout(() => setToasts((all) => all.filter((t) => t.id !== id)), kind === "error" ? 7000 : 4000);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="fixed bottom-4 right-4 z-[60] flex w-[min(380px,calc(100vw-2rem))] flex-col gap-2" role="status" aria-live="polite">
        {toasts.map((toast) => {
          const Icon = TOAST_ICON[toast.kind];
          return (
            <div key={toast.id} className="flex animate-rise items-start gap-2.5 rounded-lg border border-line bg-raised px-3 py-2.5 shadow-pop">
              <Icon size={16} className={`mt-0.5 shrink-0 ${TOAST_COLOUR[toast.kind]}`} />
              <p className="flex-1 text-[13px]">{toast.message}</p>
              <button aria-label="Dismiss" className="text-faint hover:text-ink" onClick={() => setToasts((all) => all.filter((t) => t.id !== toast.id))}><X size={14} /></button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

/* ---------- Session and workspace ---------- */
interface AuthState {
  user: User | null;
  loading: boolean;
  workspace: WorkspaceRef | null;
  canEdit: boolean;
  canAdmin: boolean;
  setUser: (user: User | null) => void;
  refreshUser: () => Promise<void>;
  switchWorkspace: (id: string) => void;
  logout: () => Promise<void>;
  workspaceKey: number;
}
const AuthContext = createContext<AuthState>(null as unknown as AuthState);
export const useAuth = () => useContext(AuthContext);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUserState] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [workspaceKey, setWorkspaceKey] = useState(0);

  const setUser = useCallback((next: User | null) => {
    setUserState(next);
    if (next) {
      const stored = getWorkspaceId();
      if (!stored || !next.workspaces.some((w) => w.id === stored)) setWorkspaceId(next.workspaces[0]?.id ?? null);
    }
  }, []);

  const refreshUser = useCallback(async () => setUser(await api.get<User>("/auth/me")), [setUser]);

  useEffect(() => {
    setUnauthorisedHandler(() => setUserState(null));
    // The stored workspace may belong to another account, so it is left out of the first request.
    const stored = getWorkspaceId();
    setWorkspaceId(null);
    api.get<User>("/auth/me")
      .then((me) => {
        setWorkspaceId(stored);
        setUser(me);
      })
      .catch(() => setUserState(null))
      .finally(() => setLoading(false));
  }, [setUser]);

  const workspace = useMemo(() => user?.workspaces.find((w) => w.id === getWorkspaceId()) ?? user?.workspaces[0] ?? null, [user, workspaceKey]); // eslint-disable-line

  const value: AuthState = {
    user,
    loading,
    workspace,
    canEdit: !!workspace && workspace.role !== "viewer",
    canAdmin: !!workspace && (workspace.role === "owner" || workspace.role === "admin"),
    setUser,
    refreshUser,
    workspaceKey,
    switchWorkspace: (id) => {
      setWorkspaceId(id);
      setWorkspaceKey((k) => k + 1);
    },
    logout: async () => {
      await api.post("/auth/logout").catch(() => undefined);
      setWorkspaceId(null);
      setUserState(null);
    },
  };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/* ---------- Active dataset, kept in the URL so that pages can be linked ---------- */
interface DatasetState {
  datasets: Dataset[];
  loading: boolean;
  datasetId: string | null;
  dataset: Dataset | null;
  setDatasetId: (id: string) => void;
  reloadDatasets: () => void;
}
const DatasetContext = createContext<DatasetState>(null as unknown as DatasetState);
export const useDatasets = () => useContext(DatasetContext);
const ACTIVE_KEY = "dataforge.dataset";

export function DatasetProvider({ children }: { children: ReactNode }) {
  const { workspaceKey } = useAuth();
  const [params, setParams] = useSearchParams();
  const { data, loading, reload } = useAsync(() => api.get<Dataset[]>("/datasets"), [workspaceKey]);
  const datasets = data ?? [];
  const pending = datasets.some((d) => d.status === "queued" || d.status === "processing");
  useInterval(() => void reload(true), pending ? 1200 : null);

  const urlId = params.get("dataset");
  const ready = datasets.filter((d) => d.status === "ready");
  const stored = remember.get(ACTIVE_KEY);
  const datasetId = (urlId && datasets.some((d) => d.id === urlId) ? urlId : null) ?? (stored && ready.some((d) => d.id === stored) ? stored : null) ?? ready[0]?.id ?? null;

  useEffect(() => {
    if (datasetId) remember.set(ACTIVE_KEY, datasetId);
  }, [datasetId]);

  const value: DatasetState = {
    datasets,
    loading,
    datasetId,
    dataset: datasets.find((d) => d.id === datasetId) ?? null,
    reloadDatasets: () => void reload(true),
    setDatasetId: (id) => {
      remember.set(ACTIVE_KEY, id);
      const next = new URLSearchParams(params);
      next.set("dataset", id);
      setParams(next, { replace: true });
    },
  };
  return <DatasetContext.Provider value={value}>{children}</DatasetContext.Provider>;
}
