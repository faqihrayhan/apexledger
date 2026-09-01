/**
 * Treasury (M6) — kasbon lifecycle, bank account master,
 * statement import + auto-match reconciliation, and the
 * read-only cash flow forecast.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { Badge, Button, Card } from "@/components/ui";
import { cn } from "@/lib/utils";
import {
  ArrowDownLeft,
  ArrowUpRight,
  BadgeCheck,
  Banknote,
  HandCoins,
  Landmark,
  Loader2,
  Plus,
  SearchCheck,
} from "lucide-react";

/* --------------------------------- types --------------------------------- */

interface BankAccount {
  id: string;
  bank_name: string;
  account_number: string;
  account_name: string;
  currency_code: string;
  is_active: boolean;
}

interface Kasbon {
  id: string;
  status: string;
  amount: string;
  purpose: string;
  required_approval_role: string | null;
}

interface GlAccount {
  id: string;
  account_code: string;
  account_name: string;
}

interface ForecastRow {
  week_start: string;
  category: string;
  source_type: string;
  estimated_amount: string;
}

type Tab = "kasbon" | "banks" | "recon" | "forecast";

type KasbonAction = "disburse" | "settle";

/* ------------------------------- formatting ------------------------------- */

function formatAmount(value: string): string {
  const [intPart = "0", decPart = "00"] = value.split(".");
  const grouped = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const dec = (decPart + "00").slice(0, 2);
  return `${grouped}.${dec}`;
}

const inputCls =
  "h-9 rounded-md border border-input bg-transparent px-3 text-sm outline-none focus:ring-1 focus:ring-ring";

