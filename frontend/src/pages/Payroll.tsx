/**
 * Payroll (M2) — employee master, payroll periods, and the
 * three-step run lifecycle (calculate -> approve -> disburse)
 * with period entries drill-down.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { Badge, Button, Card } from "@/components/ui";
import { cn } from "@/lib/utils";
import {
  BadgeCheck,
  Banknote,
  CalendarClock,
  Calculator,
  Loader2,
  Plus,
  Users,
} from "lucide-react";

/* --------------------------------- types --------------------------------- */

interface Employee {
  id: string;
  employee_code: string;
  full_name: string;
  position: string | null;
  department_code: string | null;
  base_salary: string;
  bank_account_no: string | null;
  npwp: string | null;
  hire_date: string;
  termination_date: string | null;
}

interface PayrollPeriod {
  id: string;
  period_year: number;
  period_month: number;
  start_date: string;
  end_date: string;
  accrual_journal_entry_id: string | null;
  journal_entry_id: string | null;
}

interface PeriodEntry {
  id: string;
  employee_id: string;
  full_name: string;
  working_days: number;
  unpaid_days: number;
  overtime_hours: string;
  gross_earning: string;
  total_deduction: string;
  net_pay: string;
}

interface GlAccount {
  id: string;
  account_code: string;
  account_name: string;
}

type Tab = "employees" | "periods";

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

/* ------------------------------ employee form ---------------------------- */

function EmployeeForm({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState({
    employee_code: "",
    full_name: "",
    position: "",
    department_code: "",
    base_salary: "",
    hire_date: "",
  });
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      api.post("/hr/employees", {
          employee_code: form.employee_code,
          full_name: form.full_name,
          position: form.position || null,
          department_code: form.department_code || null,
          base_salary: form.base_salary,
          hire_date: form.hire_date,
        }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["employees"] });
      onDone();
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [k]: e.target.value });

  return (
    <Card className="p-5 space-y-3">
      <h3 className="text-sm font-medium">Add employee</h3>
      <div className="grid grid-cols-2 gap-3">
        <input className={inputCls} placeholder="Employee code" value={form.employee_code} onChange={set("employee_code")} />
        <input className={inputCls} placeholder="Full name" value={form.full_name} onChange={set("full_name")} />
        <input className={inputCls} placeholder="Position" value={form.position} onChange={set("position")} />
        <input className={inputCls} placeholder="Department" value={form.department_code} onChange={set("department_code")} />
        <input className={inputCls} placeholder="Base salary (e.g. 5000000)" value={form.base_salary} onChange={set("base_salary")} />
        <input className={inputCls} type="date" value={form.hire_date} onChange={set("hire_date")} />
      </div>
      {error && <p className="text-xs text-destructive">{error}</p>}
      <div className="flex gap-2 justify-end">
        <Button variant="ghost" onClick={onDone}>Cancel</Button>
        <Button onClick={() => mutation.mutate()} disabled={mutation.isPending || !form.employee_code || !form.full_name || !form.base_salary || !form.hire_date}>
          {mutation.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
          Save
        </Button>
      </div>
    </Card>
  );
}

const inputCls =
  "h-9 rounded-md border border-input bg-transparent px-3 text-sm outline-none focus:ring-1 focus:ring-ring";

/* ------------------------------ periods panel ---------------------------- */

