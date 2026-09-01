/**
 * Procurement & AP (M5/M5A) — purchase orders (create -> submit ->
 * approve -> receive), GRN inspection (PUTG), AP bills with 3-way
 * match, vendor payments, purchase returns (debit note), and landed
 * costs.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { Badge, Button, Card } from "@/components/ui";
import {
  ChevronDown,
  ChevronRight,
  Loader2,
  PackageCheck,
  Plus,
  Truck,
  Undo2,
  X,
} from "lucide-react";

/* --------------------------------- types --------------------------------- */

interface Vendor {
  id: string;
  vendor_code: string;
  vendor_name: string;
  payment_term_days: number;
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

interface PoLine {
  id: string;
  item_id: string;
  qty_ordered: string;
  qty_received: string;
  unit_price: string;
  line_total: string;
}

interface PurchaseOrder {
  id: string;
  po_number: string;
  status: string;
  total_amount: string;
  required_approval_role: string | null;
  lines: PoLine[];
}

interface Grn {
  grn_id: string;
  grn_number: string;
  purchase_order_id: string;
  warehouse_id: string;
  received_date: string;
  status: string;
  inspection_status: string;
}

interface GrnLine {
  grn_line_id: string;
  purchase_order_line_id: string;
  item_id: string;
  qty_received: string;
  qty_accepted: string;
  qty_rejected: string;
}

interface ApBill {
  id: string;
  bill_number: string;
  status: string;
  total_amount: string;
  paid_amount: string;
  dispute_reason: string | null;
}

interface PurchaseReturn {
  id: string;
  return_number: string;
  status: string;
  total_amount: string;
  reason: string | null;
}

interface LandedCost {
  id: string;
  lc_number: string;
  status: string;
  total_amount: string;
  allocation_method: string;
}

type Tab =
  | "orders"
  | "vendors"
  | "grns"
  | "bills"
  | "payments"
  | "returns"
  | "landed-costs";

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

function poStatusVariant(status: string) {
  switch (status) {
    case "RECEIVED":
      return "success" as const;
    case "PARTIALLY_RECEIVED":
      return "warning" as const;
    case "PENDING_APPROVAL":
      return "outline" as const;
    case "APPROVED":
      return "outline" as const;
    default:
      return "default" as const;
  }
}

function grnStatusVariant(status: string) {
  switch (status) {
    case "PASSED":
      return "success" as const;
    case "PARTIAL":
      return "warning" as const;
    case "REJECTED":
      return "destructive" as const;
    default:
      return "default" as const;
  }
}

function billStatusVariant(status: string) {
  switch (status) {
    case "APPROVED":
      return "success" as const;
    case "PAID":
      return "success" as const;
    case "DISPUTED":
      return "destructive" as const;
    default:
      return "default" as const;
  }
}

/* ------------------------------ shared queries ---------------------------- */

function useProcMaster() {
  const vendors = useQuery({
    queryKey: ["proc", "vendors"],
    queryFn: () => api.get<Vendor[]>("/proc/vendors"),
  });
  const warehouses = useQuery({
    queryKey: ["inv", "warehouses"],
    queryFn: () => api.get<Warehouse[]>("/inv/warehouses"),
  });
  const items = useQuery({
    queryKey: ["inv", "items"],
    queryFn: () => api.get<InvItem[]>("/inv/items"),
  });
  const grns = useQuery({
    queryKey: ["proc", "grns"],
    queryFn: () => api.get<Grn[]>("/proc/grns"),
  });
  return { vendors, warehouses, items, grns };
}

/* ------------------------------ orders panel ------------------------------ */

function OrdersPanel() {
  const qc = useQueryClient();
  const { vendors, warehouses, items } = useProcMaster();
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [receivePo, setReceivePo] = useState<PurchaseOrder | null>(null);
  const [receiveQtys, setReceiveQtys] = useState<Record<string, string>>({});

  const orders = useQuery({
    queryKey: ["proc", "orders"],
    queryFn: () => api.get<PurchaseOrder[]>("/proc/orders"),
  });

  const submitPo = useMutation({
    mutationFn: (poId: string) =>
      api.post<{
        purchase_order_id: string;
        required_approval_role: string;
        total_amount: string;
      }>(`/proc/orders/${poId}/submit`),
    onSuccess: (r) =>
      setNotice(`Submitted — requires approval by ${r.required_approval_role}.`),
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  const approvePo = useMutation({
    mutationFn: (poId: string) =>
      api.post<{ purchase_order_id: string; status: string }>(
        `/proc/orders/${poId}/approve`,
      ),
    onSuccess: (r) => setNotice(`PO approved — status ${r.status}.`),
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  const receiveGoods = useMutation({
    mutationFn: (vars: { poId: string; lines: unknown[] }) =>
      api.post<{ grn_id: string; grn_number: string; inspection_status: string }>(
        `/proc/orders/${vars.poId}/receive`,
        {
          received_date: new Date().toISOString().slice(0, 10),
          lines: vars.lines,
        },
      ),
    onSuccess: (r) => {
      setNotice(
        `Goods received — ${r.grn_number} (inspection ${r.inspection_status}). ` +
          "Inspect it on the GRN tab.",
      );
      setReceivePo(null);
      qc.invalidateQueries({ queryKey: ["proc"] });
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  const itemName = (id: string) => {
    const it = items.data?.find((i) => i.id === id);
    return it ? `${it.item_code} — ${it.item_name}` : id;
  };

  /* ----- create form ----- */
  const [form, setForm] = useState({
    vendor_id: "",
    warehouse_id: "",
    po_number: "",
    order_date: new Date().toISOString().slice(0, 10),
  });
  const [poLines, setPoLines] = useState<
    { item_id: string; qty_ordered: string; unit_price: string }[]
  >([{ item_id: "", qty_ordered: "", unit_price: "" }]);

  const poTotal = poLines.reduce(
    (acc, ln) =>
      acc +
      (Number(ln.qty_ordered) || 0) * (Number(ln.unit_price) || 0),
    0,
  );

  const createPo = useMutation({
    mutationFn: () =>
      api.post<PurchaseOrder>("/proc/orders", {
        ...form,
        lines: poLines.filter(
          (ln) => ln.item_id && ln.qty_ordered && ln.unit_price,
        ),
      }),
    onSuccess: (r) => {
      setNotice(`PO ${r.po_number} created as ${r.status}.`);
      setForm({
        vendor_id: "",
        warehouse_id: "",
        po_number: "",
        order_date: new Date().toISOString().slice(0, 10),
      });
      setPoLines([{ item_id: "", qty_ordered: "", unit_price: "" }]);
      qc.invalidateQueries({ queryKey: ["proc", "orders"] });
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  const canCreate =
    form.vendor_id &&
    form.warehouse_id &&
    form.po_number &&
    poLines.some((ln) => ln.item_id && ln.qty_ordered && ln.unit_price);

  return (
    <div className="space-y-4">
      {(error || notice) && (
        <div
          className={
            error
              ? "rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
              : "rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-400"
          }
        >
          {error ?? notice}
          <button
            className="ml-2 text-xs underline"
            onClick={() => {
              setError(null);
              setNotice(null);
            }}
          >
            dismiss
          </button>
        </div>
      )}

      <Card className="p-4 space-y-3">
        <h3 className="text-sm font-semibold">New Purchase Order</h3>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <select
            className={inputCls}
            value={form.vendor_id}
            onChange={(e) =>
              setForm({ ...form, vendor_id: e.target.value })
            }
          >
            <option value="">Vendor…</option>
            {vendors.data?.map((v) => (
              <option key={v.id} value={v.id}>
                {v.vendor_code} — {v.vendor_name}
              </option>
            ))}
          </select>
          <select
            className={inputCls}
            value={form.warehouse_id}
            onChange={(e) =>
              setForm({ ...form, warehouse_id: e.target.value })
            }
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
            placeholder="PO number"
            value={form.po_number}
            onChange={(e) =>
              setForm({ ...form, po_number: e.target.value })
            }
          />
          <input
            type="date"
            className={inputCls}
            value={form.order_date}
            onChange={(e) =>
              setForm({ ...form, order_date: e.target.value })
            }
          />
        </div>

        <div className="space-y-2">
          {poLines.map((ln, i) => (
            <div key={i} className="grid grid-cols-[2fr_1fr_1fr_auto] gap-2">
              <select
                className={inputCls}
                value={ln.item_id}
                onChange={(e) => {
                  const next = [...poLines];
                  next[i] = { ...ln, item_id: e.target.value };
                  setPoLines(next);
                }}
              >
                <option value="">Item…</option>
                {items.data?.map((it) => (
                  <option key={it.id} value={it.id}>
                    {it.item_code} — {it.item_name}
                  </option>
                ))}
              </select>
              <input
                className={inputCls}
                placeholder="Qty"
                value={ln.qty_ordered}
                onChange={(e) => {
                  const next = [...poLines];
                  next[i] = { ...ln, qty_ordered: e.target.value };
                  setPoLines(next);
                }}
              />
              <input
                className={inputCls}
                placeholder="Unit price"
                value={ln.unit_price}
                onChange={(e) => {
                  const next = [...poLines];
                  next[i] = { ...ln, unit_price: e.target.value };
                  setPoLines(next);
                }}
              />
              <Button
                variant="outline"
                size="sm"
                disabled={poLines.length === 1}
                onClick={() =>
                  setPoLines(poLines.filter((_, j) => j !== i))
                }
              >
                <X className="h-3.5 w-3.5" />
              </Button>
            </div>
          ))}
        </div>

        <div className="flex items-center justify-between">
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              setPoLines([
                ...poLines,
                { item_id: "", qty_ordered: "", unit_price: "" },
              ])
            }
          >
            <Plus className="h-3.5 w-3.5" /> Line
          </Button>
          <span className="text-sm text-muted-foreground">
            Total: {formatAmount(poTotal.toFixed(2))}
          </span>
          <Button
            size="sm"
            disabled={!canCreate || createPo.isPending}
            onClick={() => {
              setError(null);
              setNotice(null);
              createPo.mutate();
            }}
          >
            {createPo.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              "Create PO"
            )}
          </Button>
        </div>
      </Card>

      <Card className="divide-y divide-border">
        <div className="flex items-center justify-between px-4 py-2">
          <span className="text-sm font-semibold">
            Purchase Orders ({orders.data?.length ?? 0})
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => orders.refetch()}
          >
            Refresh
          </Button>
        </div>
        {orders.isLoading ? (
          <div className="flex justify-center p-6">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : (
          orders.data?.map((po) => (
            <div key={po.id} className="px-4 py-2.5">
              <div className="flex items-center justify-between gap-2">
                <button
                  className="flex items-center gap-2 text-sm"
                  onClick={() =>
                    setExpanded(expanded === po.id ? null : po.id)
                  }
                >
                  {expanded === po.id ? (
                    <ChevronDown className="h-3.5 w-3.5" />
                  ) : (
                    <ChevronRight className="h-3.5 w-3.5" />
                  )}
                  <span className="font-medium">{po.po_number}</span>
                </button>
                <div className="flex items-center gap-2">
                  <span className="text-sm tabular-nums text-muted-foreground">
                    {formatAmount(po.total_amount)}
                  </span>
                  <Badge variant={poStatusVariant(po.status)}>
                    {po.status}
                  </Badge>
                  {po.status === "DRAFT" && (
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={submitPo.isPending}
                      onClick={() => {
                        setError(null);
                        setNotice(null);
                        submitPo.mutate(po.id);
                      }}
                    >
                      Submit
                    </Button>
                  )}
                  {po.status === "PENDING_APPROVAL" && (
                    <Button
                      size="sm"
                      disabled={approvePo.isPending}
                      onClick={() => {
                        setError(null);
                        setNotice(null);
                        approvePo.mutate(po.id);
                      }}
                    >
                      Approve
                    </Button>
                  )}
                  {(po.status === "APPROVED" ||
                    po.status === "PARTIALLY_RECEIVED") && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setError(null);
                        setReceivePo(po);
                        setReceiveQtys(
                          Object.fromEntries(
                            po.lines.map((ln) => [ln.id, ""]),
                          ),
                        );
                      }}
                    >
                      <Truck className="h-3.5 w-3.5" /> Receive
                    </Button>
                  )}
                </div>
              </div>
              {expanded === po.id && (
                <div className="mt-2 space-y-1 pl-6">
                  {po.lines.map((ln) => (
                    <div
                      key={ln.id}
                      className="flex justify-between text-xs text-muted-foreground"
                    >
                      <span>{itemName(ln.item_id)}</span>
                      <span className="tabular-nums">
                        {fmtQty(ln.qty_ordered)} @{" "}
                        {formatAmount(ln.unit_price)} ={" "}
                        {formatAmount(ln.line_total)}
                        {Number(ln.qty_received) > 0 &&
                          ` · received ${fmtQty(ln.qty_received)}`}
                      </span>
                    </div>
                  ))}
                  {po.required_approval_role && (
                    <div className="text-xs text-muted-foreground">
                      Approval role: {po.required_approval_role}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))
        )}
      </Card>

      {receivePo && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <Card className="w-full max-w-lg space-y-3 p-4">
            <h3 className="text-sm font-semibold">
              Receive goods — {receivePo.po_number}
            </h3>
            {receivePo.lines.map((ln) => (
              <div key={ln.id} className="flex items-center gap-2">
                <span className="flex-1 text-xs text-muted-foreground">
                  {itemName(ln.item_id)} · ordered {fmtQty(ln.qty_ordered)}
                </span>
                <input
                  className={`${inputCls} w-28`}
                  placeholder="Qty received"
                  value={receiveQtys[ln.id] ?? ""}
                  onChange={(e) =>
                    setReceiveQtys({
                      ...receiveQtys,
                      [ln.id]: e.target.value,
                    })
                  }
                />
              </div>
            ))}
            <div className="flex justify-end gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setReceivePo(null)}
              >
                Cancel
              </Button>
              <Button
                size="sm"
                disabled={
                  receiveGoods.isPending ||
                  !receivePo.lines.some(
                    (ln) => receiveQtys[ln.id]?.trim() !== "",
                  )
                }
                onClick={() => {
                  setError(null);
                  receiveGoods.mutate({
                    poId: receivePo.id,
                    lines: receivePo.lines
                      .filter((ln) => receiveQtys[ln.id]?.trim() !== "")
                      .map((ln) => ({
                        purchase_order_line_id: ln.id,
                        qty_received: receiveQtys[ln.id],
                      })),
                  });
                }}
              >
                {receiveGoods.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  "Receive"
                )}
              </Button>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}

/* ------------------------------ vendors panel ----------------------------- */

function VendorsPanel() {
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [form, setForm] = useState({
    vendor_code: "",
    vendor_name: "",
    payment_term_days: "30",
    npwp: "",
  });

  const vendors = useQuery({
    queryKey: ["proc", "vendors"],
    queryFn: () => api.get<Vendor[]>("/proc/vendors"),
  });

  const createVendor = useMutation({
    mutationFn: () =>
      api.post<Vendor>("/proc/vendors", {
        vendor_code: form.vendor_code,
        vendor_name: form.vendor_name,
        payment_term_days: Number(form.payment_term_days) || 30,
        npwp: form.npwp || null,
      }),
    onSuccess: (r) => {
      setNotice(`Vendor ${r.vendor_code} added.`);
      setForm({
        vendor_code: "",
        vendor_name: "",
        payment_term_days: "30",
        npwp: "",
      });
      qc.invalidateQueries({ queryKey: ["proc", "vendors"] });
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  return (
    <div className="space-y-4">
      {(error || notice) && (
        <div
          className={
            error
              ? "rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
              : "rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-400"
          }
        >
          {error ?? notice}
          <button
            className="ml-2 text-xs underline"
            onClick={() => {
              setError(null);
              setNotice(null);
            }}
          >
            dismiss
          </button>
        </div>
      )}

      <Card className="p-4 space-y-3">
        <h3 className="text-sm font-semibold">New Vendor</h3>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <input
            className={inputCls}
            placeholder="Vendor code"
            value={form.vendor_code}
            onChange={(e) =>
              setForm({ ...form, vendor_code: e.target.value })
            }
          />
          <input
            className={inputCls}
            placeholder="Vendor name"
            value={form.vendor_name}
            onChange={(e) =>
              setForm({ ...form, vendor_name: e.target.value })
            }
          />
          <input
            className={inputCls}
            placeholder="Term (days)"
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
        <div className="flex justify-end">
          <Button
            size="sm"
            disabled={
              !form.vendor_code ||
              !form.vendor_name ||
              createVendor.isPending
            }
            onClick={() => {
              setError(null);
              setNotice(null);
              createVendor.mutate();
            }}
          >
            {createVendor.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              "Add vendor"
            )}
          </Button>
        </div>
      </Card>

      <Card className="divide-y divide-border">
        <div className="px-4 py-2 text-sm font-semibold">
          Vendors ({vendors.data?.length ?? 0})
        </div>
        {vendors.isLoading ? (
          <div className="flex justify-center p-6">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : (
          vendors.data?.map((v) => (
            <div
              key={v.id}
              className="flex items-center justify-between px-4 py-2.5 text-sm"
            >
              <span>
                <span className="font-medium">{v.vendor_code}</span> —{" "}
                {v.vendor_name}
              </span>
              <span className="text-xs text-muted-foreground">
                Term {v.payment_term_days}d · {v.is_active ? "active" : "inactive"}
              </span>
            </div>
          ))
        )}
      </Card>
    </div>
  );
}

/* --------------------------- GRN / inspect panel --------------------------- */

function GrnPanel() {
  const qc = useQueryClient();
  const { items, grns } = useProcMaster();
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [inspectGrn, setInspectGrn] = useState<Grn | null>(null);
  const [inspectLines, setInspectLines] = useState<GrnLine[]>([]);

  const grnLines = useQuery({
    queryKey: ["proc", "grn-lines", inspectGrn?.grn_id],
    queryFn: () =>
      api.get<GrnLine[]>(`/proc/grns/${inspectGrn?.grn_id}/lines`),
    enabled: !!inspectGrn,
  });

  const inspect = useMutation({
    mutationFn: (vars: { grnId: string; lines: unknown[] }) =>
      api.post<{ grn_id: string; total_accepted_value: string; any_rejected: boolean }>(
        `/proc/grns/${vars.grnId}/inspect`,
        { line_results: vars.lines },
      ),
    onSuccess: (r) => {
      setNotice(
        `Inspection recorded — accepted value ${formatAmount(
          r.total_accepted_value,
        )}${r.any_rejected ? " (some rejected)" : ""}. Stock posted for accepted qty.`,
      );
      setInspectGrn(null);
      qc.invalidateQueries({ queryKey: ["proc"] });
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  const itemName = (id: string) => {
    const it = items.data?.find((i) => i.id === id);
    return it ? `${it.item_code}` : id.slice(0, 8);
  };

  return (
    <div className="space-y-4">
      {(error || notice) && (
        <div
          className={
            error
              ? "rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
              : "rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-400"
          }
        >
          {error ?? notice}
          <button
            className="ml-2 text-xs underline"
            onClick={() => {
              setError(null);
              setNotice(null);
            }}
          >
            dismiss
          </button>
        </div>
      )}

      <Card className="divide-y divide-border">
        <div className="flex items-center justify-between px-4 py-2">
          <span className="text-sm font-semibold">
            Goods Received Notes ({grns.data?.length ?? 0})
          </span>
          <Button variant="outline" size="sm" onClick={() => grns.refetch()}>
            Refresh
          </Button>
        </div>
        {grns.isLoading ? (
          <div className="flex justify-center p-6">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : (
          grns.data?.map((g) => (
            <div
              key={g.grn_id}
              className="flex items-center justify-between gap-2 px-4 py-2.5"
            >
              <div>
                <span className="text-sm font-medium">{g.grn_number}</span>
                <span className="ml-2 text-xs text-muted-foreground">
                  {g.received_date}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant={grnStatusVariant(g.inspection_status)}>
                  {g.inspection_status}
                </Badge>
                {g.inspection_status === "PENDING" && (
                  <Button
                    size="sm"
                    onClick={() => {
                      setError(null);
                      setNotice(null);
                      setInspectGrn(g);
                      setInspectLines([]);
                    }}
                  >
                    <PackageCheck className="h-3.5 w-3.5" /> Inspect
                  </Button>
                )}
              </div>
            </div>
          ))
        )}
      </Card>

      {inspectGrn && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <Card className="w-full max-w-lg space-y-3 p-4">
            <h3 className="text-sm font-semibold">
              Inspect — {inspectGrn.grn_number} (PUTG)
            </h3>
            {grnLines.isLoading ? (
              <div className="flex justify-center p-4">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            ) : (
              <>
                <div className="grid grid-cols-[2fr_1fr_1fr] gap-2 text-xs font-medium text-muted-foreground">
                  <span>Item</span>
                  <span>Qty accepted</span>
                  <span>Qty rejected</span>
                </div>
                {grnLines.data?.map((ln) => (
                  <div
                    key={ln.grn_line_id}
                    className="grid grid-cols-[2fr_1fr_1fr] gap-2"
                  >
                    <span className="flex items-center text-xs text-muted-foreground">
                      {itemName(ln.item_id)} · received{" "}
                      {fmtQty(ln.qty_received)}
                    </span>
                    <input
                      className={inputCls}
                      placeholder="Accepted"
                      value={
                        inspectLines.find(
                          (l) => l.grn_line_id === ln.grn_line_id,
                        )?.qty_accepted ?? ""
                      }
                      onChange={(e) => {
                        const next = inspectLines.filter(
                          (l) => l.grn_line_id !== ln.grn_line_id,
                        );
                        next.push({
                          grn_line_id: ln.grn_line_id,
                          purchase_order_line_id: "",
                          item_id: "",
                          qty_received: "",
                          qty_accepted: e.target.value,
                          qty_rejected:
                            inspectLines.find(
                              (l) => l.grn_line_id === ln.grn_line_id,
                            )?.qty_rejected ?? "",
                        });
                        setInspectLines(next);
                      }}
                    />
                    <input
                      className={inputCls}
                      placeholder="Rejected"
                      value={
                        inspectLines.find(
                          (l) => l.grn_line_id === ln.grn_line_id,
                        )?.qty_rejected ?? ""
                      }
                      onChange={(e) => {
                        const next = inspectLines.filter(
                          (l) => l.grn_line_id !== ln.grn_line_id,
                        );
                        next.push({
                          grn_line_id: ln.grn_line_id,
                          purchase_order_line_id: "",
                          item_id: "",
                          qty_received: "",
                          qty_accepted:
                            inspectLines.find(
                              (l) => l.grn_line_id === ln.grn_line_id,
                            )?.qty_accepted ?? "",
                          qty_rejected: e.target.value,
                        });
                        setInspectLines(next);
                      }}
                    />
                  </div>
                ))}
              </>
            )}
            <div className="flex justify-end gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setInspectGrn(null)}
              >
                Cancel
              </Button>
              <Button
                size="sm"
                disabled={
                  inspect.isPending ||
                  !inspectLines.some((l) => l.qty_accepted || l.qty_rejected)
                }
                onClick={() => {
                  setError(null);
                  inspect.mutate({
                    grnId: inspectGrn.grn_id,
                    lines: inspectLines
                      .filter((l) => l.qty_accepted || l.qty_rejected)
                      .map((l) => ({
                        grn_line_id: l.grn_line_id,
                        qty_accepted: l.qty_accepted || "0",
                        qty_rejected: l.qty_rejected || "0",
                      })),
                  });
                }}
              >
                {inspect.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  "Record inspection"
                )}
              </Button>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}

/* ------------------------- bills & 3-way match panel ------------------------ */

function BillsPanel() {
  const qc = useQueryClient();
  const { items, grns } = useProcMaster();
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const bills = useQuery({
    queryKey: ["proc", "bills"],
    queryFn: () => api.get<ApBill[]>("/proc/bills"),
  });

  const match = useMutation({
    mutationFn: (billId: string) =>
      api.post<{
        status: string;
        price_variance: string | null;
        reason: string | null;
      }>(`/proc/bills/${billId}/match`),
    onSuccess: (r) => {
      setNotice(
        r.status === "DISPUTED"
          ? `Bill DISPUTED: ${r.reason ?? "variance"} — variance ${r.price_variance ?? "?"}.`
          : `Bill matched — ${r.status} (variance ${r.price_variance ?? "0"}). GL posted.`,
      );
      qc.invalidateQueries({ queryKey: ["proc", "bills"] });
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  /* ----- create bill form (from an inspected GRN) ----- */
  const [form, setForm] = useState({
    grn_id: "",
    bill_number: "",
    bill_date: new Date().toISOString().slice(0, 10),
    tax_rate_pct: "11",
  });
  const [billLines, setBillLines] = useState<
    { item_id: string; qty: string; unit_price: string }[]
  >([{ item_id: "", qty: "", unit_price: "" }]);

  const inspectedGrns = (grns.data ?? []).filter(
    (g) =>
      g.inspection_status === "PASSED" || g.inspection_status === "PARTIAL",
  );

  const createBill = useMutation({
    mutationFn: () =>
      api.post<{ ap_bill_id: string; total_amount: string }>("/proc/bills", {
        ...form,
        lines: billLines.filter((ln) => ln.item_id && ln.qty && ln.unit_price),
      }),
    onSuccess: (r) => {
      setNotice(
        `Bill created — total ${formatAmount(r.total_amount)}. Run "Match" to post GL.`,
      );
      setForm({
        grn_id: "",
        bill_number: "",
        bill_date: new Date().toISOString().slice(0, 10),
        tax_rate_pct: "11",
      });
      setBillLines([{ item_id: "", qty: "", unit_price: "" }]);
      qc.invalidateQueries({ queryKey: ["proc", "bills"] });
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  const canCreate =
    form.grn_id && form.bill_number &&
    billLines.some((ln) => ln.item_id && ln.qty && ln.unit_price);

  return (
    <div className="space-y-4">
      {(error || notice) && (
        <div
          className={
            error
              ? "rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
              : "rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-400"
          }
        >
          {error ?? notice}
          <button
            className="ml-2 text-xs underline"
            onClick={() => {
              setError(null);
              setNotice(null);
            }}
          >
            dismiss
          </button>
        </div>
      )}

      <Card className="p-4 space-y-3">
        <h3 className="text-sm font-semibold">New AP Bill</h3>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <select
            className={inputCls}
            value={form.grn_id}
            onChange={(e) => setForm({ ...form, grn_id: e.target.value })}
          >
            <option value="">Inspected GRN…</option>
            {inspectedGrns.map((g) => (
              <option key={g.grn_id} value={g.grn_id}>
                {g.grn_number} ({g.inspection_status})
              </option>
            ))}
          </select>
          <input
            className={inputCls}
            placeholder="Bill number"
            value={form.bill_number}
            onChange={(e) =>
              setForm({ ...form, bill_number: e.target.value })
            }
          />
          <input
            type="date"
            className={inputCls}
            value={form.bill_date}
            onChange={(e) =>
              setForm({ ...form, bill_date: e.target.value })
            }
          />
          <input
            className={inputCls}
            placeholder="Tax %"
            value={form.tax_rate_pct}
            onChange={(e) =>
              setForm({ ...form, tax_rate_pct: e.target.value })
            }
          />
        </div>

        <div className="space-y-2">
          {billLines.map((ln, i) => (
            <div key={i} className="grid grid-cols-[2fr_1fr_1fr_auto] gap-2">
              <select
                className={inputCls}
                value={ln.item_id}
                onChange={(e) => {
                  const next = [...billLines];
                  next[i] = { ...ln, item_id: e.target.value };
                  setBillLines(next);
                }}
              >
                <option value="">Item…</option>
                {items.data?.map((it) => (
                  <option key={it.id} value={it.id}>
                    {it.item_code} — {it.item_name}
                  </option>
                ))}
              </select>
              <input
                className={inputCls}
                placeholder="Qty"
                value={ln.qty}
                onChange={(e) => {
                  const next = [...billLines];
                  next[i] = { ...ln, qty: e.target.value };
                  setBillLines(next);
                }}
              />
              <input
                className={inputCls}
                placeholder="Unit price"
                value={ln.unit_price}
                onChange={(e) => {
                  const next = [...billLines];
                  next[i] = { ...ln, unit_price: e.target.value };
                  setBillLines(next);
                }}
              />
              <Button
                variant="outline"
                size="sm"
                disabled={billLines.length === 1}
                onClick={() =>
                  setBillLines(billLines.filter((_, j) => j !== i))
                }
              >
                <X className="h-3.5 w-3.5" />
              </Button>
            </div>
          ))}
        </div>

        <div className="flex items-center justify-between">
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              setBillLines([...billLines, { item_id: "", qty: "", unit_price: "" }])
            }
          >
            <Plus className="h-3.5 w-3.5" /> Line
          </Button>
          <Button
            size="sm"
            disabled={!canCreate || createBill.isPending}
            onClick={() => {
              setError(null);
              setNotice(null);
              createBill.mutate();
            }}
          >
            {createBill.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              "Create bill"
            )}
          </Button>
        </div>
      </Card>

      <Card className="divide-y divide-border">
        <div className="flex items-center justify-between px-4 py-2">
          <span className="text-sm font-semibold">
            AP Bills ({bills.data?.length ?? 0})
          </span>
          <Button variant="outline" size="sm" onClick={() => bills.refetch()}>
            Refresh
          </Button>
        </div>
        {bills.isLoading ? (
          <div className="flex justify-center p-6">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : (
          bills.data?.map((b) => (
            <div
              key={b.id}
              className="flex items-center justify-between gap-2 px-4 py-2.5"
            >
              <div>
                <span className="text-sm font-medium">{b.bill_number}</span>
                {b.dispute_reason && (
                  <span className="ml-2 text-xs text-destructive">
                    {b.dispute_reason}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm tabular-nums text-muted-foreground">
                  {formatAmount(b.total_amount)}
                </span>
                <Badge variant={billStatusVariant(b.status)}>
                  {b.status}
                </Badge>
                {(b.status === "PENDING" || b.status === "DRAFT") && (
                  <Button
                    size="sm"
                    disabled={match.isPending}
                    onClick={() => {
                      setError(null);
                      setNotice(null);
                      match.mutate(b.id);
                    }}
                  >
                    Match
                  </Button>
                )}
              </div>
            </div>
          ))
        )}
      </Card>
    </div>
  );
}

/* ------------------------------ payments panel ----------------------------- */

function PaymentsPanel() {
  const qc = useQueryClient();
  const { vendors } = useProcMaster();
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [form, setForm] = useState({
    vendor_id: "",
    payment_date: new Date().toISOString().slice(0, 10),
    amount: "",
    payment_method: "TRANSFER",
  });

  const bills = useQuery({
    queryKey: ["proc", "bills"],
    queryFn: () => api.get<ApBill[]>("/proc/bills"),
  });
  const openBills = (bills.data ?? []).filter(
    (b) => b.status !== "PAID" && b.status !== "DISPUTED",
  );

  const pay = useMutation({
    mutationFn: () =>
      api.post<{ ap_payment_id: string; journal_entry_id: string }>(
        "/proc/payments",
        form,
      ),
    onSuccess: (r) => {
      setNotice(`Payment recorded — JE ${r.journal_entry_id.slice(0, 8)}…`);
      setForm({
        vendor_id: "",
        payment_date: new Date().toISOString().slice(0, 10),
        amount: "",
        payment_method: "TRANSFER",
      });
      qc.invalidateQueries({ queryKey: ["proc", "bills"] });
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  return (
    <div className="space-y-4">
      {(error || notice) && (
        <div
          className={
            error
              ? "rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
              : "rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-400"
          }
        >
          {error ?? notice}
          <button
            className="ml-2 text-xs underline"
            onClick={() => {
              setError(null);
              setNotice(null);
            }}
          >
            dismiss
          </button>
        </div>
      )}

      <Card className="p-4 space-y-3">
        <h3 className="text-sm font-semibold">Record AP Payment</h3>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <select
            className={inputCls}
            value={form.vendor_id}
            onChange={(e) => setForm({ ...form, vendor_id: e.target.value })}
          >
            <option value="">Vendor…</option>
            {vendors.data?.map((v) => (
              <option key={v.id} value={v.id}>
                {v.vendor_code} — {v.vendor_name}
              </option>
            ))}
          </select>
          <input
            type="date"
            className={inputCls}
            value={form.payment_date}
            onChange={(e) =>
              setForm({ ...form, payment_date: e.target.value })
            }
          />
          <input
            className={inputCls}
            placeholder="Amount"
            value={form.amount}
            onChange={(e) => setForm({ ...form, amount: e.target.value })}
          />
          <select
            className={inputCls}
            value={form.payment_method}
            onChange={(e) =>
              setForm({ ...form, payment_method: e.target.value })
            }
          >
            <option value="TRANSFER">Transfer</option>
            <option value="CASH">Cash</option>
          </select>
        </div>
        <div className="flex justify-end">
          <Button
            size="sm"
            disabled={
              !form.vendor_id || !form.amount || pay.isPending
            }
            onClick={() => {
              setError(null);
              setNotice(null);
              pay.mutate();
            }}
          >
            {pay.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              "Pay"
            )}
          </Button>
        </div>
      </Card>

      <Card className="divide-y divide-border">
        <div className="px-4 py-2 text-sm font-semibold">
          Open bills ({openBills.length})
        </div>
        {openBills.map((b) => (
          <div
            key={b.id}
            className="flex items-center justify-between px-4 py-2.5 text-sm"
          >
            <span className="font-medium">{b.bill_number}</span>
            <span className="tabular-nums text-muted-foreground">
              {formatAmount(b.total_amount)} · paid {formatAmount(b.paid_amount)}
            </span>
          </div>
        ))}
        {openBills.length === 0 && (
          <div className="px-4 py-4 text-xs text-muted-foreground">
            No open bills.
          </div>
        )}
      </Card>
    </div>
  );
}

/* ------------------------------ returns panel ------------------------------ */

function ReturnsPanel() {
  const qc = useQueryClient();
  const { vendors, grns, warehouses } = useProcMaster();
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const returns = useQuery({
    queryKey: ["proc", "returns"],
    queryFn: () => api.get<PurchaseReturn[]>("/proc/returns"),
  });

  const approve = useMutation({
    mutationFn: (id: string) =>
      api.post<{
        purchase_return_id: string;
        return_number: string;
        subtotal: string;
        tax_amount: string;
        total_amount: string;
        journal_entry_id: string;
      }>(`/proc/returns/${id}/approve`),
    onSuccess: (r) => {
      setNotice(
        `Return ${r.return_number} approved — debit note total ${formatAmount(
          r.total_amount,
        )} posted.`,
      );
      qc.invalidateQueries({ queryKey: ["proc", "returns"] });
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  /* create return: pick GRN (inspected), fetch its lines, qty per line */
  const [form, setForm] = useState({
    vendor_id: "",
    grn_id: "",
    warehouse_id: "",
    return_number: "",
    return_date: new Date().toISOString().slice(0, 10),
    reason: "",
  });
  const [retLines, setRetLines] = useState<
    Record<string, { qty: string; unit_price: string }>
  >({});

  const grnLines = useQuery({
    queryKey: ["proc", "grn-lines", form.grn_id],
    queryFn: () => api.get<GrnLine[]>(`/proc/grns/${form.grn_id}/lines`),
    enabled: !!form.grn_id,
  });

  const createReturn = useMutation({
    mutationFn: () =>
      api.post("/proc/returns", {
        vendor_id: form.vendor_id,
        grn_id: form.grn_id,
        warehouse_id: form.warehouse_id,
        return_number: form.return_number,
        return_date: form.return_date,
        reason: form.reason,
        lines: (grnLines.data ?? [])
          .filter(
            (ln) =>
              (retLines[ln.grn_line_id]?.qty ?? "").trim() !== "",
          )
          .map((ln) => {
            const entry = retLines[ln.grn_line_id];
            if (!entry) {
              throw new Error("Missing return line entry");
            }
            return {
              grn_line_id: ln.grn_line_id,
              item_id: ln.item_id,
              qty_returned: entry.qty,
              unit_price: entry.unit_price || "0",
            };
          }),
      }),
    onSuccess: () => {
      setNotice("Return created as DRAFT — approve to post debit note.");
      setForm({
        vendor_id: "",
        grn_id: "",
        warehouse_id: "",
        return_number: "",
        return_date: new Date().toISOString().slice(0, 10),
        reason: "",
      });
      setRetLines({});
      qc.invalidateQueries({ queryKey: ["proc", "returns"] });
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  const inspectedGrns = (grns.data ?? []).filter(
    (g) =>
      g.inspection_status === "PASSED" || g.inspection_status === "PARTIAL",
  );

  return (
    <div className="space-y-4">
      {(error || notice) && (
        <div
          className={
            error
              ? "rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
              : "rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-400"
          }
        >
          {error ?? notice}
          <button
            className="ml-2 text-xs underline"
            onClick={() => {
              setError(null);
              setNotice(null);
            }}
          >
            dismiss
          </button>
        </div>
      )}

      <Card className="p-4 space-y-3">
        <h3 className="text-sm font-semibold">
          New Purchase Return (Debit Note)
        </h3>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
          <select
            className={inputCls}
            value={form.vendor_id}
            onChange={(e) => setForm({ ...form, vendor_id: e.target.value })}
          >
            <option value="">Vendor…</option>
            {vendors.data?.map((v) => (
              <option key={v.id} value={v.id}>
                {v.vendor_code} — {v.vendor_name}
              </option>
            ))}
          </select>
          <select
            className={inputCls}
            value={form.grn_id}
            onChange={(e) => setForm({ ...form, grn_id: e.target.value })}
          >
            <option value="">GRN…</option>
            {inspectedGrns.map((g) => (
              <option key={g.grn_id} value={g.grn_id}>
                {g.grn_number}
              </option>
            ))}
          </select>
          <select
            className={inputCls}
            value={form.warehouse_id}
            onChange={(e) =>
              setForm({ ...form, warehouse_id: e.target.value })
            }
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
            placeholder="Return number"
            value={form.return_number}
            onChange={(e) =>
              setForm({ ...form, return_number: e.target.value })
            }
          />
          <input
            type="date"
            className={inputCls}
            value={form.return_date}
            onChange={(e) =>
              setForm({ ...form, return_date: e.target.value })
            }
          />
          <input
            className={inputCls}
            placeholder="Reason (min 3 chars)"
            value={form.reason}
            onChange={(e) => setForm({ ...form, reason: e.target.value })}
          />
        </div>

        {form.grn_id && (
          <div className="space-y-2">
            {grnLines.isLoading ? (
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            ) : (
              grnLines.data?.map((ln) => (
                <div key={ln.grn_line_id} className="flex items-center gap-2">
                  <span className="flex-1 text-xs text-muted-foreground">
                    line {ln.grn_line_id.slice(0, 8)}… · accepted{" "}
                    {fmtQty(ln.qty_accepted)}
                  </span>
                  <input
                    className={`${inputCls} w-24`}
                    placeholder="Qty"
                    value={retLines[ln.grn_line_id]?.qty ?? ""}
                    onChange={(e) =>
                      setRetLines({
                        ...retLines,
                        [ln.grn_line_id]: {
                          qty: e.target.value,
                          unit_price:
                            retLines[ln.grn_line_id]?.unit_price ?? "",
                        },
                      })
                    }
                  />
                  <input
                    className={`${inputCls} w-28`}
                    placeholder="Unit price"
                    value={retLines[ln.grn_line_id]?.unit_price ?? ""}
                    onChange={(e) =>
                      setRetLines({
                        ...retLines,
                        [ln.grn_line_id]: {
                          qty: retLines[ln.grn_line_id]?.qty ?? "",
                          unit_price: e.target.value,
                        },
                      })
                    }
                  />
                </div>
              ))
            )}
          </div>
        )}

        <div className="flex justify-end">
          <Button
            size="sm"
            disabled={
              !form.vendor_id ||
              !form.grn_id ||
              !form.warehouse_id ||
              !form.return_number ||
              form.reason.length < 3 ||
              Object.values(retLines).every((v) => !v.qty.trim()) ||
              createReturn.isPending
            }
            onClick={() => {
              setError(null);
              setNotice(null);
              createReturn.mutate();
            }}
          >
            {createReturn.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              "Create return"
            )}
          </Button>
        </div>
      </Card>

      <Card className="divide-y divide-border">
        <div className="flex items-center justify-between px-4 py-2">
          <span className="text-sm font-semibold">
            Purchase Returns ({returns.data?.length ?? 0})
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => returns.refetch()}
          >
            Refresh
          </Button>
        </div>
        {returns.isLoading ? (
          <div className="flex justify-center p-6">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : (
          returns.data?.map((r) => (
            <div
              key={r.id}
              className="flex items-center justify-between gap-2 px-4 py-2.5"
            >
              <div>
                <span className="text-sm font-medium">
                  {r.return_number}
                </span>
                {r.reason && (
                  <span className="ml-2 text-xs text-muted-foreground">
                    {r.reason}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm tabular-nums text-muted-foreground">
                  {formatAmount(r.total_amount)}
                </span>
                <Badge
                  variant={
                    r.status === "APPROVED" ? "success" : "default"
                  }
                >
                  {r.status}
                </Badge>
                {r.status === "DRAFT" && (
                  <Button
                    size="sm"
                    disabled={approve.isPending}
                    onClick={() => {
                      setError(null);
                      setNotice(null);
                      approve.mutate(r.id);
                    }}
                  >
                    <Undo2 className="h-3.5 w-3.5" /> Approve
                  </Button>
                )}
              </div>
            </div>
          ))
        )}
      </Card>
    </div>
  );
}

/* ---------------------------- landed costs panel ---------------------------- */

function LandedCostsPanel() {
  const qc = useQueryClient();
  const { grns } = useProcMaster();
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const landedCosts = useQuery({
    queryKey: ["proc", "landed-costs"],
    queryFn: () => api.get<LandedCost[]>("/proc/landed-costs"),
  });

  const allocate = useMutation({
    mutationFn: (id: string) =>
      api.post<{
        landed_cost_id: string;
        lc_number: string;
        total_allocated: string;
        lines_count: number;
        journal_entry_id: string;
      }>(`/proc/landed-costs/${id}/allocate`),
    onSuccess: (r) => {
      setNotice(
        `${r.lc_number} allocated — ${formatAmount(r.total_allocated)} across ${r.lines_count} lines, avg costs updated.`,
      );
      qc.invalidateQueries({ queryKey: ["proc", "landed-costs"] });
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  const completedGrns = (grns.data ?? []).filter(
    (g) => g.status === "COMPLETED",
  );

  const [form, setForm] = useState({
    grn_id: "",
    lc_number: "",
    lc_date: new Date().toISOString().slice(0, 10),
    description: "",
    total_amount: "",
    allocation_method: "BY_QTY",
  });

  const createLc = useMutation({
    mutationFn: () =>
      api.post<LandedCost>("/proc/landed-costs", form),
    onSuccess: (r) => {
      setNotice(
        `Landed cost ${r.lc_number} created as ${r.status} — allocate to post GL.`,
      );
      setForm({
        grn_id: "",
        lc_number: "",
        lc_date: new Date().toISOString().slice(0, 10),
        description: "",
        total_amount: "",
        allocation_method: "BY_QTY",
      });
      qc.invalidateQueries({ queryKey: ["proc", "landed-costs"] });
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  return (
    <div className="space-y-4">
      {(error || notice) && (
        <div
          className={
            error
              ? "rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
              : "rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-400"
          }
        >
          {error ?? notice}
          <button
            className="ml-2 text-xs underline"
            onClick={() => {
              setError(null);
              setNotice(null);
            }}
          >
            dismiss
          </button>
        </div>
      )}

      <Card className="p-4 space-y-3">
        <h3 className="text-sm font-semibold">New Landed Cost</h3>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
          <select
            className={inputCls}
            value={form.grn_id}
            onChange={(e) => setForm({ ...form, grn_id: e.target.value })}
          >
            <option value="">Completed GRN…</option>
            {completedGrns.map((g) => (
              <option key={g.grn_id} value={g.grn_id}>
                {g.grn_number}
              </option>
            ))}
          </select>
          <input
            className={inputCls}
            placeholder="LC number"
            value={form.lc_number}
            onChange={(e) => setForm({ ...form, lc_number: e.target.value })}
          />
          <input
            type="date"
            className={inputCls}
            value={form.lc_date}
            onChange={(e) => setForm({ ...form, lc_date: e.target.value })}
          />
          <input
            className={inputCls}
            placeholder="Description"
            value={form.description}
            onChange={(e) =>
              setForm({ ...form, description: e.target.value })
            }
          />
          <input
            className={inputCls}
            placeholder="Total amount"
            value={form.total_amount}
            onChange={(e) =>
              setForm({ ...form, total_amount: e.target.value })
            }
          />
          <select
            className={inputCls}
            value={form.allocation_method}
            onChange={(e) =>
              setForm({ ...form, allocation_method: e.target.value })
            }
          >
            <option value="BY_QTY">By quantity</option>
            <option value="BY_VALUE">By value</option>
            <option value="BY_WEIGHT">By weight</option>
          </select>
        </div>
        <div className="flex justify-end">
          <Button
            size="sm"
            disabled={
              !form.grn_id ||
              !form.lc_number ||
              form.description.length < 3 ||
              !form.total_amount ||
              createLc.isPending
            }
            onClick={() => {
              setError(null);
              setNotice(null);
              createLc.mutate();
            }}
          >
            {createLc.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              "Create landed cost"
            )}
          </Button>
        </div>
      </Card>

      <Card className="divide-y divide-border">
        <div className="flex items-center justify-between px-4 py-2">
          <span className="text-sm font-semibold">
            Landed Costs ({landedCosts.data?.length ?? 0})
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => landedCosts.refetch()}
          >
            Refresh
          </Button>
        </div>
        {landedCosts.isLoading ? (
          <div className="flex justify-center p-6">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : (
          landedCosts.data?.map((lc) => (
            <div
              key={lc.id}
              className="flex items-center justify-between gap-2 px-4 py-2.5"
            >
              <div>
                <span className="text-sm font-medium">{lc.lc_number}</span>
                <span className="ml-2 text-xs text-muted-foreground">
                  {lc.allocation_method}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-sm tabular-nums text-muted-foreground">
                  {formatAmount(lc.total_amount)}
                </span>
                <Badge
                  variant={lc.status === "ALLOCATED" ? "success" : "default"}
                >
                  {lc.status}
                </Badge>
                {lc.status === "DRAFT" && (
                  <Button
                    size="sm"
                    disabled={allocate.isPending}
                    onClick={() => {
                      setError(null);
                      setNotice(null);
                      allocate.mutate(lc.id);
                    }}
                  >
                    Allocate
                  </Button>
                )}
              </div>
            </div>
          ))
        )}
      </Card>
    </div>
  );
}

/* -------------------------------- page shell -------------------------------- */

const TABS: Array<{ key: Tab; label: string }> = [
  { key: "orders", label: "Purchase Orders" },
  { key: "vendors", label: "Vendors" },
  { key: "grns", label: "GRN / Inspection" },
  { key: "bills", label: "Bills & Match" },
  { key: "payments", label: "Payments" },
  { key: "returns", label: "Returns" },
  { key: "landed-costs", label: "Landed Costs" },
];

export function ProcurementPage() {
  const [tab, setTab] = useState<Tab>("orders");

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 md:p-6">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Procurement</h1>
        <p className="text-xs text-muted-foreground">
          Purchase orders, PUTG goods receipt &amp; inspection, AP bills with
          3-way match, payments, debit-note returns, and landed costs.
        </p>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={
              tab === t.key
                ? "rounded-md bg-accent px-3 py-1.5 text-sm text-accent-foreground"
                : "rounded-md px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent/50 hover:text-foreground"
            }
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "orders" && <OrdersPanel />}
      {tab === "vendors" && <VendorsPanel />}
      {tab === "grns" && <GrnPanel />}
      {tab === "bills" && <BillsPanel />}
      {tab === "payments" && <PaymentsPanel />}
      {tab === "returns" && <ReturnsPanel />}
      {tab === "landed-costs" && <LandedCostsPanel />}
    </div>
  );
}