function kasbonStatusVariant(status: string): "default" | "success" | "warning" | "outline" {
  if (status === "SETTLED") return "success";
  if (status === "DISBURSED") return "warning";
  if (status === "PENDING_APPROVAL") return "outline";
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

/* ------------------------------- kasbon tab ------------------------------ */

function KasbonPanel() {
  const qc = useQueryClient();
  const [showNew, setShowNew] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionFor, setActionFor] = useState<string | null>(null);
  const [action, setAction] = useState<KasbonAction>("disburse");
  const [bankId, setBankId] = useState("");
  const [piutangId, setPiutangId] = useState("");
  const [settleDate, setSettleDate] = useState("");
  const [expenseAccount, setExpenseAccount] = useState("");
  const [lineDesc, setLineDesc] = useState("");
  const [lineAmount, setLineAmount] = useState("");
  const [settleLines, setSettleLines] = useState<
    { expense_account_id: string; description: string; amount: string; receipt_reference: string | null }[]
  >([]);

  const kasbon = useQuery({
    queryKey: ["kasbon"],
    queryFn: () => api.get<Kasbon[]>("/treasury/kasbon"),
  });

  const accounts = useQuery({
    queryKey: ["gl-accounts"],
    queryFn: () => api.get<GlAccount[]>("/gl/accounts"),
  });

  const [form, setForm] = useState({
    department_code: "",
    amount: "",
    purpose: "",
    request_date: "",
  });

  const create = useMutation({
    mutationFn: () =>
      api.post("/treasury/kasbon", {
        department_code: form.department_code || null,
        amount: form.amount,
        purpose: form.purpose,
        request_date: form.request_date,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["kasbon"] });
      setShowNew(false);
      setForm({ department_code: "", amount: "", purpose: "", request_date: "" });
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  const submit = useMutation({
    mutationFn: (id: string) =>
      api.post<{ kasbon_request_id: string; required_approval_role: string }>(
        `/treasury/kasbon/${id}/submit`,
      ),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["kasbon"] });
      setNotice(`Submitted — requires ${r.required_approval_role} approval.`);
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  const approve = useMutation({
    mutationFn: (id: string) =>
      api.post(`/treasury/kasbon/${id}/approve`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["kasbon"] });
      setNotice("Kasbon approved.");
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  const disburse = useMutation({
    mutationFn: (body: { id: string; bank_account_id: string; piutang_karyawan_account_id: string }) =>
      api.post(`/treasury/kasbon/${body.id}/disburse`, {
        bank_account_id: body.bank_account_id,
        piutang_karyawan_account_id: body.piutang_karyawan_account_id,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["kasbon"] });
      setActionFor(null);
      setBankId("");
        setPiutangId("");
      setNotice("Kasbon disbursed — GL journal posted (Dr receivable / Cr bank).");
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  const settle = useMutation({
    mutationFn: (body: {
      id: string;
      settlement_date: string;
      piutang_karyawan_account_id: string;
      bank_account_id: string;
      lines: { expense_account_id: string; description: string; amount: string; receipt_reference: string | null }[];
    }) =>
      api.post(`/treasury/kasbon/${body.id}/settle`, {
        settlement_date: body.settlement_date,
        piutang_karyawan_account_id: body.piutang_karyawan_account_id,
        bank_account_id: body.bank_account_id,
        lines: body.lines,
      }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["kasbon"] });
      setActionFor(null);
      setSettleLines([]);
      setSettleDate("");
      setPiutangId("");
      setBankId("");
      const resp = r as { actual_used?: string; refund?: string; additional_claim?: string };
      setNotice(
        `Settled — used ${formatAmount(resp.actual_used ?? "0")}` +
          `, refund ${formatAmount(resp.refund ?? "0")}` +
          `, additional claim ${formatAmount(resp.additional_claim ?? "0")}.`,
      );
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  const addSettleLine = () => {
    if (!expenseAccount || !lineAmount || !lineDesc) return;
    setSettleLines([
      ...settleLines,
      {
        expense_account_id: expenseAccount,
        description: lineDesc,
        amount: lineAmount,
        receipt_reference: null,
      },
    ]);
    setExpenseAccount("");
    setLineDesc("");
    setLineAmount("");
  };

  const openAction = (id: string, act: KasbonAction) => {
    setActionFor(id);
    setAction(act);
    setBankId("");
    setPiutangId("");
    setSettleDate("");
    setSettleLines([]);
    setError(null);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-medium flex items-center gap-2">
          <HandCoins className="w-4 h-4" /> Kasbon requests
        </h2>
        <Button size="sm" onClick={() => setShowNew(!showNew)}>
          <Plus className="w-4 h-4" /> New kasbon
        </Button>
      </div>

      {showNew && (
        <Card className="p-5 space-y-3">
          <h3 className="text-sm font-medium">New kasbon request</h3>
          <div className="grid grid-cols-2 gap-3">
            <input className={inputCls} placeholder="Department (optional)" value={form.department_code} onChange={(e) => setForm({ ...form, department_code: e.target.value })} />
            <input className={inputCls} placeholder="Amount (e.g. 6000000)" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
            <input className={inputCls} placeholder="Purpose" value={form.purpose} onChange={(e) => setForm({ ...form, purpose: e.target.value })} />
            <input className={inputCls} type="date" value={form.request_date} onChange={(e) => setForm({ ...form, request_date: e.target.value })} />
          </div>
          {error && <p className="text-xs text-destructive">{error}</p>}
          <div className="flex justify-end">
            <Button
              onClick={() => create.mutate()}
              disabled={create.isPending || !form.amount || !form.purpose || !form.request_date}
            >
              {create.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
              Save draft
            </Button>
          </div>
        </Card>
      )}

      {notice && <p className="text-xs text-success">{notice}</p>}

      <Card className="divide-y">
        {kasbon.isLoading ? (
          <div className="p-6 text-sm text-muted-foreground">Loading…</div>
        ) : kasbon.data?.length === 0 ? (
          <div className="p-6 text-sm text-muted-foreground">No kasbon requests yet.</div>
        ) : (
          kasbon.data?.map((k) => (
            <div key={k.id} className="p-4 flex flex-wrap items-center gap-3 text-sm">
              <HandCoins className="w-4 h-4 text-muted-foreground" />
              <div className="min-w-48">
                <div className="font-medium">{formatAmount(k.amount)}</div>
                <div className="text-xs text-muted-foreground">{k.purpose}</div>
              </div>
              <Badge variant={kasbonStatusVariant(k.status)}>{k.status}</Badge>
              {k.required_approval_role && (
                <span className="text-xs text-muted-foreground">needs {k.required_approval_role}</span>
              )}
              <div className="ml-auto flex items-center gap-2">
                {k.status === "DRAFT" && (
                  <Button size="sm" variant="outline" onClick={() => submit.mutate(k.id)}>
                    Submit
                  </Button>
                )}
                {k.status === "PENDING_APPROVAL" && (
                  <Button size="sm" variant="outline" onClick={() => approve.mutate(k.id)}>
                    <BadgeCheck className="w-4 h-4" /> Approve
                  </Button>
                )}
                {k.status === "APPROVED" && (
                  <Button size="sm" variant="outline" onClick={() => openAction(k.id, "disburse")}>
                    <Banknote className="w-4 h-4" /> Disburse
                  </Button>
                )}
                {k.status === "DISBURSED" && (
                  <Button size="sm" variant="outline" onClick={() => openAction(k.id, "settle")}>
                    Settle
                  </Button>
                )}
              </div>
            </div>
          ))
        )}
      </Card>

      {actionFor && action === "disburse" && (
        <Card className="p-5 space-y-3">
          <h3 className="text-sm font-medium">Disburse kasbon — pick bank &amp; employee receivable accounts</h3>
          <div className="flex flex-wrap gap-3">
            <AccountPicker accounts={accounts.data} value={bankId} onChange={setBankId} placeholder="Bank / cash account…" className="w-80" />
            <AccountPicker accounts={accounts.data} value={piutangId} onChange={setPiutangId} placeholder="Employee receivable (piutang)…" className="w-80" />
          </div>
          {error && <p className="text-xs text-destructive">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setActionFor(null)}>Cancel</Button>
            <Button
              disabled={!bankId || !piutangId || disburse.isPending}
              onClick={() => disburse.mutate({ id: actionFor, bank_account_id: bankId, piutang_karyawan_account_id: piutangId })}
            >
              {disburse.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
              Disburse &amp; post journal
            </Button>
          </div>
        </Card>
      )}

      {actionFor && action === "settle" && (
        <Card className="p-5 space-y-3">
          <h3 className="text-sm font-medium">Settle kasbon — expense lines, refund &amp; additional claim</h3>
          <div className="flex flex-wrap gap-3">
            <input className={cn(inputCls, "w-40")} type="date" value={settleDate} onChange={(e) => setSettleDate(e.target.value)} />
            <AccountPicker accounts={accounts.data} value={piutangId} onChange={setPiutangId} placeholder="Employee receivable (piutang)…" className="w-72" />
            <AccountPicker accounts={accounts.data} value={bankId} onChange={setBankId} placeholder="Bank / cash account…" className="w-72" />
          </div>
          <div className="grid grid-cols-[1fr_2fr_1fr_auto] gap-3 items-center">
            <AccountPicker accounts={accounts.data} value={expenseAccount} onChange={setExpenseAccount} placeholder="Expense account…" className="w-full" />
            <input className={inputCls} placeholder="Description" value={lineDesc} onChange={(e) => setLineDesc(e.target.value)} />
            <input className={inputCls} placeholder="Amount" value={lineAmount} onChange={(e) => setLineAmount(e.target.value)} />
            <Button size="sm" variant="outline" onClick={addSettleLine} disabled={!expenseAccount || !lineDesc || !lineAmount}>
              <Plus className="w-4 h-4" /> Add line
            </Button>
          </div>
          {settleLines.length > 0 && (
            <Card className="divide-y">
              {settleLines.map((ln, i) => (
                <div key={i} className="p-2.5 flex items-center gap-3 text-xs">
                  <span>{accounts.data?.find((a) => a.id === ln.expense_account_id)?.account_name ?? "—"}</span>
                  <span className="text-muted-foreground">{ln.description}</span>
                  <span className="ml-auto font-medium">{formatAmount(ln.amount)}</span>
                  <button className="text-muted-foreground hover:text-foreground" onClick={() => setSettleLines(settleLines.filter((_, j) => j !== i))}>✕</button>
                </div>
              ))}
            </Card>
            )}
          {error && <p className="text-xs text-destructive">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setActionFor(null)}>Cancel</Button>
            <Button
              disabled={!settleDate || !piutangId || !bankId || settleLines.length === 0 || settle.isPending}
              onClick={() =>
                settle.mutate({
                  id: actionFor,
                  settlement_date: settleDate,
                  piutang_karyawan_account_id: piutangId,
                  bank_account_id: bankId,
                  lines: settleLines,
                })
              }
            >
              {settle.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
              Settle &amp; post journal
            </Button>
          </div>
        </Card>
      )}
    </div>
  );
}

/* ------------------------------ banks tab -------------------------------- */

function BanksPanel() {
  const qc = useQueryClient();
  const [showNew, setShowNew] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    bank_name: "",
    account_number: "",
    account_name: "",
    currency_code: "IDR",
    gl_account_id: "",
  });

  const banks = useQuery({
    queryKey: ["bank-accounts"],
    queryFn: () => api.get<BankAccount[]>("/treasury/bank-accounts"),
  });

  const accounts = useQuery({
    queryKey: ["gl-accounts"],
    queryFn: () => api.get<GlAccount[]>("/gl/accounts"),
  });

  const create = useMutation({
    mutationFn: () =>
      api.post("/treasury/bank-accounts", {
        bank_name: form.bank_name,
        account_number: form.account_number,
        account_name: form.account_name,
        currency_code: form.currency_code,
        gl_account_id: form.gl_account_id,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bank-accounts"] });
      setShowNew(false);
      setForm({ bank_name: "", account_number: "", account_name: "", currency_code: "IDR", gl_account_id: "" });
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-medium flex items-center gap-2">
          <Landmark className="w-4 h-4" /> Bank accounts
        </h2>
        <Button size="sm" onClick={() => setShowNew(!showNew)}>
          <Plus className="w-4 h-4" /> Add
        </Button>
      </div>

      {showNew && (
        <Card className="p-5 space-y-3">
          <h3 className="text-sm font-medium">Add bank account</h3>
          <div className="grid grid-cols-2 gap-3">
            <input className={inputCls} placeholder="Bank name" value={form.bank_name} onChange={(e) => setForm({ ...form, bank_name: e.target.value })} />
            <input className={inputCls} placeholder="Account number" value={form.account_number} onChange={(e) => setForm({ ...form, account_number: e.target.value })} />
            <input className={inputCls} placeholder="Account name" value={form.account_name} onChange={(e) => setForm({ ...form, account_name: e.target.value })} />
            <input className={inputCls} placeholder="Currency (IDR)" value={form.currency_code} onChange={(e) => setForm({ ...form, currency_code: e.target.value })} />
          </div>
          <AccountPicker accounts={accounts.data} value={form.gl_account_id} onChange={(v) => setForm({ ...form, gl_account_id: v })} placeholder="GL account for this bank…" className="w-80" />
          {error && <p className="text-xs text-destructive">{error}</p>}
          <div className="flex justify-end">
            <Button
              onClick={() => create.mutate()}
              disabled={create.isPending || !form.bank_name || !form.account_number || !form.account_name || !form.gl_account_id}
            >
              {create.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
              Save
            </Button>
          </div>
        </Card>
      )}

      <Card className="divide-y">
        {banks.isLoading ? (
          <div className="p-6 text-sm text-muted-foreground">Loading…</div>
        ) : banks.data?.length === 0 ? (
          <div className="p-6 text-sm text-muted-foreground">No bank accounts yet.</div>
        ) : (
          banks.data?.map((b) => (
            <div key={b.id} className="p-4 flex flex-wrap items-center gap-3 text-sm">
              <Landmark className="w-4 h-4 text-muted-foreground" />
              <span className="font-medium">{b.bank_name}</span>
              <span className="font-mono text-xs text-muted-foreground">{b.account_number}</span>
              <span className="text-muted-foreground">{b.account_name}</span>
              <Badge variant="outline">{b.currency_code}</Badge>
              {b.is_active ? <Badge variant="success">active</Badge> : <Badge>inactive</Badge>}
            </div>
          ))
        )}
      </Card>
    </div>
  );
}

/* ------------------------------ recon tab -------------------------------- */

function ReconPanel() {
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [date, setDate] = useState("");
  const [desc, setDesc] = useState("");
  const [amount, setAmount] = useState("");

  const banks = useQuery({
    queryKey: ["bank-accounts"],
    queryFn: () => api.get<BankAccount[]>("/treasury/bank-accounts"),
  });

  const [selectedBank, setSelectedBank] = useState("");
  const [linesByBank, setLinesByBank] = useState<Record<string, { statement_date: string; description: string; amount: string }[]>>({});

  const importStmt = useMutation({
    mutationFn: (body: { bankId: string; lines: { statement_date: string; description: string; amount: string }[] }) =>
      api.post(`/treasury/bank-accounts/${body.bankId}/statements`, { lines: body.lines }),
    onSuccess: (_r, vars) => {
      qc.invalidateQueries({ queryKey: ["kasbon"] });
      setLinesByBank((prev) => ({ ...prev, [vars.bankId]: [] }));
      setNotice("Statement imported. Run auto-match next.");
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  const autoMatch = useMutation({
    mutationFn: (bankId: string) =>
      api.post<{ matched_count: number }>(`/treasury/bank-accounts/${bankId}/auto-match`),
    onSuccess: (r) => {
      setNotice(`Auto-match complete — ${r.matched_count} statement line(s) matched to payments.`);
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  const bankLines = selectedBank ? linesByBank[selectedBank] ?? [] : [];

  const addLine = () => {
    if (!date || !amount) return;
    setLinesByBank((prev) => ({
      ...prev,
      [selectedBank]: [...(prev[selectedBank] ?? []), { statement_date: date, description: desc, amount }],
    }));
    setDate("");
    setDesc("");
    setAmount("");
  };

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-medium flex items-center gap-2">
        <SearchCheck className="w-4 h-4" /> Bank reconciliation
      </h2>

      <Card className="p-5 space-y-3">
        <select
          className={cn(inputCls, "w-80")}
          value={selectedBank}
          onChange={(e) => setSelectedBank(e.target.value)}
        >
          <option value="">Select bank account…</option>
          {banks.data?.map((b) => (
            <option key={b.id} value={b.id}>
              {b.bank_name} — {b.account_number}
            </option>
          ))}
        </select>

        {selectedBank && (
          <>
            <div className="grid grid-cols-[1fr_2fr_1fr_auto] gap-3 items-center">
              <input className={inputCls} type="date" value={date} onChange={(e) => setDate(e.target.value)} />
              <input className={inputCls} placeholder="Description (optional)" value={desc} onChange={(e) => setDesc(e.target.value)} />
              <input className={inputCls} placeholder="Amount (e.g. 88800 / -999999)" value={amount} onChange={(e) => setAmount(e.target.value)} />
              <Button size="sm" variant="outline" onClick={addLine} disabled={!date || !amount}>
                <Plus className="w-4 h-4" /> Add line
              </Button>
            </div>
            {bankLines.length > 0 && (
              <Card className="divide-y">
                {bankLines.map((ln, i) => (
                  <div key={i} className="p-2.5 flex items-center gap-3 text-xs">
                    <span>{ln.statement_date}</span>
                    <span className="text-muted-foreground">{ln.description || "—"}</span>
                    <span className={cn("ml-auto font-medium", ln.amount.startsWith("-") ? "text-destructive" : "")}>
                      {formatAmount(ln.amount)}
                    </span>
                    <button
                      className="text-muted-foreground hover:text-foreground"
                      onClick={() =>
                        setLinesByBank((prev) => ({
                          ...prev,
                          [selectedBank]: (prev[selectedBank] ?? []).filter((_, j) => j !== i),
                        }))
                      }
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </Card>
            )}
            <div className="flex gap-2 justify-end">
              <Button
                variant="outline"
                disabled={bankLines.length === 0 || importStmt.isPending}
                onClick={() => importStmt.mutate({ bankId: selectedBank, lines: bankLines })}
              >
                {importStmt.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
                Import statement
              </Button>
              <Button
                disabled={autoMatch.isPending}
                onClick={() => autoMatch.mutate(selectedBank)}
              >
                {autoMatch.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
                <SearchCheck className="w-4 h-4" /> Run auto-match
              </Button>
            </div>
          </>
        )}
        {error && <p className="text-xs text-destructive">{error}</p>}
        {notice && <p className="text-xs text-success">{notice}</p>}
      </Card>
    </div>
  );
}

/* ----------------------------- forecast tab ------------------------------ */

function ForecastPanel() {
  const [weeks, setWeeks] = useState("4");
  const forecast = useQuery({
    queryKey: ["cash-forecast", weeks],
    queryFn: () => api.get<ForecastRow[]>(`/treasury/forecast?weeks_ahead=${weeks}`),
  });

  const grouped = new Map<string, ForecastRow[]>();
  for (const row of forecast.data ?? []) {
    const list = grouped.get(row.week_start) ?? [];
    list.push(row);
    grouped.set(row.week_start, list);
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-medium flex items-center gap-2">
          <ArrowUpRight className="w-4 h-4" /> Cash flow forecast
        </h2>
        <div className="flex items-center gap-2">
          <input
            className={cn(inputCls, "w-24")}
            value={weeks}
            onChange={(e) => setWeeks(e.target.value)}
            aria-label="Weeks ahead"
          />
          <span className="text-xs text-muted-foreground">weeks ahead</span>
        </div>
      </div>

      <Card className="divide-y">
        {forecast.isLoading ? (
          <div className="p-6 text-sm text-muted-foreground">Loading…</div>
        ) : grouped.size === 0 ? (
          <div className="p-6 text-sm text-muted-foreground">
            No forecast rows — no invoices, bills, or kasbon due within this window.
          </div>
        ) : (
          [...grouped.entries()].map(([week, rows]) => {
            const inflow = rows
              .filter((r) => r.category === "INFLOW")
              .reduce((a, r) => a + Number(r.estimated_amount), 0);
            const outflow = rows
              .filter((r) => r.category === "OUTFLOW")
              .reduce((a, r) => a + Number(r.estimated_amount), 0);
            return (
              <div key={week} className="p-4 space-y-2">
                <div className="flex items-center gap-3 text-sm">
                  <span className="font-medium">Week of {week}</span>
                  <Badge variant="success">
                    <ArrowDownLeft className="w-3 h-3" /> in {formatAmount(String(inflow))}
                  </Badge>
                  <Badge variant="warning">
                    <ArrowUpRight className="w-3 h-3" /> out {formatAmount(String(outflow))}
                  </Badge>
                  <span className="ml-auto text-muted-foreground">net {formatAmount(String(inflow - outflow))}</span>
                </div>
                {rows.map((r, i) => (
                  <div key={i} className="flex items-center gap-3 text-xs text-muted-foreground">
                    <span>{r.category === "INFLOW" ? "↘" : "↗"}</span>
                    <span>{r.source_type}</span>
                    <span className="ml-auto">{formatAmount(r.estimated_amount)}</span>
                  </div>
                ))}
              </div>
            );
          })
        )}
      </Card>
    </div>
  );
}

/* -------------------------------- page ----------------------------------- */

export function TreasuryPage() {
  const [tab, setTab] = useState<Tab>("kasbon");

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-medium">Treasury</h1>
          <p className="text-sm text-muted-foreground">
            Kasbon lifecycle, bank master, reconciliation, and cash flow forecast.
          </p>
        </div>
      </div>

      <div className="flex gap-1 border-b border-border">
        {(["kasbon", "banks", "recon", "forecast"] as Tab[]).map((t) => (
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

      {tab === "kasbon" && <KasbonPanel />}
      {tab === "banks" && <BanksPanel />}
      {tab === "recon" && <ReconPanel />}
      {tab === "forecast" && <ForecastPanel />}
    </div>
  );
}
