/**
 * Inventory (M3) — stock on-hand, warehouse/item master data,
 * stock movements (receive / issue / transfer), and work orders
 * with COGM completion.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { Badge, Button, Card } from "@/components/ui";
import { cn } from "@/lib/utils";
import {
  ArrowLeftRight,
  Boxes,
  Factory,
  Loader2,
  Package,
  PackagePlus,
  Plus,
  Warehouse as WarehouseIcon,
} from "lucide-react";

/* --------------------------------- types --------------------------------- */

interface Warehouse {
  id: string;
  code: string;
  name: string;
  warehouse_type: string;
  is_active: boolean;
}

interface Item {
  id: string;
  item_code: string;
  item_name: string;
  item_type: string;
  costing_method: string;
  uom_base: string;
  requires_fefo: boolean;
  is_active: boolean;
  gl_inventory_account_id: string | null;
  gl_cogs_account_id: string | null;
}

interface OnHandRow {
  item_code: string;
  item_name: string;
  warehouse_code: string;
  qty_on_hand: string;
  avg_cost: string;
}

interface WorkOrder {
  id: string;
  wo_number: string;
  bom_id: string;
  item_id: string;
  warehouse_id: string;
  cost_center_id: string | null;
  qty_planned: string;
  qty_produced: string | null;
  status: string;
  journal_entry_id: string | null;
}

type Tab = "onhand" | "master" | "movements" | "workorders";

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

/* ------------------------------- on-hand tab ----------------------------- */

