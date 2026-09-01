/**
 * Budgeting & Analytics (M8) — annual budget lifecycle
 * (create -> approve -> lock -> revise with audit), budget-vs-actual
 * variance, monthly trend, and the productivity batch.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { Badge, Button, Card } from "@/components/ui";
import { cn } from "@/lib/utils";
import {
  BarChart3,
  Loader2,
  Lock,
  PieChart,
  Plus,
  TrendingUp,
} from "lucide-react";

/* --------------------------------- types --------------------------------- */

interface Budget {
  id: string;
  budget_name: string;
  fiscal_year_id: string;
  year_label: string;
  status: "DRAFT" | "APPROVED" | "LOCKED";
  created_at: string;
}

interface BudgetLine {
  id: string;
  account_id: string;
  account_code: string;
  account_name: string;
  department_code: string | null;
  period_month: number;
  budgeted_amount: string;
}

interface FiscalYear {
  id: string;
  year_label: string;
  start_date: string;
  end_date: string;
  status: string;
}

interface VsActualRow {
  account_code: string;
  account_name: string;
  department_code: string | null;
  budgeted_amount: string;
  actual_amount: string;
  variance_amount: string;
  variance_pct: string | null;
}

interface TrendRow {
  period_year: number;
  period_month: number;
  total_amount: string;
}

interface GlAccount {
  id: string;
  account_code: string;
  account_name: string;
}

type Tab = "budgets" | "trend" | "productivity";

interface BuilderLine {
  account_id: string;
  department_code: string;
  period_month: string;
  budgeted_amount: string;
}

/* ------------------------------- formatting ------------------------------- */

function formatAmount(value: string): string {
  const [intPart = "0", decPart = "00"] = value.split(".");
  const grouped = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const dec = (decPart + "00").slice(0, 2);
  return `${grouped}.${dec}`;
}

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

const inputCls =
  "h-9 rounded-md border border-input bg-transparent px-3 text-sm outline-none focus:ring-1 focus:ring-ring";

function budgetStatusVariant(status: string): "default" | "success" | "warning" {
  if (status === "LOCKED") return "warning";
  if (status === "APPROVED") return "success";
  return "default";
}

/* ------------------------------ account picker --------------------------- */

function AccountPicker({
  accounts,
  value,
  onChange,
  placeholder,
  className,
}: {
  accounts: GlAccount[] | undefined;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  className?: string;
}) {
  return (
    <select
      className={cn(inputCls, className)}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">{placeholder}</option>
      {accounts?.map((a) => (
        <option key={a.id} value={a.id}>
          {a.account_code} — {a.account_name}
        </option>
      ))}
    </select>
  );
}

/* ------------------------- shared line builder --------------------------- */

