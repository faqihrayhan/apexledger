/**
 * Sales & AR (M4) — sales orders (create -> confirm -> deliver ->
 * invoice), customers, AR payments, POS fast path with batch GL
 * posting, and sales returns approval.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { Badge, Button, Card } from "@/components/ui";
import { cn } from "@/lib/utils";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  FileText,
  Loader2,
  Plus,
  Receipt,
  ShoppingCart,
  Store,
  Truck,
  Undo2,
  Users,
  X,
} from "lucide-react";

/* --------------------------------- types --------------------------------- */

interface Customer {
  id: string;
  customer_code: string;
  customer_name: string;
  credit_limit: string;
  payment_term_days: number;
  npwp: string | null;
  is_active: boolean;
}

interface Warehouse {
  id: string;
  code: string;
  name: string;
}

interface InvItem {
  id: string;
  item_code: string;
  item_name: string;
}

interface SoLine {
  id: string;
  item_id: string;
  qty_ordered: string;
  qty_delivered: string;
  unit_price: string;
  line_total: string;
}

interface SalesOrder {
  id: string;
  so_number: string;
  customer_id: string;
  warehouse_id: string;
  order_date: string;
  status: string;
  total_amount: string;
  lines: SoLine[];
}

interface Invoice {
  id: string;
  invoice_number: string;
  customer_id: string;
  status: string;
  subtotal: string;
  tax_amount: string;
  total_amount: string;
  paid_amount: string;
  due_date: string;
}

interface SalesReturn {
  id: string;
  return_number: string;
  status: string;
  total_amount: string;
}

interface GlAccount {
  id: string;
  account_code: string;
  account_name: string;
}

interface GlDefaults {
  configured: boolean;
  gl_ar_account_id?: string;
  gl_sales_revenue_account_id?: string;
  gl_ppn_keluaran_account_id?: string;
  gl_kas_bank_default_account_id?: string;
}

interface SessionDo {
  id: string;
  do_number: string;
  so_number: string;
}

type Line = { item_id: string; qty: string; unit_price: string };
type Tab = "orders" | "customers" | "invoices" | "pos" | "returns";

const inputCls =
  "h-9 rounded-md border border-input bg-transparent px-3 text-sm outline-none focus:ring-1 focus:ring-ring";

/* ------------------------------- formatting ------------------------------- */

function formatAmount(value: string): string {
  const [intPart = "0", decPart = "00"] = value.split(".");
  const grouped = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const dec = (decPart + "00").slice(0, 2);
  return `${grouped}.${dec}`;
}

function fmtQty(value: string): string {
  const [intPart = "0", decPart] = value.split(".");
  if (!decPart || Number(decPart) === 0) return intPart;
  return value;
}

function soStatusVariant(status: string) {
  switch (status) {
    case "DELIVERED":
      return "success" as const;
    case "CONFIRMED":
      return "outline" as const;
    case "PARTIALLY_DELIVERED":
      return "warning" as const;
    case "CANCELLED":
      return "destructive" as const;
    default:
      return "default" as const;
  }
}

/* ------------------------------ shared queries ---------------------------- */

function useSalesMaster() {
  const customers = useQuery({
    queryKey: ["sales-customers"],
    queryFn: () => api.get<Customer[]>("/sales/customers"),
  });
  const warehouses = useQuery({
    queryKey: ["inv-warehouses"],
    queryFn: () => api.get<Warehouse[]>("/inv/warehouses"),
  });
  const items = useQuery({
    queryKey: ["inv-items"],
    queryFn: () => api.get<InvItem[]>("/inv/items"),
  });
  return { customers, warehouses, items };
}