function OnHandPanel() {
  const [whFilter, setWhFilter] = useState("");
  const rows = useQuery({
    queryKey: ["inv-onhand", whFilter],
    queryFn: () =>
      api.get<OnHandRow[]>(
        whFilter ? `/inv/stock/on-hand?warehouse_id=${whFilter}` : "/inv/stock/on-hand",
      ),
  });
  const warehouses = useQuery({
    queryKey: ["inv-warehouses"],
    queryFn: () => api.get<Warehouse[]>("/inv/warehouses"),
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-medium flex items-center gap-2">
          <Boxes className="w-4 h-4" /> Stock on hand
        </h2>
        <select
          className={cn(inputCls, "w-56")}
          value={whFilter}
          onChange={(e) => setWhFilter(e.target.value)}
        >
          <option value="">All warehouses</option>
          {warehouses.data?.map((w) => (
            <option key={w.id} value={w.id}>
              {w.code} — {w.name}
            </option>
          ))}
        </select>
      </div>

      <Card className="divide-y">
        {rows.isLoading ? (
          <div className="p-6 text-sm text-muted-foreground">Loading…</div>
        ) : rows.data?.length === 0 ? (
          <div className="p-6 text-sm text-muted-foreground">
            No stock recorded yet. Receive stock from the Movements tab.
          </div>
        ) : (
          rows.data?.map((r) => (
            <div
              key={`${r.item_code}-${r.warehouse_code}`}
              className="p-4 flex flex-wrap items-center gap-3 text-sm"
            >
              <span className="font-mono text-xs text-muted-foreground">
                {r.item_code}
              </span>
              <span className="font-medium min-w-40">{r.item_name}</span>
              <Badge variant="default">{r.warehouse_code}</Badge>
              <span className="ml-auto">
                <span className="font-medium">{fmtQty(r.qty_on_hand)}</span>
                <span className="text-muted-foreground"> @ avg </span>
                <span className="font-medium">{formatAmount(r.avg_cost)}</span>
              </span>
            </div>
          ))
        )}
      </Card>
    </div>
  );
}

/* ------------------------------ master tab ------------------------------- */

function WarehouseForm({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState({ code: "", name: "", warehouse_type: "OUTLET" });
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      api.post("/inv/warehouses", {
        code: form.code,
        name: form.name,
        warehouse_type: form.warehouse_type,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["inv-warehouses"] });
      onDone();
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  return (
    <Card className="p-5 space-y-3">
      <h3 className="text-sm font-medium">Add warehouse</h3>
      <div className="grid grid-cols-3 gap-3">
        <input
          className={inputCls}
          placeholder="Code (e.g. WH-GA)"
          value={form.code}
          onChange={(e) => setForm({ ...form, code: e.target.value })}
        />
        <input
          className={inputCls}
          placeholder="Name"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
        />
        <select
          className={inputCls}
          value={form.warehouse_type}
          onChange={(e) => setForm({ ...form, warehouse_type: e.target.value })}
        >
          <option value="OUTLET">OUTLET</option>
          <option value="MAIN">MAIN</option>
          <option value="TRANSIT">TRANSIT</option>
        </select>
      </div>
      {error && <p className="text-xs text-destructive">{error}</p>}
      <div className="flex gap-2 justify-end">
        <Button variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        <Button
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending || !form.code || !form.name}
        >
          {mutation.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
          Save
        </Button>
      </div>
    </Card>
  );
}

function ItemForm({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState({
    item_code: "",
    item_name: "",
    item_type: "FINISHED_GOOD",
    costing_method: "MOVING_AVERAGE",
    uom_base: "PCS",
    requires_fefo: false,
  });
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => api.post("/inv/items", form),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["inv-items"] });
      onDone();
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  return (
    <Card className="p-5 space-y-3">
      <h3 className="text-sm font-medium">Add item</h3>
      <div className="grid grid-cols-3 gap-3">
        <input
          className={inputCls}
          placeholder="Item code"
          value={form.item_code}
          onChange={(e) => setForm({ ...form, item_code: e.target.value })}
        />
        <input
          className={inputCls}
          placeholder="Item name"
          value={form.item_name}
          onChange={(e) => setForm({ ...form, item_name: e.target.value })}
        />
        <input
          className={inputCls}
          placeholder="UoM (e.g. PCS / KG)"
          value={form.uom_base}
          onChange={(e) => setForm({ ...form, uom_base: e.target.value })}
        />
        <select
          className={inputCls}
          value={form.item_type}
          onChange={(e) => setForm({ ...form, item_type: e.target.value })}
        >
          <option value="FINISHED_GOOD">FINISHED_GOOD</option>
          <option value="RAW_MATERIAL">RAW_MATERIAL</option>
          <option value="SEMI_FINISHED">SEMI_FINISHED</option>
          <option value="CONSUMABLE">CONSUMABLE</option>
        </select>
        <select
          className={inputCls}
          value={form.costing_method}
          onChange={(e) => setForm({ ...form, costing_method: e.target.value })}
        >
          <option value="MOVING_AVERAGE">MOVING_AVERAGE</option>
          <option value="FIFO">FIFO</option>
        </select>
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <input
            type="checkbox"
            checked={form.requires_fefo}
            onChange={(e) => setForm({ ...form, requires_fefo: e.target.checked })}
          />
          Requires FEFO (expiry)
        </label>
      </div>
      {error && <p className="text-xs text-destructive">{error}</p>}
      <div className="flex gap-2 justify-end">
        <Button variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        <Button
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending || !form.item_code || !form.item_name || !form.uom_base}
        >
          {mutation.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
          Save
        </Button>
      </div>
    </Card>
  );
}

function MasterPanel() {
  const [showWhForm, setShowWhForm] = useState(false);
  const [showItemForm, setShowItemForm] = useState(false);

  const warehouses = useQuery({
    queryKey: ["inv-warehouses"],
    queryFn: () => api.get<Warehouse[]>("/inv/warehouses"),
  });
  const items = useQuery({
    queryKey: ["inv-items"],
    queryFn: () => api.get<Item[]>("/inv/items"),
  });

  return (
    <div className="space-y-6">
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-medium flex items-center gap-2">
            <WarehouseIcon className="w-4 h-4" /> Warehouses (
            {warehouses.data?.length ?? 0})
          </h2>
          <Button size="sm" onClick={() => setShowWhForm(!showWhForm)}>
            <Plus className="w-4 h-4" /> Add
          </Button>
        </div>
        {showWhForm && <WarehouseForm onDone={() => setShowWhForm(false)} />}
        <Card className="divide-y">
          {warehouses.isLoading ? (
            <div className="p-6 text-sm text-muted-foreground">Loading…</div>
          ) : warehouses.data?.length === 0 ? (
            <div className="p-6 text-sm text-muted-foreground">
              No warehouses yet.
            </div>
          ) : (
            warehouses.data?.map((w) => (
              <div
                key={w.id}
                className="p-4 flex flex-wrap items-center gap-3 text-sm"
              >
                <span className="font-mono text-xs text-muted-foreground">
                  {w.code}
                </span>
                <span className="font-medium">{w.name}</span>
                <Badge variant="default">{w.warehouse_type}</Badge>
                {!w.is_active && <Badge variant="destructive">INACTIVE</Badge>}
              </div>
            ))
          )}
        </Card>
      </div>

      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-medium flex items-center gap-2">
            <Package className="w-4 h-4" /> Items ({items.data?.length ?? 0})
          </h2>
          <Button size="sm" onClick={() => setShowItemForm(!showItemForm)}>
            <Plus className="w-4 h-4" /> Add
          </Button>
        </div>
        {showItemForm && <ItemForm onDone={() => setShowItemForm(false)} />}
        <Card className="divide-y">
          {items.isLoading ? (
            <div className="p-6 text-sm text-muted-foreground">Loading…</div>
          ) : items.data?.length === 0 ? (
            <div className="p-6 text-sm text-muted-foreground">
              No items yet.
            </div>
          ) : (
            items.data?.map((i) => (
              <div
                key={i.id}
                className="p-4 flex flex-wrap items-center gap-3 text-sm"
              >
                <span className="font-mono text-xs text-muted-foreground">
                  {i.item_code}
                </span>
                <span className="font-medium min-w-40">{i.item_name}</span>
                <Badge variant="default">{i.item_type}</Badge>
                <Badge variant="outline">{i.costing_method}</Badge>
                <span className="text-muted-foreground">{i.uom_base}</span>
                {i.requires_fefo && <Badge variant="outline">FEFO</Badge>}
              </div>
            ))
          )}
        </Card>
      </div>
    </div>
  );
}

/* ----------------------------- movements tab ----------------------------- */

function MovementsPanel() {
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [move, setMove] = useState<"receive" | "issue" | "transfer">("receive");

  const warehouses = useQuery({
    queryKey: ["inv-warehouses"],
    queryFn: () => api.get<Warehouse[]>("/inv/warehouses"),
  });
  const items = useQuery({
    queryKey: ["inv-items"],
    queryFn: () => api.get<Item[]>("/inv/items"),
  });

  const [form, setForm] = useState({
    item_id: "",
    warehouse_id: "",
    to_warehouse_id: "",
    qty: "",
    unit_cost: "",
    expiry_date: "",
  });

  const receive = useMutation({
    mutationFn: () =>
      api.post<{ transaction_id: string }>("/inv/stock/receive", {
        item_id: form.item_id,
        warehouse_id: form.warehouse_id,
        qty: form.qty,
        unit_cost: form.unit_cost,
        reference_type: "MANUAL",
        expiry_date: form.expiry_date || null,
      }),
    onSuccess: (r: { transaction_id: string }) => {
      qc.invalidateQueries({ queryKey: ["inv-onhand"] });
      setSuccess(`Received ${form.qty} units — transaction ${r.transaction_id.slice(0, 8)}…`);
      setForm({ ...form, qty: "", unit_cost: "", expiry_date: "" });
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  const issue = useMutation({
    mutationFn: () =>
      api.post<{ transaction_id: string; total_cost: string }>(
        "/inv/stock/issue",
        {
          item_id: form.item_id,
          warehouse_id: form.warehouse_id,
          qty: form.qty,
          reference_type: "MANUAL",
        }),
    onSuccess: (r: { transaction_id: string; total_cost: string }) => {
      qc.invalidateQueries({ queryKey: ["inv-onhand"] });
      setSuccess(`Issued ${form.qty} units — total cost ${formatAmount(r.total_cost)}`);
      setForm({ ...form, qty: "" });
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  const transfer = useMutation({
    mutationFn: () =>
      api.post<{ qty_transferred: string; unit_cost: string }>(
        "/inv/stock/transfer",
        {
          item_id: form.item_id,
          from_warehouse_id: form.warehouse_id,
          to_warehouse_id: form.to_warehouse_id,
          qty: form.qty,
        }),
    onSuccess: (r: { qty_transferred: string; unit_cost: string }) => {
      qc.invalidateQueries({ queryKey: ["inv-onhand"] });
      setSuccess(
        `Transferred ${r.qty_transferred} units @ ${formatAmount(r.unit_cost)}`,
      );
      setForm({ ...form, qty: "" });
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  const active =
    move === "receive" ? receive : move === "issue" ? issue : transfer;
  const pending = active.isPending;
  const runActive = () => {
    if (move === "receive") receive.mutate();
    else if (move === "issue") issue.mutate();
    else transfer.mutate();
  };

  const canSubmit =
    form.item_id !== "" &&
    form.warehouse_id !== "" &&
    form.qty !== "" &&
    (move === "receive"
      ? form.unit_cost !== ""
      : move === "transfer"
        ? form.to_warehouse_id !== ""
        : true);

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-medium flex items-center gap-2">
        <ArrowLeftRight className="w-4 h-4" /> Stock movements
      </h2>

      <div className="flex gap-1 border-b border-border">
        {(["receive", "issue", "transfer"] as const).map((m) => (
          <button
            key={m}
            className={cn(
              "px-4 py-2 text-sm capitalize border-b-2 -mb-px",
              move === m
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
            onClick={() => {
              setMove(m);
              setError(null);
              setSuccess(null);
            }}
          >
            {m}
          </button>
        ))}
      </div>

      <Card className="p-5 space-y-3">
        <div className="grid grid-cols-3 gap-3">
          <select
            className={inputCls}
            value={form.item_id}
            onChange={(e) => setForm({ ...form, item_id: e.target.value })}
          >
            <option value="">Select item…</option>
            {items.data?.map((i) => (
              <option key={i.id} value={i.id}>
                {i.item_code} — {i.item_name}
              </option>
            ))}
          </select>
          <select
            className={inputCls}
            value={form.warehouse_id}
            onChange={(e) => setForm({ ...form, warehouse_id: e.target.value })}
          >
            <option value="">
              {move === "transfer" ? "From warehouse…" : "Select warehouse…"}
            </option>
            {warehouses.data?.map((w) => (
              <option key={w.id} value={w.id}>
                {w.code} — {w.name}
              </option>
            ))}
          </select>
          {move === "transfer" ? (
            <select
              className={inputCls}
              value={form.to_warehouse_id}
              onChange={(e) =>
                setForm({ ...form, to_warehouse_id: e.target.value })
              }
            >
              <option value="">To warehouse…</option>
              {warehouses.data?.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.code} — {w.name}
                </option>
              ))}
            </select>
          ) : (
            <input
              className={inputCls}
              placeholder="Quantity"
              value={form.qty}
              onChange={(e) => setForm({ ...form, qty: e.target.value })}
            />
          )}
        </div>

        <div className="grid grid-cols-3 gap-3">
          {move === "receive" && (
            <>
              <input
                className={inputCls}
                placeholder="Unit cost (e.g. 10000)"
                value={form.unit_cost}
                onChange={(e) =>
                  setForm({ ...form, unit_cost: e.target.value })
                }
              />
              <input
                className={inputCls}
                type="date"
                title="Expiry date (required for FEFO items)"
                value={form.expiry_date}
                onChange={(e) =>
                  setForm({ ...form, expiry_date: e.target.value })
                }
              />
            </>
          )}
          {move === "transfer" && (
            <input
              className={inputCls}
              placeholder="Quantity"
              value={form.qty}
              onChange={(e) => setForm({ ...form, qty: e.target.value })}
            />
          )}
        </div>

        {error && <p className="text-xs text-destructive">{error}</p>}
        {success && <p className="text-xs text-primary">{success}</p>}

        <div className="flex justify-end">
          <Button
            size="sm"
            disabled={pending || !canSubmit}
            onClick={() => runActive()}
          >
            {pending && <Loader2 className="w-4 h-4 animate-spin" />}
            <span className="capitalize">{move}</span> stock
          </Button>
        </div>
      </Card>

      <p className="text-xs text-muted-foreground">
        Receive recomputes moving-average cost and creates a stock lot (expiry
        required for FEFO items). Issue burns FIFO/FEFO lots. Transfer moves
        stock between warehouses atomically.
      </p>
    </div>
  );
}

/* ---------------------------- work orders tab ---------------------------- */

function WorkOrdersPanel() {
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [completeFor, setCompleteFor] = useState<string | null>(null);
  const [qtyProduced, setQtyProduced] = useState("");

  const workOrders = useQuery({
    queryKey: ["inv-work-orders"],
    queryFn: () => api.get<WorkOrder[]>("/inv/work-orders"),
  });
  const items = useQuery({
    queryKey: ["inv-items"],
    queryFn: () => api.get<Item[]>("/inv/items"),
  });
  const warehouses = useQuery({
    queryKey: ["inv-warehouses"],
    queryFn: () => api.get<Warehouse[]>("/inv/warehouses"),
  });

  const [form, setForm] = useState({
    wo_number: "",
    bom_id: "",
    item_id: "",
    warehouse_id: "",
    qty_planned: "",
    direct_labor_cost: "",
    gl_accrued_labor_account_id: "",
    driver_qty_used: "",
  });

  const [showForm, setShowForm] = useState(false);

  const createWo = useMutation({
    mutationFn: () =>
      api.post("/inv/work-orders", {
        wo_number: form.wo_number,
        bom_id: form.bom_id,
        item_id: form.item_id,
        warehouse_id: form.warehouse_id,
        qty_planned: form.qty_planned,
        direct_labor_cost: form.direct_labor_cost || "0",
        gl_accrued_labor_account_id: form.gl_accrued_labor_account_id || null,
        driver_qty_used: form.driver_qty_used || "0",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["inv-work-orders"] });
      setShowForm(false);
      setForm({
        wo_number: "",
        bom_id: "",
        item_id: "",
        warehouse_id: "",
        qty_planned: "",
        direct_labor_cost: "",
        gl_accrued_labor_account_id: "",
        driver_qty_used: "",
      });
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  const complete = useMutation({
    mutationFn: (body: { id: string; qty: string }) =>
      api.post<{
        work_order_id: string;
        cogm: string;
        unit_cost: string;
      }>(`/inv/work-orders/${body.id}/complete`, {
        qty_produced: body.qty,
      }),
    onSuccess: (r: {
      work_order_id: string;
      cogm: string;
      unit_cost: string;
    }) => {
      qc.invalidateQueries({ queryKey: ["inv-work-orders"] });
      setResult(
        `COGM ${formatAmount(r.cogm)} — unit cost ${formatAmount(r.unit_cost)}`,
      );
      setCompleteFor(null);
      setQtyProduced("");
    },
    onError: (e: ApiError) => setError(e.uiMessage),
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-medium flex items-center gap-2">
          <Factory className="w-4 h-4" /> Work orders (
          {workOrders.data?.length ?? 0})
        </h2>
        <Button size="sm" onClick={() => setShowForm(!showForm)}>
          <Plus className="w-4 h-4" /> New
        </Button>
      </div>

      {showForm && (
        <Card className="p-5 space-y-3">
          <h3 className="text-sm font-medium">Create work order</h3>
          <div className="grid grid-cols-3 gap-3">
            <input
              className={inputCls}
              placeholder="WO number (e.g. WO-2026-001)"
              value={form.wo_number}
              onChange={(e) => setForm({ ...form, wo_number: e.target.value })}
            />
            <input
              className={inputCls}
              placeholder="BOM UUID"
              value={form.bom_id}
              onChange={(e) => setForm({ ...form, bom_id: e.target.value })}
            />
            <input
              className={inputCls}
              placeholder="Qty planned"
              value={form.qty_planned}
              onChange={(e) => setForm({ ...form, qty_planned: e.target.value })}
            />
            <select
              className={inputCls}
              value={form.item_id}
              onChange={(e) => setForm({ ...form, item_id: e.target.value })}
            >
              <option value="">Output item (FG)…</option>
              {items.data?.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.item_code} — {i.item_name}
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
              placeholder="Direct labor cost"
              value={form.direct_labor_cost}
              onChange={(e) =>
                setForm({ ...form, direct_labor_cost: e.target.value })
              }
            />
            <input
              className={inputCls}
              placeholder="Accrued labor account UUID"
              value={form.gl_accrued_labor_account_id}
              onChange={(e) =>
                setForm({ ...form, gl_accrued_labor_account_id: e.target.value })
              }
            />
            <input
              className={inputCls}
              placeholder="Driver qty used (FOH basis)"
              value={form.driver_qty_used}
              onChange={(e) =>
                setForm({ ...form, driver_qty_used: e.target.value })
              }
            />
          </div>
          <p className="text-xs text-muted-foreground">
            BOM and cost center IDs are UUIDs from the database (BOM master CRUD
            is API-managed; paste the UUID here).
          </p>
          {error && <p className="text-xs text-destructive">{error}</p>}
          <div className="flex justify-end">
            <Button
              size="sm"
              disabled={
                createWo.isPending ||
                !form.wo_number ||
                !form.bom_id ||
                !form.item_id ||
                !form.warehouse_id ||
                !form.qty_planned
              }
              onClick={() => createWo.mutate()}
            >
              {createWo.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
              Create
            </Button>
          </div>
        </Card>
      )}

      <Card className="divide-y">
        {workOrders.isLoading ? (
          <div className="p-6 text-sm text-muted-foreground">Loading…</div>
        ) : workOrders.data?.length === 0 ? (
          <div className="p-6 text-sm text-muted-foreground">
            No work orders yet.
          </div>
        ) : (
          workOrders.data?.map((w) => (
            <div
              key={w.id}
              className="p-4 flex flex-wrap items-center gap-3 text-sm"
            >
              <span className="font-mono text-xs text-muted-foreground">
                {w.wo_number}
              </span>
              <Badge
                variant={
                  w.status === "COMPLETED"
                    ? "success"
                    : w.status === "DRAFT"
                      ? "default"
                      : "outline"
                }
              >
                {w.status}
              </Badge>
              <span className="text-muted-foreground">
                planned {fmtQty(w.qty_planned)}
              </span>
              {w.qty_produced && (
                <span className="text-muted-foreground">
                  produced {fmtQty(w.qty_produced)}
                </span>
              )}
              {w.journal_entry_id && (
                <Badge variant="success">POSTED</Badge>
              )}
              {w.status === "DRAFT" && (
                <div className="ml-auto flex items-center gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      setCompleteFor(w.id);
                      setQtyProduced("");
                      setResult(null);
                    }}
                  >
                    <PackagePlus className="w-4 h-4" /> Complete
                  </Button>
                </div>
              )}
            </div>
          ))
        )}
      </Card>

      {completeFor && (
        <Card className="p-5 space-y-3">
          <h3 className="text-sm font-medium">
            Complete work order — produced quantity
          </h3>
          <div className="flex gap-3 items-center">
            <input
              className={cn(inputCls, "w-40")}
              placeholder="Qty produced"
              value={qtyProduced}
              onChange={(e) => setQtyProduced(e.target.value)}
            />
            <Button
              size="sm"
              disabled={!qtyProduced || complete.isPending}
              onClick={() =>
                complete.mutate({ id: completeFor, qty: qtyProduced })
              }
            >
              {complete.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
              Complete &amp; post COGM
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setCompleteFor(null)}>
              Cancel
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Consumes BOM components (prorata by yield + waste), allocates labor
            and FOH, computes COGM, and posts the GL entry atomically.
          </p>
        </Card>
      )}

      {result && <p className="text-xs text-primary">{result}</p>}
      {!showForm && error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}

/* --------------------------------- page ---------------------------------- */

export function InventoryPage() {
  const [tab, setTab] = useState<Tab>("onhand");

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-medium">Inventory</h1>
          <p className="text-sm text-muted-foreground">
            Stock levels, master data, movements, and work orders — moving
            average / FIFO / FEFO handled by the engine.
          </p>
        </div>
      </div>

      <div className="flex gap-1 border-b border-border">
        {(["onhand", "master", "movements", "workorders"] as Tab[]).map((t) => (
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
            {t === "workorders" ? "work orders" : t}
          </button>
        ))}
      </div>

      {tab === "onhand" && <OnHandPanel />}
      {tab === "master" && <MasterPanel />}
      {tab === "movements" && <MovementsPanel />}
      {tab === "workorders" && <WorkOrdersPanel />}
    </div>
  );
}
