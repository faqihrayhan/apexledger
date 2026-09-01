/**
 * Fixed Assets (M7) — asset registration with auto-posted
 * acquisition JE, monthly depreciation batch, per-asset
 * schedule drill-down, and disposal with gain/loss posting.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { Badge, Button, Card } from "@/components/ui";
import { cn } from "@/lib/utils";
import {
  Calculator,
  Loader2,
  Package,
  Plus,
  Recycle,
  TrendingDown,
} from "lucide-react";

/* --------------------------------- types --------------------------------- */

interface Asset {
  id: string;
  asset_code: string;
  asset_name: string;
  asset_category: "TANGIBLE" | "INTANGIBLE";
  acquisition_date: string;
  acquisition_cost: string;
  salvage_value: string;
  accumulated_depreciation: string;
  book_value: string;
  status: string;
}

interface ScheduleRow {
  period_year: number;
  period_month: number;
  depreciation_amount: string;
  accumulated_after: string;
  book_value_after: string;
  journal_entry_id: string | null;
}

interface GlAccount {
  id: string;
  account_code: string;
  account_name: string;
}

type Tab = "assets" | "depreciation" | "disposals";

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

function statusVariant(status: string): "default" | "success" | "destructive" | "warning" | "outline" {
  if (status === "ACTIVE") return "success";
  if (status === "DISPOSED") return "destructive";
  if (status === "FULLY_DEPRECIATED") return "warning";
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

const emptyAssetForm = {
  asset_name: "",
  asset_category: "TANGIBLE",
  acquisition_date: "",
  acquisition_cost: "",
  salvage_value: "0",
  useful_life_months: "",
  depreciation_method: "STRAIGHT_LINE",
  declining_rate_pct: "",
  gl_asset_account_id: "",
  gl_accum_depr_account_id: "",
  funding_account_id: "",
};

/* ------------------------------- assets tab ------------------------------ */

function AssetsPanel() {
  const qc = useQueryClient();
  const [showNew, setShowNew] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [scheduleFor, setScheduleFor] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [form, setForm] = useState(emptyAssetForm);

  const assets = useQuery({
    queryKey: ["assets", statusFilter],
    queryFn: () =>
      api.get<Asset[]>(statusFilter ? `/assets?status=${statusFilter}` : "/assets"),
  });

  const accounts = useQuery({
    queryKey: ["gl-accounts"],
    queryFn: () => api.get<GlAccount[]>("/gl/accounts"),
  });

  const schedule = useQuery({
    queryKey: ["asset-schedule", scheduleFor],
    queryFn: () => api.get<ScheduleRow[]>(`/assets/${scheduleFor}/schedule`),
    enabled: scheduleFor !== null,
  });

  const register = useMutation({
    mutationFn: () =>
      api.post<{ asset_id: string; asset_code: string; journal_entry_id: string }>(
        "/assets",
        {
          asset_name: form.asset_name,
          asset_category: form.asset_category,
          acquisition_date: form.acquisition_date,
          acquisition_cost: form.acquisition_cost,
          salvage_value: form.salvage_value || "0",
          useful_life_months: Number(form.useful_life_months),
          depreciation_method: form.depreciation_method,
          declining_rate_pct:
            form.depreciation_method === "DECLINING_BALANCE"
              ? form.declining_rate_pct || null
              : null,
          gl_asset_account_id: form.gl_asset_account_id,
          gl_accum_depr_account_id: form.gl_accum_depr_account_id,
          funding_account_id: form.funding_account_id,
        },
      ),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["assets"] });
      setShowNew(false);
      setForm(emptyAssetForm);
      setNotice(`Asset ${r.asset_code} registered — acquisition JE posted.`);
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  const set = (k: keyof typeof emptyAssetForm) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm({ ...form, [k]: e.target.value });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-medium flex items-center gap-2">
          <Package className="w-4 h-4" /> Assets ({assets.data?.length ?? 0})
        </h2>
        <div className="flex items-center gap-2">
          <select
            className={cn(inputCls, "w-44")}
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="">All statuses</option>
            <option value="ACTIVE">ACTIVE</option>
            <option value="FULLY_DEPRECIATED">FULLY DEPRECIATED</option>
            <option value="DISPOSED">DISPOSED</option>
          </select>
          <Button size="sm" onClick={() => { setShowNew(!showNew); setError(null); }}>
            <Plus className="w-4 h-4" /> Register
          </Button>
        </div>
      </div>

      {showNew && (
        <Card className="p-5 space-y-3">
          <h3 className="text-sm font-medium">Register asset</h3>
          <div className="grid grid-cols-3 gap-3">
            <input className={inputCls} placeholder="Asset name" value={form.asset_name} onChange={set("asset_name")} />
            <select className={inputCls} value={form.asset_category} onChange={set("asset_category")}>
              <option value="TANGIBLE">TANGIBLE</option>
              <option value="INTANGIBLE">INTANGIBLE</option>
            </select>
            <input className={inputCls} type="date" value={form.acquisition_date} onChange={set("acquisition_date")} />
            <input className={inputCls} placeholder="Acquisition cost" value={form.acquisition_cost} onChange={set("acquisition_cost")} />
            <input className={inputCls} placeholder="Salvage value (default 0)" value={form.salvage_value} onChange={set("salvage_value")} />
            <input className={inputCls} placeholder="Useful life (months)" value={form.useful_life_months} onChange={set("useful_life_months")} />
            <select className={inputCls} value={form.depreciation_method} onChange={set("depreciation_method")}>
              <option value="STRAIGHT_LINE">STRAIGHT LINE</option>
              <option value="DECLINING_BALANCE">DECLINING BALANCE</option>
            </select>
            {form.depreciation_method === "DECLINING_BALANCE" && (
              <input className={inputCls} placeholder="Declining rate % (e.g. 40)" value={form.declining_rate_pct} onChange={set("declining_rate_pct")} />
            )}
          </div>
          <div className="flex flex-wrap gap-3">
            <AccountPicker accounts={accounts.data} value={form.gl_asset_account_id} onChange={(v) => setForm({ ...form, gl_asset_account_id: v })} placeholder="GL asset account…" className="w-72" />
            <AccountPicker accounts={accounts.data} value={form.gl_accum_depr_account_id} onChange={(v) => setForm({ ...form, gl_accum_depr_account_id: v })} placeholder="Accumulated depreciation account…" className="w-72" />
            <AccountPicker accounts={accounts.data} value={form.funding_account_id} onChange={(v) => setForm({ ...form, funding_account_id: v })} placeholder="Funding source (AP/cash/bank)…" className="w-72" />
          </div>
          {error && <p className="text-xs text-destructive">{error}</p>}
          <div className="flex justify-end">
            <Button
              onClick={() => register.mutate()}
              disabled={
                register.isPending ||
                !form.asset_name ||
                !form.acquisition_date ||
                !form.acquisition_cost ||
                !form.useful_life_months ||
                !form.gl_asset_account_id ||
                !form.gl_accum_depr_account_id ||
                !form.funding_account_id
              }
            >
              {register.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
              Register &amp; post acquisition
            </Button>
          </div>
        </Card>
      )}

      {notice && <p className="text-xs text-success">{notice}</p>}

      <Card className="divide-y">
        {assets.isLoading ? (
          <div className="p-6 text-sm text-muted-foreground">Loading…</div>
        ) : assets.data?.length === 0 ? (
          <div className="p-6 text-sm text-muted-foreground">No assets registered yet.</div>
        ) : (
          assets.data?.map((a) => (
            <div key={a.id} className="p-4 flex flex-wrap items-center gap-3 text-sm">
              <Package className="w-4 h-4 text-muted-foreground" />
              <span className="font-mono text-xs text-muted-foreground">{a.asset_code}</span>
              <span className="font-medium">{a.asset_name}</span>
              <Badge variant="outline">{a.asset_category}</Badge>
              <span className="text-xs text-muted-foreground">acq {formatAmount(a.acquisition_cost)}</span>
              <span className="text-xs text-muted-foreground">depr {formatAmount(a.accumulated_depreciation)}</span>
              <span className="text-xs font-medium">book {formatAmount(a.book_value)}</span>
              <Badge variant={statusVariant(a.status)}>{a.status}</Badge>
              <div className="ml-auto flex gap-2">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setScheduleFor(scheduleFor === a.id ? null : a.id)}
                >
                  Schedule
                </Button>
              </div>
            </div>
          ))
        )}
      </Card>

      {scheduleFor && (
        <Card className="divide-y">
          <div className="p-4 text-sm font-medium flex items-center gap-2">
            <TrendingDown className="w-4 h-4" /> Depreciation schedule
          </div>
          {schedule.isLoading ? (
            <div className="p-4 text-sm text-muted-foreground">Loading…</div>
          ) : schedule.data?.length === 0 ? (
            <div className="p-4 text-sm text-muted-foreground">No depreciation posted for this asset yet.</div>
          ) : (
            schedule.data?.map((s, i) => (
              <div key={i} className="p-3 flex items-center gap-3 text-xs">
                <span className="w-20 font-medium">{MONTHS[s.period_month - 1]} {s.period_year}</span>
                <span>depr {formatAmount(s.depreciation_amount)}</span>
                <span className="text-muted-foreground">accum {formatAmount(s.accumulated_after)}</span>
                <span className="ml-auto">book {formatAmount(s.book_value_after)}</span>
              </div>
            ))
          )}
        </Card>
      )}
    </div>
  );
}