function LineBuilder({
  lines,
  setLines,
  accounts,
}: {
  lines: BuilderLine[];
  setLines: (l: BuilderLine[]) => void;
  accounts: GlAccount[] | undefined;
}) {
  const [accountId, setAccountId] = useState("");
  const [dept, setDept] = useState("");
  const [month, setMonth] = useState("1");
  const [amount, setAmount] = useState("");

  const add = () => {
    if (!accountId || !amount) return;
    setLines([
      ...lines,
      {
        account_id: accountId,
        department_code: dept,
        period_month: month,
        budgeted_amount: amount,
      },
    ]);
    setAccountId("");
    setDept("");
    setAmount("");
  };

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-[2fr_1fr_1fr_1fr_auto] gap-2 items-center">
        <AccountPicker accounts={accounts} value={accountId} onChange={setAccountId} placeholder="Account…" className="w-full" />
        <input className={inputCls} placeholder="Dept (opt)" value={dept} onChange={(e) => setDept(e.target.value)} />
        <select className={inputCls} value={month} onChange={(e) => setMonth(e.target.value)}>
          {MONTHS.map((m, i) => (
            <option key={m} value={String(i + 1)}>{m}</option>
          ))}
        </select>
        <input className={inputCls} placeholder="Amount" value={amount} onChange={(e) => setAmount(e.target.value)} />
        <Button size="sm" variant="outline" onClick={add} disabled={!accountId || !amount}>
          <Plus className="w-4 h-4" /> Add
        </Button>
      </div>
      {lines.length > 0 && (
        <Card className="divide-y">
          {lines.map((ln, i) => {
            const acc = accounts?.find((a) => a.id === ln.account_id);
            return (
              <div key={i} className="p-2.5 flex items-center gap-3 text-xs">
                <span className="font-mono">{acc?.account_code ?? "—"}</span>
                <span>{acc?.account_name ?? ""}</span>
                {ln.department_code && <span className="text-muted-foreground">{ln.department_code}</span>}
                <span className="text-muted-foreground">{MONTHS[Number(ln.period_month) - 1]}</span>
                <span className="ml-auto font-medium">{formatAmount(ln.budgeted_amount)}</span>
                <button
                  className="text-muted-foreground hover:text-foreground"
                  onClick={() => setLines(lines.filter((_, j) => j !== i))}
                >
                  ✕
                </button>
              </div>
            );
          })}
        </Card>
      )}
    </div>
  );
}

/* ------------------------------ budgets tab ------------------------------ */