function LineEditor({
  lines,
  setLines,
  items,
}: {
  lines: Line[];
  setLines: (l: Line[]) => void;
  items: InvItem[];
}) {
  const update = (idx: number, patch: Partial<Line>) =>
    setLines(lines.map((l, i) => (i === idx ? { ...l, ...patch } : l)));

  const total = lines.reduce(
    (acc, l) => acc + (Number(l.qty) || 0) * (Number(l.unit_price) || 0),
    0,
  );

  return (
    <div className="space-y-2">
      {lines.map((l, idx) => (
        <div key={idx} className="flex gap-2 items-center">
          <select
            className={cn(inputCls, "flex-1")}
            value={l.item_id}
            onChange={(e) => update(idx, { item_id: e.target.value })}
          >
            <option value="">Select item…</option>
            {items.map((i) => (
              <option key={i.id} value={i.id}>
                {i.item_code} — {i.item_name}
              </option>
            ))}
          </select>
          <input
            className={cn(inputCls, "w-24")}
            placeholder="Qty"
            value={l.qty}
            onChange={(e) => update(idx, { qty: e.target.value })}
          />
          <input
            className={cn(inputCls, "w-32")}
            placeholder="Unit price"
            value={l.unit_price}
            onChange={(e) => update(idx, { unit_price: e.target.value })}
          />
          <span className="w-28 text-right text-sm text-muted-foreground">
            {((Number(l.qty) || 0) * (Number(l.unit_price) || 0)).toLocaleString()}
          </span>
          <button
            className="text-muted-foreground hover:text-destructive"
            onClick={() => setLines(lines.filter((_, i) => i !== idx))}
            aria-label="Remove line"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      ))}
      <div className="flex items-center justify-between">
        <Button
          size="sm"
          variant="outline"
          onClick={() => setLines([...lines, { item_id: "", qty: "", unit_price: "" }])}
        >
          <Plus className="w-4 h-4" /> Line
        </Button>
        <span className="text-sm">
          Total <span className="font-medium">{total.toLocaleString()}</span>
        </span>
      </div>
    </div>
  );
}

/* ------------------------------ orders panel ------------------------------ */