/* --------------------------- depreciation tab ---------------------------- */

function DepreciationPanel() {
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [form, setForm] = useState({
    period_year: String(new Date().getFullYear()),
    period_month: String(new Date().getMonth()),
  });

  const run = useMutation({
    mutationFn: () =>
      api.post<{ asset_count: number; total_depreciation: string; journal_entry_id: string | null; note: string | null }>(
        "/assets/depreciation/batch",
        {
          period_year: Number(form.period_year),
          period_month: Number(form.period_month),
        },
      ),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["assets"] });
      qc.invalidateQueries({ queryKey: ["asset-schedule"] });
      setNotice(
        `Batch done — ${r.asset_count} asset(s), total ${formatAmount(r.total_depreciation)}` +
          (r.journal_entry_id ? ", journal posted." : `. ${r.note ?? ""}`),
      );
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-medium flex items-center gap-2">
        <Calculator className="w-4 h-4" /> Monthly depreciation batch
      </h2>

      <Card className="p-5 space-y-3">
        <p className="text-xs text-muted-foreground">
          Posts one aggregated depreciation journal per run for the whole entity.
          Re-running the same period is rejected (PERIOD_ALREADY_PROCESSED).
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

/* ----------------------------- disposals tab ----------------------------- */

function DisposalsPanel() {
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [disposeFor, setDisposeFor] = useState<string | null>(null);
  const [form, setForm] = useState({
    disposal_date: "",
    disposal_type: "WRITE_OFF",
    disposal_proceeds: "0",
    proceeds_account_id: "",
    gain_loss_account_id: "",
  });

  const assets = useQuery({
    queryKey: ["assets", ""],
    queryFn: () => api.get<Asset[]>("/assets"),
  });

  const accounts = useQuery({
    queryKey: ["gl-accounts"],
    queryFn: () => api.get<GlAccount[]>("/gl/accounts"),
  });

  const dispose = useMutation({
    mutationFn: (assetId: string) =>
      api.post<{ disposal_id: string; gain_loss: string; journal_entry_id: string }>(
        `/assets/${assetId}/dispose`,
        {
          disposal_date: form.disposal_date,
          disposal_type: form.disposal_type,
          disposal_proceeds: form.disposal_proceeds || "0",
          proceeds_account_id: form.proceeds_account_id,
          gain_loss_account_id: form.gain_loss_account_id,
        },
      ),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["assets"] });
      setDisposeFor(null);
      setForm({
        disposal_date: "",
        disposal_type: "WRITE_OFF",
        disposal_proceeds: "0",
        proceeds_account_id: "",
        gain_loss_account_id: "",
      });
      setNotice(
        `Disposed — gain/loss ${formatAmount(r.gain_loss)}, journal posted.`,
      );
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  const activeAssets = assets.data?.filter((a) => a.status !== "DISPOSED") ?? [];

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-medium flex items-center gap-2">
        <Recycle className="w-4 h-4" /> Disposals
      </h2>

      <Card className="p-5 space-y-3">
        <select
          className={cn(inputCls, "w-80")}
          value={disposeFor ?? ""}
          onChange={(e) => { setDisposeFor(e.target.value || null); setError(null); }}
        >
          <option value="">Select asset to dispose…</option>
          {activeAssets.map((a) => (
            <option key={a.id} value={a.id}>
              {a.asset_code} — {a.asset_name} (book {formatAmount(a.book_value)})
            </option>
          ))}
        </select>

        {disposeFor && (
          <>
            <div className="flex flex-wrap gap-3">
              <input
                className={cn(inputCls, "w-36")}
                type="date"
                value={form.disposal_date}
                onChange={(e) => setForm({ ...form, disposal_date: e.target.value })}
              />
              <select
                className={cn(inputCls, "w-40")}
                value={form.disposal_type}
                onChange={(e) => setForm({ ...form, disposal_type: e.target.value })}
              >
                <option value="SALE">SALE</option>
                <option value="WRITE_OFF">WRITE OFF</option>
                <option value="DONATION">DONATION</option>
              </select>
              <input
                className={cn(inputCls, "w-44")}
                placeholder="Proceeds (default 0)"
                value={form.disposal_proceeds}
                onChange={(e) => setForm({ ...form, disposal_proceeds: e.target.value })}
              />
            </div>
            <div className="flex flex-wrap gap-3">
              <AccountPicker
                accounts={accounts.data}
                value={form.proceeds_account_id}
                onChange={(v) => setForm({ ...form, proceeds_account_id: v })}
                placeholder="Proceeds account (cash/bank)…"
                className="w-72"
              />
              <AccountPicker
                accounts={accounts.data}
                value={form.gain_loss_account_id}
                onChange={(v) => setForm({ ...form, gain_loss_account_id: v })}
                placeholder="Gain/loss account…"
                className="w-72"
              />
            </div>
            {error && <p className="text-xs text-destructive">{error}</p>}
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setDisposeFor(null)}>Cancel</Button>
              <Button
                onClick={() => dispose.mutate(disposeFor)}
                disabled={
                  dispose.isPending ||
                  !form.disposal_date ||
                  !form.proceeds_account_id ||
                  !form.gain_loss_account_id
                }
              >
                {dispose.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
                Dispose &amp; post journal
              </Button>
            </div>
          </>
        )}
        {notice && <p className="text-xs text-success">{notice}</p>}
      </Card>
    </div>
  );
}

/* -------------------------------- page ----------------------------------- */

export function FixedAssetPage() {
  const [tab, setTab] = useState<Tab>("assets");

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-medium">Fixed Assets</h1>
          <p className="text-sm text-muted-foreground">
            Register, depreciate, and dispose fixed assets — GL posts automated.
          </p>
        </div>
      </div>

      <div className="flex gap-1 border-b border-border">
        {(["assets", "depreciation", "disposals"] as Tab[]).map((t) => (
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

      {tab === "assets" && <AssetsPanel />}
      {tab === "depreciation" && <DepreciationPanel />}
      {tab === "disposals" && <DisposalsPanel />}
    </div>
  );
}