function PeriodsPanel() {
  const qc = useQueryClient();
  const [showNew, setShowNew] = useState(false);
  const [entriesFor, setEntriesFor] = useState<string | null>(null);
  const [calcEmp, setCalcEmp] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const periods = useQuery({
    queryKey: ["payroll-periods"],
    queryFn: () => api.get<PayrollPeriod[]>("/hr/payroll/periods"),
  });

  const employees = useQuery({
    queryKey: ["employees"],
    queryFn: () => api.get<Employee[]>("/hr/employees"),
  });

  const accounts = useQuery({
    queryKey: ["gl-accounts"],
    queryFn: () => api.get<GlAccount[]>("/gl/accounts") as Promise<GlAccount[]>,
  });

  const entries = useQuery({
    queryKey: ["period-entries", entriesFor],
    queryFn: () =>
      api.get<PeriodEntry[]>(`/hr/payroll/periods/${entriesFor}/entries`),
    enabled: entriesFor !== null,
  });

  const createPeriod = useMutation({
    mutationFn: (body: { period_year: number; period_month: number; start_date: string; end_date: string }) =>
      api.post("/hr/payroll/periods", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["payroll-periods"] });
      setShowNew(false);
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  const calculate = useMutation({
    mutationFn: (body: { employee_id: string; payroll_period_id: string }) =>
      api.post("/hr/payroll/calculate", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["period-entries"] });
      setCalcEmp(null);
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  const [approveFor, setApproveFor] = useState<string | null>(null);
  const [disburseFor, setDisburseFor] = useState<string | null>(null);
  const [pickedAccount, setPickedAccount] = useState("");

  const approve = useMutation({
    mutationFn: (body: { payroll_period_id: string; ap_gaji_account_id: string }) =>
      api.post("/hr/payroll/approve", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["payroll-periods"] });
      setApproveFor(null);
      setPickedAccount("");
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  const disburse = useMutation({
    mutationFn: (body: { payroll_period_id: string; kas_bank_account_id: string }) =>
      api.post("/hr/payroll/disburse", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["payroll-periods"] });
      setDisburseFor(null);
      setPickedAccount("");
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  const [form, setForm] = useState({
    period_year: String(new Date().getFullYear()),
    period_month: String(new Date().getMonth() + 1),
    start_date: "",
    end_date: "",
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-medium">Payroll periods</h2>
        <Button size="sm" onClick={() => setShowNew(!showNew)}>
          <Plus className="w-4 h-4" /> New period
        </Button>
      </div>
      {showNew && (
        <Card className="p-5 space-y-3">
          <div className="grid grid-cols-4 gap-3">
            <input className={inputCls} placeholder="Year" value={form.period_year} onChange={(e) => setForm({ ...form, period_year: e.target.value })} />
            <input className={inputCls} placeholder="Month 1-12" value={form.period_month} onChange={(e) => setForm({ ...form, period_month: e.target.value })} />
            <input className={inputCls} type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} />
            <input className={inputCls} type="date" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} />
          </div>
          <Button size="sm" onClick={() =>
            createPeriod.mutate({
              period_year: Number(form.period_year),
              period_month: Number(form.period_month),
              start_date: form.start_date,
              end_date: form.end_date,
            })
          } disabled={createPeriod.isPending || !form.start_date || !form.end_date}>
            {createPeriod.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
            Create
          </Button>
        </Card>
      )}
      {error && <p className="text-xs text-destructive">{error}</p>}

      <Card className="divide-y">
        {periods.isLoading ? (
          <div className="p-6 text-sm text-muted-foreground">Loading…</div>
        ) : periods.data?.length === 0 ? (
          <div className="p-6 text-sm text-muted-foreground">No payroll periods yet.</div>
        ) : (
          periods.data?.map((p) => (
            <div key={p.id} className="p-4 flex flex-wrap items-center gap-3">
              <CalendarClock className="w-4 h-4 text-muted-foreground" />
              <div className="min-w-32">
                <div className="text-sm font-medium">
                  {MONTHS[p.period_month - 1]} {p.period_year}
                </div>
                <div className="text-xs text-muted-foreground">
                  {p.start_date} → {p.end_date}
                </div>
              </div>
              <Badge variant={p.journal_entry_id ? "success" : "default"}>
                {p.journal_entry_id ? "DISBURSED" : "OPEN"}
              </Badge>
              <div className="ml-auto flex items-center gap-2">
                <Button size="sm" variant="outline" onClick={() => setCalcEmp(p.id)}>
                  <Calculator className="w-4 h-4" /> Calculate
                </Button>
                <Button size="sm" variant="outline" onClick={() => { setApproveFor(p.id); setPickedAccount(""); }}>
                  <BadgeCheck className="w-4 h-4" /> Approve
                </Button>
                <Button size="sm" variant="outline" onClick={() => { setDisburseFor(p.id); setPickedAccount(""); }}>
                  <Banknote className="w-4 h-4" /> Disburse
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setEntriesFor(entriesFor === p.id ? null : p.id)}>
                  Entries
                </Button>
              </div>
            </div>
          ))
        )}
      </Card>

      {calcEmp && (
        <Card className="p-5 space-y-3">
          <h3 className="text-sm font-medium">Calculate payroll entry</h3>
          <select
            className={cn(inputCls, "w-64")}
            value=""
            onChange={(e) => {
              if (e.target.value) {
                calculate.mutate({
                  employee_id: e.target.value,
                  payroll_period_id: calcEmp,
                });
              }
            }}
          >
            <option value="">Select employee…</option>
            {employees.data?.map((emp) => (
              <option key={emp.id} value={emp.id}>
                {emp.employee_code} — {emp.full_name}
              </option>
            ))}
          </select>
          <p className="text-xs text-muted-foreground">
            Computes gross, BPJS + TER deductions, and net pay for the selected employee in this period.
          </p>
        </Card>
      )}

      {approveFor && (
        <Card className="p-5 space-y-3">
          <h3 className="text-sm font-medium">Approve payroll — select AP Gaji (accrued salary) account</h3>
          <select
            className={cn(inputCls, "w-80")}
            value={pickedAccount}
            onChange={(e) => setPickedAccount(e.target.value)}
          >
            <option value="">Select account…</option>
            {accounts.data?.map((a) => (
              <option key={a.id} value={a.id}>
                {a.account_code} — {a.account_name}
              </option>
            ))}
          </select>
          <Button
            size="sm"
            disabled={!pickedAccount || approve.isPending}
            onClick={() => approve.mutate({ payroll_period_id: approveFor, ap_gaji_account_id: pickedAccount })}
          >
            {approve.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
            Approve &amp; post accrual
          </Button>
        </Card>
      )}

      {disburseFor && (
        <Card className="p-5 space-y-3">
          <h3 className="text-sm font-medium">Disburse payroll — select kas/bank account</h3>
          <select
            className={cn(inputCls, "w-80")}
            value={pickedAccount}
            onChange={(e) => setPickedAccount(e.target.value)}
          >
            <option value="">Select account…</option>
            {accounts.data?.map((a) => (
              <option key={a.id} value={a.id}>
                {a.account_code} — {a.account_name}
              </option>
            ))}
          </select>
          <Button
            size="sm"
            disabled={!pickedAccount || disburse.isPending}
            onClick={() => disburse.mutate({ payroll_period_id: disburseFor, kas_bank_account_id: pickedAccount })}
          >
            {disburse.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
            Disburse &amp; post payment
          </Button>
        </Card>
      )}

      {entriesFor && (
        <Card className="divide-y">
          <div className="p-4 text-sm font-medium">
            Period entries
          </div>
          {entries.isLoading ? (
            <div className="p-4 text-sm text-muted-foreground">Loading…</div>
          ) : entries.data?.length === 0 ? (
            <div className="p-4 text-sm text-muted-foreground">
              No entries calculated for this period yet.
            </div>
          ) : (
            entries.data?.map((en) => (
              <div key={en.id} className="p-4 flex flex-wrap items-center gap-3 text-sm">
                <span className="min-w-40 font-medium">{en.full_name}</span>
                <span className="text-muted-foreground">{en.working_days}d</span>
                <span className="text-muted-foreground">OT {en.overtime_hours}h</span>
                <span className="text-muted-foreground">gross {formatAmount(en.gross_earning)}</span>
                <span className="text-muted-foreground">ded {formatAmount(en.total_deduction)}</span>
                <span className="ml-auto font-medium">net {formatAmount(en.net_pay)}</span>
              </div>
            ))
          )}
        </Card>
      )}
    </div>
  );
}

/* --------------------------------- page ---------------------------------- */

export function PayrollPage() {
  const [tab, setTab] = useState<Tab>("periods");
  const [showForm, setShowForm] = useState(false);
  const employees = useQuery({
    queryKey: ["employees"],
    queryFn: () => api.get<Employee[]>("/hr/employees"),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-medium">Payroll</h1>
          <p className="text-sm text-muted-foreground">
            Employee master and payroll runs — BPJS and TER computed by the engine.
          </p>
        </div>
      </div>

      <div className="flex gap-1 border-b border-border">
        {(["periods", "employees"] as Tab[]).map((t) => (
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

      {tab === "employees" && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-medium flex items-center gap-2">
              <Users className="w-4 h-4" /> Employees ({employees.data?.length ?? 0})
            </h2>
            <Button size="sm" onClick={() => setShowForm(!showForm)}>
              <Plus className="w-4 h-4" /> Add
            </Button>
          </div>
          {showForm && <EmployeeForm onDone={() => setShowForm(false)} />}
          <Card className="divide-y">
            {employees.isLoading ? (
              <div className="p-6 text-sm text-muted-foreground">Loading…</div>
            ) : employees.data?.length === 0 ? (
              <div className="p-6 text-sm text-muted-foreground">No employees yet.</div>
            ) : (
              employees.data?.map((emp) => (
                <div key={emp.id} className="p-4 flex flex-wrap items-center gap-3 text-sm">
                  <span className="font-mono text-xs text-muted-foreground">{emp.employee_code}</span>
                  <span className="font-medium">{emp.full_name}</span>
                  {emp.position && <span className="text-muted-foreground">{emp.position}</span>}
                  <Badge variant="default">{emp.department_code ?? "—"}</Badge>
                  <span className="ml-auto font-medium">{formatAmount(emp.base_salary)}</span>
                </div>
              ))
            )}
          </Card>
        </div>
      )}

      {tab === "periods" && <PeriodsPanel />}
    </div>
  );
}