function CreateSoForm({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient();
  const { customers, warehouses, items } = useSalesMaster();
  const [error, setError] = useState<string | null>(null);
  const [lines, setLines] = useState<Line[]>([
    { item_id: "", qty: "", unit_price: "" },
  ]);
  const [form, setForm] = useState({
    so_number: "",
    customer_id: "",
    warehouse_id: "",
    order_date: new Date().toISOString().slice(0, 10),
  });

  const create = useMutation({
    mutationFn: () =>
      api.post("/sales/orders", {
        so_number: form.so_number,
        customer_id: form.customer_id,
        warehouse_id: form.warehouse_id,
        order_date: form.order_date,
        lines: lines
          .filter((l) => l.item_id && l.qty && l.unit_price)
          .map((l) => ({
            item_id: l.item_id,
            qty_ordered: l.qty,
            unit_price: l.unit_price,
          })),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sales-orders"] });
      onDone();
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  return (
    <Card className="p-5 space-y-3">
      <h3 className="text-sm font-medium">New sales order</h3>
      <div className="grid grid-cols-4 gap-3">
        <input
          className={inputCls}
          placeholder="SO number (e.g. SO-2026-001)"
          value={form.so_number}
          onChange={(e) => setForm({ ...form, so_number: e.target.value })}
        />
        <select
          className={inputCls}
          value={form.customer_id}
          onChange={(e) => setForm({ ...form, customer_id: e.target.value })}
        >
          <option value="">Customer…</option>
          {customers.data?.map((c) => (
            <option key={c.id} value={c.id}>
              {c.customer_code} — {c.customer_name}
            </option>
          ))}
        </select>
        <select
          className={inputCls}
          value={form.warehouse_id}
          onChange={(e) => setForm({ ...form, warehouse_id: e.target.value })}
        >
          <option value="">Warehouse…</option>
          {warehouses.data?.map((w) => (
            <option key={w.id} value={w.id}>
              {w.code} — {w.name}
            </option>
          ))}
        </select>
        <input
          className={inputCls}
          type="date"
          value={form.order_date}
          onChange={(e) => setForm({ ...form, order_date: e.target.value })}
        />
      </div>
      <LineEditor lines={lines} setLines={setLines} items={items.data ?? []} />
      {error && <p className="text-xs text-destructive">{error}</p>}
      <div className="flex gap-2 justify-end">
        <Button variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        <Button
          disabled={
            create.isPending ||
            !form.so_number ||
            !form.customer_id ||
            !form.warehouse_id ||
            !lines.some((l) => l.item_id && l.qty && l.unit_price)
          }
          onClick={() => create.mutate()}
        >
          {create.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
          Create
        </Button>
      </div>
    </Card>
  );
}

function DoForm({
  so,
  onCreated,
}: {
  so: SalesOrder;
  onCreated: (d: SessionDo) => void;
}) {
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [deliveryDate, setDeliveryDate] = useState(
    new Date().toISOString().slice(0, 10),
  );
  const [qtys, setQtys] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      so.lines.map((l) => [
        l.id,
        String(Number(l.qty_ordered) - Number(l.qty_delivered)),
      ]),
    ),
  );

  const deliver = useMutation({
    mutationFn: () =>
      api.post<{
        delivery_order_id: string;
        do_number: string;
        so_status: string;
      }>(`/sales/orders/${so.id}/delivery-orders`, {
        delivery_date: deliveryDate,
        lines: so.lines
          .filter((l) => Number(qtys[l.id] ?? "0") > 0)
          .map((l) => ({
            sales_order_line_id: l.id,
            qty_delivered: qtys[l.id],
          })),
      }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["sales-orders"] });
      onCreated({
        id: r.delivery_order_id,
        do_number: r.do_number,
        so_number: so.so_number,
      });
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  return (
    <div className="space-y-3 rounded-md border border-border p-4">
      <div className="flex items-center gap-3">
        <Truck className="w-4 h-4 text-muted-foreground" />
        <span className="text-sm font-medium">Create delivery order</span>
        <input
          className={cn(inputCls, "w-36")}
          type="date"
          value={deliveryDate}
          onChange={(e) => setDeliveryDate(e.target.value)}
        />
        <Button
          size="sm"
          disabled={
            deliver.isPending ||
            !so.lines.some((l) => Number(qtys[l.id] ?? "0") > 0)
          }
          onClick={() => deliver.mutate()}
        >
          {deliver.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
          Deliver
        </Button>
      </div>
      <div className="space-y-2">
        {so.lines.map((l) => {
          const remaining =
            Number(l.qty_ordered) - Number(l.qty_delivered);
          return (
            <div key={l.id} className="flex items-center gap-3 text-sm">
              <span className="text-muted-foreground w-20">
                {l.item_id.slice(0, 8)}…
              </span>
              <span className="text-muted-foreground">
                ordered {fmtQty(l.qty_ordered)}, delivered{" "}
                {fmtQty(l.qty_delivered)}
              </span>
              {remaining > 0 && (
                <input
                  className={cn(inputCls, "w-24")}
                  value={qtys[l.id] ?? ""}
                  onChange={(e) =>
                    setQtys({ ...qtys, [l.id]: e.target.value })
                  }
                  placeholder="Qty now"
                />
              )}
            </div>
          );
        })}
      </div>
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}

function InvoiceDoPanel({
  d,
  onDone,
}: {
  d: SessionDo;
  onDone: () => void;
}) {
  const qc = useQueryClient();
  const [taxRate, setTaxRate] = useState("11");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);

  const invoice = useMutation({
    mutationFn: () =>
      api.post<{
        invoice_id: string;
        invoice_number: string;
        total_amount: string;
        cogs: string;
      }>(`/sales/delivery-orders/${d.id}/invoice`, {
        tax_rate_pct: taxRate,
      }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["sales-invoices"] });
      setResult(
        `${r.invoice_number} — total ${formatAmount(r.total_amount)} (COGS ${formatAmount(r.cogs)})`,
      );
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  if (result) {
    return (
      <p className="text-xs text-primary">
        Invoice issued: {result}
      </p>
    );
  }

  return (
    <div className="flex items-center gap-3">
      <span className="text-sm">
        Invoice {d.do_number} (from {d.so_number})
      </span>
      <input
        className={cn(inputCls, "w-20")}
        title="Tax rate %"
        value={taxRate}
        onChange={(e) => setTaxRate(e.target.value)}
      />
      <Button
        size="sm"
        disabled={invoice.isPending}
        onClick={() => invoice.mutate()}
      >
        {invoice.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
        <FileText className="w-4 h-4" /> Issue invoice
      </Button>
      <Button size="sm" variant="ghost" onClick={onDone}>
        Cancel
      </Button>
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}

function OrdersPanel() {
  const { customers } = useSalesMaster();
  const [showForm, setShowForm] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [sessionDos, setSessionDos] = useState<SessionDo[]>([]);
  const [invoiceFor, setInvoiceFor] = useState<SessionDo | null>(null);

  const orders = useQuery({
    queryKey: ["sales-orders"],
    queryFn: () => api.get<SalesOrder[]>("/sales/orders"),
  });

  const confirm = useMutation({
    mutationFn: (soId: string) =>
      api.post(`/sales/orders/${soId}/confirm`),
    onSuccess: () => {
      setConfirmError(null);
    },
    onError: (e: ApiError) => setConfirmError(e.uiMessage),
  });

  const customerName = (id: string) =>
    customers.data?.find((c) => c.id === id)?.customer_name ?? "—";

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-medium flex items-center gap-2">
          <ShoppingCart className="w-4 h-4" /> Sales orders (
          {orders.data?.length ?? 0})
        </h2>
        <Button size="sm" onClick={() => setShowForm(!showForm)}>
          <Plus className="w-4 h-4" /> New order
        </Button>
      </div>

      {showForm && <CreateSoForm onDone={() => setShowForm(false)} />}
      {confirmError && <p className="text-xs text-destructive">{confirmError}</p>}

      <Card className="divide-y">
        {orders.isLoading ? (
          <div className="p-6 text-sm text-muted-foreground">Loading…</div>
        ) : orders.data?.length === 0 ? (
          <div className="p-6 text-sm text-muted-foreground">
            No sales orders yet.
          </div>
        ) : (
          orders.data?.map((so) => {
            const isOpen = expanded === so.id;
            return (
              <div key={so.id}>
                <div className="p-4 flex flex-wrap items-center gap-3 text-sm">
                  <button
                    onClick={() => setExpanded(isOpen ? null : so.id)}
                    className="flex items-center gap-2"
                  >
                    {isOpen ? (
                      <ChevronDown className="w-4 h-4 text-muted-foreground" />
                    ) : (
                      <ChevronRight className="w-4 h-4 text-muted-foreground" />
                    )}
                    <span className="font-mono text-xs">{so.so_number}</span>
                  </button>
                  <span className="font-medium">{customerName(so.customer_id)}</span>
                  <Badge variant={soStatusVariant(so.status)}>{so.status}</Badge>
                  <span className="text-muted-foreground">{so.order_date}</span>
                  <span className="ml-auto font-medium">
                    {formatAmount(so.total_amount)}
                  </span>
                  {so.status === "DRAFT" && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => confirm.mutate(so.id)}
                      disabled={confirm.isPending}
                    >
                      <CheckCircle2 className="w-4 h-4" /> Confirm
                    </Button>
                  )}
                </div>
                {isOpen && (
                  <div className="px-8 pb-4 space-y-3">
                    {so.lines.map((l) => (
                      <div
                        key={l.id}
                        className="flex flex-wrap items-center gap-3 text-sm"
                      >
                        <span className="text-muted-foreground w-16">
                          {l.item_id.slice(0, 8)}…
                        </span>
                        <span>
                          {fmtQty(l.qty_ordered)} @ {formatAmount(l.unit_price)}
                        </span>
                        <span className="ml-auto text-muted-foreground">
                          {formatAmount(l.line_total)}
                        </span>
                      </div>
                    ))}
                    {(so.status === "CONFIRMED" ||
                      so.status === "PARTIALLY_DELIVERED") && (
                      <DoForm
                        so={so}
                        onCreated={(d) => {
                          setSessionDos((prev) => [...prev, d]);
                          setInvoiceFor(d);
                        }}
                      />
                    )}
                  </div>
                )}
              </div>
            );
          })
        )}
      </Card>

      {sessionDos.length > 0 && (
        <Card className="divide-y">
          <div className="p-4 text-sm font-medium">
            Delivery orders this session
          </div>
          {sessionDos.map((d) => (
            <div key={d.id} className="p-4 flex items-center gap-3 text-sm">
              <span className="font-mono text-xs">{d.do_number}</span>
              <span className="text-muted-foreground">from {d.so_number}</span>
              {invoiceFor?.id === d.id ? (
                <InvoiceDoPanel d={d} onDone={() => setInvoiceFor(null)} />
              ) : (
                <Button
                  size="sm"
                  variant="outline"
                  className="ml-auto"
                  onClick={() => setInvoiceFor(d)}
                >
                  <FileText className="w-4 h-4" /> Invoice
                </Button>
              )}
            </div>
          ))}
        </Card>
      )}
    </div>
  );
}

/* ----------------------------- customers panel ---------------------------- */

function CustomersPanel() {
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    customer_code: "",
    customer_name: "",
    credit_limit: "0",
    payment_term_days: "30",
    npwp: "",
  });

  const customers = useQuery({
    queryKey: ["sales-customers"],
    queryFn: () => api.get<Customer[]>("/sales/customers"),
  });

  const create = useMutation({
    mutationFn: () =>
      api.post("/sales/customers", {
        customer_code: form.customer_code,
        customer_name: form.customer_name,
        credit_limit: form.credit_limit,
        payment_term_days: Number(form.payment_term_days),
        npwp: form.npwp || null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sales-customers"] });
      setShowForm(false);
      setForm({
        customer_code: "",
        customer_name: "",
        credit_limit: "0",
        payment_term_days: "30",
        npwp: "",
      });
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-medium flex items-center gap-2">
          <Users className="w-4 h-4" /> Customers (
          {customers.data?.length ?? 0})
        </h2>
        <Button size="sm" onClick={() => setShowForm(!showForm)}>
          <Plus className="w-4 h-4" /> Add
        </Button>
      </div>

      {showForm && (
        <Card className="p-5 space-y-3">
          <h3 className="text-sm font-medium">Add customer</h3>
          <div className="grid grid-cols-3 gap-3">
            <input
              className={inputCls}
              placeholder="Code (e.g. CUST-001)"
              value={form.customer_code}
              onChange={(e) =>
                setForm({ ...form, customer_code: e.target.value })
              }
            />
            <input
              className={inputCls}
              placeholder="Name"
              value={form.customer_name}
              onChange={(e) =>
                setForm({ ...form, customer_name: e.target.value })
              }
            />
            <input
              className={inputCls}
              placeholder="Credit limit"
              value={form.credit_limit}
              onChange={(e) =>
                setForm({ ...form, credit_limit: e.target.value })
              }
            />
            <input
              className={inputCls}
              placeholder="Payment term (days)"
              value={form.payment_term_days}
              onChange={(e) =>
                setForm({ ...form, payment_term_days: e.target.value })
              }
            />
            <input
              className={inputCls}
              placeholder="NPWP (optional)"
              value={form.npwp}
              onChange={(e) => setForm({ ...form, npwp: e.target.value })}
            />
          </div>
          {error && <p className="text-xs text-destructive">{error}</p>}
          <div className="flex justify-end">
            <Button
              disabled={create.isPending || !form.customer_code || !form.customer_name}
              onClick={() => create.mutate()}
            >
              {create.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
              Save
            </Button>
          </div>
        </Card>
      )}

      <Card className="divide-y">
        {customers.isLoading ? (
          <div className="p-6 text-sm text-muted-foreground">Loading…</div>
        ) : customers.data?.length === 0 ? (
          <div className="p-6 text-sm text-muted-foreground">
            No customers yet.
          </div>
        ) : (
          customers.data?.map((c) => (
            <div
              key={c.id}
              className="p-4 flex flex-wrap items-center gap-3 text-sm"
            >
              <span className="font-mono text-xs text-muted-foreground">
                {c.customer_code}
              </span>
              <span className="font-medium">{c.customer_name}</span>
              <span className="text-muted-foreground">
                term {c.payment_term_days}d
              </span>
              {c.npwp && (
                <span className="text-muted-foreground">NPWP {c.npwp}</span>
              )}
              <span className="ml-auto font-medium">
                limit {formatAmount(c.credit_limit)}
              </span>
            </div>
          ))
        )}
      </Card>
    </div>
  );
}

/* ----------------------------- invoices panel ----------------------------- */

function GlDefaultsCard() {
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const accounts = useQuery({
    queryKey: ["gl-accounts"],
    queryFn: () => api.get<GlAccount[]>("/gl/accounts"),
  });
  const defaults = useQuery({
    queryKey: ["sales-gl-defaults"],
    queryFn: () => api.get<GlDefaults>("/sales/gl-defaults"),
  });

  const [form, setForm] = useState<Record<string, string>>({
    gl_ar_account_id: "",
    gl_sales_revenue_account_id: "",
    gl_ppn_keluaran_account_id: "",
    gl_kas_bank_default_account_id: "",
  });

  const save = useMutation({
    mutationFn: () => api.put("/sales/gl-defaults", form),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sales-gl-defaults"] });
      setSaved(true);
      setError(null);
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  const fields: Array<[string, string]> = [
    ["gl_ar_account_id", "AR (piutang)"],
    ["gl_sales_revenue_account_id", "Sales revenue"],
    ["gl_ppn_keluaran_account_id", "PPN keluaran"],
    ["gl_kas_bank_default_account_id", "Kas / bank"],
  ];

  return (
    <Card className="p-5 space-y-3">
      <h3 className="text-sm font-medium">Posting accounts (GL defaults)</h3>
      <p className="text-xs text-muted-foreground">
        Required before invoicing / payments can post to the GL.
        {!defaults.data?.configured && " Not configured yet."}
      </p>
      <div className="grid grid-cols-2 gap-3">
        {fields.map(([key, label]) => (
          <label key={key} className="space-y-1">
            <span className="text-xs text-muted-foreground">{label}</span>
            <select
              className={cn(inputCls, "w-full")}
              value={form[key]}
              onChange={(e) => setForm({ ...form, [key]: e.target.value })}
            >
              <option value="">Select account…</option>
              {accounts.data?.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.account_code} — {a.account_name}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>
      {error && <p className="text-xs text-destructive">{error}</p>}
      {saved && <p className="text-xs text-primary">Saved.</p>}
      <div className="flex justify-end">
        <Button
          size="sm"
          disabled={
            save.isPending ||
            Object.values(form).some((v) => v === "")
          }
          onClick={() => save.mutate()}
        >
          {save.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
          Save defaults
        </Button>
      </div>
    </Card>
  );
}

function PaymentForm() {
  const qc = useQueryClient();
  const { customers } = useSalesMaster();
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [form, setForm] = useState({
    customer_id: "",
    amount: "",
    payment_date: new Date().toISOString().slice(0, 10),
    payment_method: "BANK_TRANSFER",
  });

  const pay = useMutation({
    mutationFn: () =>
      api.post<{ payment_id: string; amount: string }>("/sales/payments", {
        customer_id: form.customer_id,
        amount: form.amount,
        payment_date: form.payment_date,
        payment_method: form.payment_method,
      }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["sales-invoices"] });
      setDone(`Payment ${formatAmount(r.amount)} recorded.`);
      setForm({ ...form, amount: "" });
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  return (
    <Card className="p-5 space-y-3">
      <h3 className="text-sm font-medium">Record AR payment</h3>
      <div className="grid grid-cols-4 gap-3">
        <select
          className={inputCls}
          value={form.customer_id}
          onChange={(e) => setForm({ ...form, customer_id: e.target.value })}
        >
          <option value="">Customer…</option>
          {customers.data?.map((c) => (
            <option key={c.id} value={c.id}>
              {c.customer_code} — {c.customer_name}
            </option>
          ))}
        </select>
        <input
          className={inputCls}
          placeholder="Amount"
          value={form.amount}
          onChange={(e) => setForm({ ...form, amount: e.target.value })}
        />
        <input
          className={inputCls}
          type="date"
          value={form.payment_date}
          onChange={(e) => setForm({ ...form, payment_date: e.target.value })}
        />
        <select
          className={inputCls}
          value={form.payment_method}
          onChange={(e) =>
            setForm({ ...form, payment_method: e.target.value })
          }
        >
          <option value="CASH">CASH</option>
          <option value="BANK_TRANSFER">BANK_TRANSFER</option>
          <option value="E_WALLET">E_WALLET</option>
        </select>
      </div>
      <p className="text-xs text-muted-foreground">
        Auto-allocates FIFO by due date across open invoices.
      </p>
      {error && <p className="text-xs text-destructive">{error}</p>}
      {done && <p className="text-xs text-primary">{done}</p>}
      <div className="flex justify-end">
        <Button
          size="sm"
          disabled={pay.isPending || !form.customer_id || !form.amount}
          onClick={() => pay.mutate()}
        >
          {pay.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
          Record payment
        </Button>
      </div>
    </Card>
  );
}

function InvoicesPanel() {
  const { customers } = useSalesMaster();
  const [outstandingOnly, setOutstandingOnly] = useState(false);

  const invoices = useQuery({
    queryKey: ["sales-invoices", outstandingOnly],
    queryFn: () =>
      api.get<Invoice[]>(
        outstandingOnly
          ? "/sales/invoices?outstanding_only=true"
          : "/sales/invoices",
      ),
  });

  const customerName = (id: string) =>
    customers.data?.find((c) => c.id === id)?.customer_name ?? "—";

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-medium flex items-center gap-2">
          <Receipt className="w-4 h-4" /> AR invoices (
          {invoices.data?.length ?? 0})
        </h2>
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <input
            type="checkbox"
            checked={outstandingOnly}
            onChange={(e) => setOutstandingOnly(e.target.checked)}
          />
          Outstanding only
        </label>
      </div>

      <PaymentForm />

      <Card className="divide-y">
        {invoices.isLoading ? (
          <div className="p-6 text-sm text-muted-foreground">Loading…</div>
        ) : invoices.data?.length === 0 ? (
          <div className="p-6 text-sm text-muted-foreground">
            No invoices yet.
          </div>
        ) : (
          invoices.data?.map((inv) => (
            <div
              key={inv.id}
              className="p-4 flex flex-wrap items-center gap-3 text-sm"
            >
              <span className="font-mono text-xs">{inv.invoice_number}</span>
              <span className="font-medium">{customerName(inv.customer_id)}</span>
              <Badge
                variant={
                  inv.status === "PAID"
                    ? "success"
                    : inv.status === "PARTIALLY_PAID"
                      ? "warning"
                      : "default"
                }
              >
                {inv.status}
              </Badge>
              <span className="text-muted-foreground">
                due {inv.due_date}
              </span>
              <span className="ml-auto">
                <span className="font-medium">
                  {formatAmount(inv.total_amount)}
                </span>
                <span className="text-muted-foreground">
                  {" "}
                  (paid {formatAmount(inv.paid_amount)})
                </span>
              </span>
            </div>
          ))
        )}
      </Card>

      <GlDefaultsCard />
    </div>
  );
}

/* -------------------------------- pos panel ------------------------------- */

function PosPanel() {
  const { warehouses, items } = useSalesMaster();
  const [error, setError] = useState<string | null>(null);
  const [saleDone, setSaleDone] = useState<string | null>(null);
  const [batchDone, setBatchDone] = useState<string | null>(null);
  const [form, setForm] = useState({
    warehouse_id: "",
    payment_method: "CASH",
  });
  const [lines, setLines] = useState<Line[]>([
    { item_id: "", qty: "", unit_price: "" },
  ]);

  const sale = useMutation({
    mutationFn: () =>
      api.post<{
        pos_transaction_id: string;
        transaction_number: string;
        total_amount: string;
        total_cogs: string;
      }>("/sales/pos", {
        warehouse_id: form.warehouse_id,
        payment_method: form.payment_method,
        lines: lines
          .filter((l) => l.item_id && l.qty && l.unit_price)
          .map((l) => ({
            item_id: l.item_id,
            qty: l.qty,
            unit_price: l.unit_price,
          })),
      }),
    onSuccess: (r) => {
      setSaleDone(
        `${r.transaction_number} — total ${formatAmount(r.total_amount)}`,
      );
      setLines([{ item_id: "", qty: "", unit_price: "" }]);
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  const postBatch = useMutation({
    mutationFn: () =>
      api.post<{
        txn_count: number;
        total_sales: string | null;
        total_cogs: string | null;
        journal_entry_id: string | null;
        note: string | null;
      }>("/sales/pos/post-batch"),
    onSuccess: (r) => {
      setBatchDone(
        r.journal_entry_id
          ? `${r.txn_count} txn posted — sales ${formatAmount(r.total_sales ?? "0")}, COGS ${formatAmount(r.total_cogs ?? "0")}`
          : (r.note ?? "Nothing to post."),
      );
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-medium flex items-center gap-2">
        <Store className="w-4 h-4" /> Point of sale
      </h2>

      <Card className="p-5 space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <select
            className={inputCls}
            value={form.warehouse_id}
            onChange={(e) => setForm({ ...form, warehouse_id: e.target.value })}
          >
            <option value="">Warehouse…</option>
            {warehouses.data?.map((w) => (
              <option key={w.id} value={w.id}>
                {w.code} — {w.name}
              </option>
            ))}
          </select>
          <select
            className={inputCls}
            value={form.payment_method}
            onChange={(e) =>
              setForm({ ...form, payment_method: e.target.value })
            }
          >
            <option value="CASH">CASH</option>
            <option value="BANK_TRANSFER">BANK_TRANSFER</option>
            <option value="E_WALLET">E_WALLET</option>
          </select>
        </div>
        <LineEditor lines={lines} setLines={setLines} items={items.data ?? []} />
        {error && <p className="text-xs text-destructive">{error}</p>}
        {saleDone && <p className="text-xs text-primary">Sold: {saleDone}</p>}
        <div className="flex justify-between">
          <Button
            size="sm"
            variant="outline"
            disabled={postBatch.isPending}
            onClick={() => postBatch.mutate()}
          >
            {postBatch.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
            Post batch journal
          </Button>
          <Button
            size="sm"
            disabled={
              sale.isPending ||
              !form.warehouse_id ||
              !lines.some((l) => l.item_id && l.qty && l.unit_price)
            }
            onClick={() => sale.mutate()}
          >
            {sale.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
            Complete sale
          </Button>
        </div>
        {batchDone && <p className="text-xs text-primary">{batchDone}</p>}
      </Card>

      <p className="text-xs text-muted-foreground">
        POS is a fast path: stock is issued immediately, GL is aggregated —
        post the batch journal to recognize revenue and COGS.
      </p>
    </div>
  );
}

/* ------------------------------ returns panel ----------------------------- */

function ReturnsPanel() {
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const returns = useQuery({
    queryKey: ["sales-returns"],
    queryFn: () => api.get<SalesReturn[]>("/sales/returns"),
  });

  const approve = useMutation({
    mutationFn: (id: string) =>
      api.post<{
        sales_return_id: string;
        return_number: string;
        total_amount: string;
        cogs_reversed: string;
      }>(`/sales/returns/${id}/approve`),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["sales-returns"] });
      setDone(
        `${r.return_number} approved — credit note ${formatAmount(r.total_amount)}, COGS reversed ${formatAmount(r.cogs_reversed)}`,
      );
      setError(null);
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-medium flex items-center gap-2">
        <Undo2 className="w-4 h-4" /> Sales returns / credit notes (
        {returns.data?.length ?? 0})
      </h2>

      {error && <p className="text-xs text-destructive">{error}</p>}
      {done && <p className="text-xs text-primary">{done}</p>}

      <Card className="divide-y">
        {returns.isLoading ? (
          <div className="p-6 text-sm text-muted-foreground">Loading…</div>
        ) : returns.data?.length === 0 ? (
          <div className="p-6 text-sm text-muted-foreground">
            No returns yet.
          </div>
        ) : (
          returns.data?.map((r) => (
            <div
              key={r.id}
              className="p-4 flex flex-wrap items-center gap-3 text-sm"
            >
              <span className="font-mono text-xs">{r.return_number}</span>
              <Badge
                variant={r.status === "APPROVED" ? "success" : "default"}
              >
                {r.status}
              </Badge>
              <span className="ml-auto font-medium">
                {formatAmount(r.total_amount)}
              </span>
              {r.status === "DRAFT" && (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={approve.isPending}
                  onClick={() => approve.mutate(r.id)}
                >
                  <CheckCircle2 className="w-4 h-4" /> Approve
                </Button>
              )}
            </div>
          ))
        )}
      </Card>

      <p className="text-xs text-muted-foreground">
        Creating a return requires invoice line references — create DRAFT
        returns via the AI sidebar or API, then approve here.
      </p>
    </div>
  );
}

/* --------------------------------- page ---------------------------------- */

export function SalesPage() {
  const [tab, setTab] = useState<Tab>("orders");

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-medium">Sales &amp; AR</h1>
          <p className="text-sm text-muted-foreground">
            Orders, delivery, invoicing, payments, POS, and returns — credit
            limits and GL handled by the engine.
          </p>
        </div>
      </div>

      <div className="flex gap-1 border-b border-border">
        {(["orders", "customers", "invoices", "pos", "returns"] as Tab[]).map(
          (t) => (
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
          ),
        )}
      </div>

      {tab === "orders" && <OrdersPanel />}
      {tab === "customers" && <CustomersPanel />}
      {tab === "invoices" && <InvoicesPanel />}
      {tab === "pos" && <PosPanel />}
      {tab === "returns" && <ReturnsPanel />}
    </div>
  );
}