function BudgetsPanel() {
  const qc = useQueryClient();
  const [showNew, setShowNew] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [newLines, setNewLines] = useState<BuilderLine[]>([]);
  const [newForm, setNewForm] = useState({ fiscal_year_id: "", budget_name: "" });
  const [reviseFor, setReviseFor] = useState<Budget | null>(null);
  const [reviseLines, setReviseLines] = useState<BuilderLine[]>([]);
  const [reviseReason, setReviseReason] = useState("");
  const [vsFor, setVsFor] = useState<string | null>(null);
  const [vsMonth, setVsMonth] = useState("12");

  const budgets = useQuery({
    queryKey: ["budgets"],
    queryFn: () => api.get<Budget[]>("/budgeting/budgets"),
  });

  const fiscalYears = useQuery({
    queryKey: ["fiscal-years"],
    queryFn: () => api.get<FiscalYear[]>("/budgeting/fiscal-years"),
  });

  const accounts = useQuery({
    queryKey: ["gl-accounts"],
    queryFn: () => api.get<GlAccount[]>("/gl/accounts"),
  });

  const existingLines = useQuery({
    queryKey: ["budget-lines", reviseFor?.id],
    queryFn: () => api.get<BudgetLine[]>(`/budgeting/budgets/${reviseFor?.id}/lines`),
    enabled: reviseFor !== null,
  });

  const vsActual = useQuery({
    queryKey: ["budget-vs-actual", vsFor, vsMonth],
    queryFn: () =>
      api.get<VsActualRow[]>(
        `/budgeting/budgets/${vsFor}/vs-actual?as_of_month=${vsMonth}`,
      ),
    enabled: vsFor !== null,
  });

  const create = useMutation({
    mutationFn: () =>
      api.post<{ budget_id: string }>("/budgeting/budgets", {
        fiscal_year_id: newForm.fiscal_year_id,
        budget_name: newForm.budget_name,
        lines: newLines.map((ln) => ({
          account_id: ln.account_id,
          department_code: ln.department_code || null,
          period_month: Number(ln.period_month),
          budgeted_amount: ln.budgeted_amount,
        })),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["budgets"] });
      setShowNew(false);
      setNewLines([]);
      setNewForm({ fiscal_year_id: "", budget_name: "" });
      setNotice("Budget created as DRAFT.");
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  const approve = useMutation({
    mutationFn: (id: string) =>
      api.post(`/budgeting/budgets/${id}/approve`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["budgets"] });
      setNotice("Budget approved.");
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  const lock = useMutation({
    mutationFn: (id: string) => api.post(`/budgeting/budgets/${id}/lock`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["budgets"] });
      setNotice("Budget locked (SUPER_ADMIN only).");
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  const revise = useMutation({
    mutationFn: (id: string) =>
      api.post<{ budget_id: string; revision_number: number }>(
        `/budgeting/budgets/${id}/revise`,
        {
          reason: reviseReason,
          lines: reviseLines.map((ln) => ({
            account_id: ln.account_id,
            department_code: ln.department_code || null,
            period_month: Number(ln.period_month),
            budgeted_amount: ln.budgeted_amount,
          })),
        },
      ),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["budgets"] });
      setReviseFor(null);
      setReviseLines([]);
      setReviseReason("");
      setNotice(`Revised — revision #${r.revision_number} (audit snapshot saved).`);
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  const startRevise = (b: Budget) => {
    setReviseFor(b);
    setError(null);
    // Prefill builder once lines arrive (via useEffect-free refetch).
    if (existingLines.data && reviseFor?.id === b.id) {
      setReviseLines(
        existingLines.data.map((ln) => ({
          account_id: ln.account_id,
          department_code: ln.department_code ?? "",
          period_month: String(ln.period_month),
          budgeted_amount: ln.budgeted_amount,
        })),
      );
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-medium flex items-center gap-2">
          <PieChart className="w-4 h-4" /> Budgets
        </h2>
        <Button size="sm" onClick={() => { setShowNew(!showNew); setError(null); }}>
          <Plus className="w-4 h-4" /> New budget
        </Button>
      </div>

      {showNew && (
        <Card className="p-5 space-y-3">
          <h3 className="text-sm font-medium">Create annual budget</h3>
          <div className="flex flex-wrap gap-3">
            <select
              className={cn(inputCls, "w-44")}
              value={newForm.fiscal_year_id}
              onChange={(e) => setNewForm({ ...newForm, fiscal_year_id: e.target.value })}
            >
              <option value="">Fiscal year…</option>
              {fiscalYears.data?.map((fy) => (
                <option key={fy.id} value={fy.id}>{fy.year_label}</option>
              ))}
            </select>
            <input
              className={cn(inputCls, "w-64")}
              placeholder="Budget name"
              value={newForm.budget_name}
              onChange={(e) => setNewForm({ ...newForm, budget_name: e.target.value })}
            />
          </div>
          <LineBuilder lines={newLines} setLines={setNewLines} accounts={accounts.data} />
          {error && <p className="text-xs text-destructive">{error}</p>}
          <div className="flex justify-end">
            <Button
              onClick={() => create.mutate()}
              disabled={
                create.isPending ||
                !newForm.fiscal_year_id ||
                !newForm.budget_name ||
                newLines.length === 0
              }
            >
              {create.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
              Create draft
            </Button>
          </div>
        </Card>
      )}

      {notice && <p className="text-xs text-success">{notice}</p>}

      <Card className="divide-y">
        {budgets.isLoading ? (
          <div className="p-6 text-sm text-muted-foreground">Loading…</div>
        ) : budgets.data?.length === 0 ? (
          <div className="p-6 text-sm text-muted-foreground">No budgets yet.</div>
        ) : (
          budgets.data?.map((b) => (
            <div key={b.id} className="p-4 flex flex-wrap items-center gap-3 text-sm">
              <PieChart className="w-4 h-4 text-muted-foreground" />
              <span className="font-medium">{b.budget_name}</span>
              <Badge variant="outline">{b.year_label}</Badge>
              <Badge variant={budgetStatusVariant(b.status)}>{b.status}</Badge>
              <div className="ml-auto flex items-center gap-2">
                {b.status === "DRAFT" && (
                  <Button size="sm" variant="outline" onClick={() => approve.mutate(b.id)}>
                    Approve
                  </Button>
                )}
                {b.status === "APPROVED" && (
                  <Button size="sm" variant="outline" onClick={() => lock.mutate(b.id)}>
                    <Lock className="w-4 h-4" /> Lock
                  </Button>
                )}
                {b.status !== "DRAFT" && (
                  <Button size="sm" variant="outline" onClick={() => startRevise(b)}>
                    Revise
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setVsFor(vsFor === b.id ? null : b.id)}
                >
                  Vs actual
                </Button>
              </div>
            </div>
          ))
        )}
      </Card>

      {reviseFor && (
        <Card className="p-5 space-y-3">
          <h3 className="text-sm font-medium">
            Revise budget — {reviseFor.budget_name} (audit snapshot saved automatically)
          </h3>
          {existingLines.isLoading ? (
            <div className="text-sm text-muted-foreground">Loading existing lines…</div>
          ) : (
            <LineBuilder lines={reviseLines} setLines={setReviseLines} accounts={accounts.data} />
          )}
          <input
            className={cn(inputCls, "w-full")}
            placeholder="Revision reason (required)"
            value={reviseReason}
            onChange={(e) => setReviseReason(e.target.value)}
          />
          {error && <p className="text-xs text-destructive">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setReviseFor(null)}>Cancel</Button>
            <Button
              onClick={() => revise.mutate(reviseFor.id)}
              disabled={revise.isPending || !reviseReason || reviseLines.length === 0}
            >
              {revise.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
              Submit revision
            </Button>
          </div>
        </Card>
      )}

      {vsFor && (
        <Card className="divide-y">
          <div className="p-4 flex items-center gap-3">
            <span className="text-sm font-medium">Budget vs actual — as of month</span>
            <input
              className={cn(inputCls, "w-20")}
              value={vsMonth}
              onChange={(e) => setVsMonth(e.target.value)}
              aria-label="As of month"
            />
          </div>
          {vsActual.isLoading ? (
            <div className="p-4 text-sm text-muted-foreground">Loading…</div>
          ) : vsActual.data?.length === 0 ? (
            <div className="p-4 text-sm text-muted-foreground">No lines in this budget.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="p-2">Account</th>
                    <th className="p-2">Dept</th>
                    <th className="p-2 text-right">Budgeted</th>
                    <th className="p-2 text-right">Actual</th>
                    <th className="p-2 text-right">Variance</th>
                    <th className="p-2 text-right">%</th>
                  </tr>
                </thead>
                <tbody>
                  {vsActual.data?.map((r, i) => (
                    <tr key={i} className="border-b border-border/50">
                      <td className="p-2">
                        <span className="font-mono">{r.account_code}</span> {r.account_name}
                      </td>
                      <td className="p-2">{r.department_code ?? "—"}</td>
                      <td className="p-2 text-right">{formatAmount(r.budgeted_amount)}</td>
                      <td className="p-2 text-right">{formatAmount(r.actual_amount)}</td>
                      <td className={cn("p-2 text-right", Number(r.variance_amount) < 0 ? "text-destructive" : "text-success")}>
                        {formatAmount(r.variance_amount)}
                      </td>
                      <td className="p-2 text-right">{r.variance_pct ? `${Number(r.variance_pct).toFixed(2)}%` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}

/* ------------------------------- trend tab -------------------------------- */

function TrendPanel() {
  const [accountType, setAccountType] = useState("REVENUE");
  const [numMonths, setNumMonths] = useState("12");

  const trend = useQuery({
    queryKey: ["trend", accountType, numMonths],
    queryFn: () =>
      api.get<TrendRow[]>(
        `/budgeting/trend?account_type=${accountType}&num_months=${numMonths}`,
      ),
  });

  const max = Math.max(
    ...[...(trend.data ?? []).map((r) => Number(r.total_amount)), 1],
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-medium flex items-center gap-2">
          <TrendingUp className="w-4 h-4" /> Monthly trend
        </h2>
        <div className="flex items-center gap-2">
          <select
            className={cn(inputCls, "w-36")}
            value={accountType}
            onChange={(e) => setAccountType(e.target.value)}
          >
            <option value="REVENUE">REVENUE</option>
            <option value="EXPENSE">EXPENSE</option>
          </select>
          <input
            className={cn(inputCls, "w-20")}
            value={numMonths}
            onChange={(e) => setNumMonths(e.target.value)}
            aria-label="Months"
          />
          <span className="text-xs text-muted-foreground">months</span>
        </div>
      </div>

      <Card className="p-5">
        {trend.isLoading ? (
          <div className="text-sm text-muted-foreground">Loading…</div>
        ) : trend.data?.length === 0 ? (
          <div className="text-sm text-muted-foreground">No posted journals in this window.</div>
        ) : (
          <div className="space-y-2">
            {trend.data?.map((r, i) => (
              <div key={i} className="flex items-center gap-3 text-xs">
                <span className="w-20 text-muted-foreground">
                  {MONTHS[r.period_month - 1]} {r.period_year}
                </span>
                <div className="flex-1 h-4 rounded bg-secondary overflow-hidden">
                  <div
                    className="h-full rounded bg-primary"
                    style={{ width: `${(Number(r.total_amount) / max) * 100}%` }}
                  />
                </div>
                <span className="w-32 text-right font-medium">{formatAmount(r.total_amount)}</span>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

/* --------------------------- productivity tab ---------------------------- */

function ProductivityPanel() {
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [form, setForm] = useState({
    period_year: String(new Date().getFullYear()),
    period_month: String(new Date().getMonth() + 1),
  });

  const run = useMutation({
    mutationFn: () =>
      api.post<{ metrics_calculated: number }>(
        `/budgeting/productivity/batch?period_year=${form.period_year}&period_month=${form.period_month}`,
      ),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["productivity"] });
      setNotice(`Batch done — ${r.metrics_calculated} metric(s) calculated (idempotent).`);
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-medium flex items-center gap-2">
        <BarChart3 className="w-4 h-4" /> Employee productivity batch
      </h2>

      <Card className="p-5 space-y-3">
        <p className="text-xs text-muted-foreground">
          Joins sales activity to employees and computes per-employee metrics
          for the period. Safe to re-run (upsert).
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <input
            className={cn(inputCls, "w-24")}
            placeholder="Year"
            value={form.period_year}
            onChange={(e) => setForm({ ...form, period_year: e.target.value })}
          />
          <select
            className={cn(inputCls, "w-28")}
            value={form.period_month}
            onChange={(e) => setForm({ ...form, period_month: e.target.value })}
          >
            {MONTHS.map((m, i) => (
              <option key={m} value={String(i + 1)}>{m}</option>
            ))}
          </select>
          <Button onClick={() => run.mutate()} disabled={run.isPending}>
            {run.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
            Run batch
          </Button>
        </div>
        {error && <p className="text-xs text-destructive">{error}</p>}
        {notice && <p className="text-xs text-success">{notice}</p>}
      </Card>
    </div>
  );
}

/* --------------------------------- page ----------------------------------- */

export function BudgetingPage() {
  const [tab, setTab] = useState<Tab>("budgets");

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-medium">Budgeting &amp; Analytics</h1>
          <p className="text-sm text-muted-foreground">
            Annual budgets with audit-trailed revisions, variance reporting, and trends.
          </p>
        </div>
      </div>

      <div className="flex gap-1 border-b border-border">
        {(["budgets", "trend", "productivity"] as Tab[]).map((t) => (
          <button
            key={t}
            className={cn(
              "px-4 py-2 text-sm capitalize border-b-2 -mb-px",
              tab === t
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === "budgets" && <BudgetsPanel />}
      {tab === "trend" && <TrendPanel />}
      {tab === "productivity" && <ProductivityPanel />}
    </div>
  );
}
