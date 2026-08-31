/**
 * Login screen — JWT authentication.
 *
 * Checks system status on mount: if the instance is not yet initialized,
 * the first-boot setup wizard is shown instead of the login form.
 */

import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { useAuthStore } from "@/stores/auth";
import { Button, Card, Input, Label } from "@/components/ui";
import { BookOpen, Loader2, LogIn } from "lucide-react";

/* --------------------------------- types -------------------------------- */

interface LoginResponse {
  access_token: string;
  token_type: string;
  user_id: string;
  role: string;
}

interface SetupStatus {
  is_initialized: boolean;
}

interface SetupRequest {
  entity_code: string;
  entity_name: string;
  base_currency_code: string;
  admin_email: string;
  admin_full_name: string;
  admin_password: string;
  fiscal_year: number;
}

interface SetupResponse {
  entity_id: string;
  entity_code: string;
  user_id: string;
  fiscal_year_id: string;
  periods_created: number;
  access_token: string;
}

/* ------------------------------ helpers --------------------------------- */

function formatError(err: unknown): string {
  if (err instanceof ApiError) {
    const detail = err.detail as unknown as { message?: string };
    if (typeof detail === "object" && detail?.message) return detail.message;
    if (typeof detail === "string" && detail) return detail;
  }
  return "Something went wrong. Please try again.";
}

/* ------------------------------ setup wizard ---------------------------- */

function SetupWizard() {
  const setAuth = useAuthStore((s) => s.setAuth);
  const [form, setForm] = useState<SetupRequest>({
    entity_code: "",
    entity_name: "",
    base_currency_code: "IDR",
    admin_email: "",
    admin_full_name: "",
    admin_password: "",
    fiscal_year: new Date().getFullYear(),
  });

  const setup = useMutation({
    mutationFn: (payload: SetupRequest) =>
      api.post<SetupResponse>("/system/setup", payload),
    onSuccess: (res) => {
      setAuth({
        token: res.access_token,
        userId: res.user_id,
        role: "SUPER_ADMIN",
      });
    },
  });

  const update =
    (field: keyof SetupRequest) =>
    (
      e: React.ChangeEvent<HTMLInputElement>,
    ) => {
      setForm((prev) => ({ ...prev, [field]: e.target.value }));
    };

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setup.mutate(form);
  };

  return (
    <Card className="w-[420px] p-2">
      <div className="mb-6 text-center">
        <div className="mb-3 inline-flex h-10 w-10 items-center justify-center rounded-md border border-border bg-secondary">
          <BookOpen className="h-5 w-5 text-primary" />
        </div>
        <h1 className="text-lg font-semibold tracking-tight">
          Welcome to ApexLedger
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Create your entity and first administrator to get started.
        </p>
      </div>

      <form onSubmit={onSubmit} className="space-y-3 text-left">
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="entity_code">Entity code</Label>
            <Input
              id="entity_code"
              value={form.entity_code}
              onChange={update("entity_code")}
              placeholder="ACME"
              required
              minLength={2}
              maxLength={20}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="entity_name">Entity name</Label>
            <Input
              id="entity_name"
              value={form.entity_name}
              onChange={update("entity_name")}
              placeholder="ACME Manufacturing"
              required
              maxLength={150}
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="admin_full_name">Admin full name</Label>
            <Input
              id="admin_full_name"
              value={form.admin_full_name}
              onChange={update("admin_full_name")}
              placeholder="Faqih Raihan"
              required
              maxLength={150}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="admin_email">Admin email</Label>
            <Input
              id="admin_email"
              type="email"
              value={form.admin_email}
              onChange={update("admin_email")}
              placeholder="admin@example.com"
              required
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="base_currency_code">Base currency</Label>
            <Input
              id="base_currency_code"
              value={form.base_currency_code}
              onChange={update("base_currency_code")}
              placeholder="IDR"
              required
              minLength={3}
              maxLength={3}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="fiscal_year">Fiscal year</Label>
            <Input
              id="fiscal_year"
              type="number"
              value={form.fiscal_year}
              onChange={update("fiscal_year")}
              required
              min={2000}
              max={2100}
            />
          </div>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="admin_password">Admin password</Label>
          <Input
            id="admin_password"
            type="password"
            value={form.admin_password}
            onChange={update("admin_password")}
            placeholder="Minimum 8 characters"
            required
            minLength={8}
            maxLength={128}
          />
        </div>

        {setup.isError && (
          <p className="text-sm text-destructive">{formatError(setup.error)}</p>
        )}

        <Button
          type="submit"
          className="w-full"
          disabled={setup.isPending || !form.entity_code || !form.admin_email}
        >
          {setup.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <LogIn className="h-4 w-4" />
          )}
          Initialize ApexLedger
        </Button>
      </form>
    </Card>
  );
}

/* ------------------------------- login form ----------------------------- */

function LoginForm() {
  const setAuth = useAuthStore((s) => s.setAuth);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const login = useMutation({
    mutationFn: (credentials: { email: string; password: string }) =>
      api.post<LoginResponse>("/auth/login", credentials),
    onSuccess: (res) => {
      setAuth({
        token: res.access_token,
        userId: res.user_id,
        role: res.role,
      });
    },
  });

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    login.mutate({ email, password });
  };

  return (
    <Card className="w-[380px] p-2">
      <div className="mb-6 text-center">
        <div className="mb-3 inline-flex h-10 w-10 items-center justify-center rounded-md border border-border bg-secondary">
          <BookOpen className="h-5 w-5 text-primary" />
        </div>
        <h1 className="text-lg font-semibold tracking-tight">
          Sign in to ApexLedger
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Enter your credentials to access your ledger.
        </p>
      </div>

      <form onSubmit={onSubmit} className="space-y-3 text-left">
        <div className="space-y-1.5">
          <Label htmlFor="login-email">Email</Label>
          <Input
            id="login-email"
            type="email"
            placeholder="admin@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="login-password">Password</Label>
          <Input
            id="login-password"
            type="password"
            placeholder="Your password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </div>

        {login.isError && (
          <p className="text-sm text-destructive">{formatError(login.error)}</p>
        )}

        <Button
          type="submit"
          className="w-full"
          disabled={login.isPending || !email || !password}
        >
          {login.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <LogIn className="h-4 w-4" />
          )}
          Sign in
        </Button>
      </form>
    </Card>
  );
}

/* ------------------------------- the page ------------------------------- */

export function LoginPage() {
  const [status, setStatus] = useState<"loading" | "setup" | "login">("loading");

  useEffect(() => {
    let cancelled = false;
    api
      .get<SetupStatus>("/system/status")
      .then((res) => {
        if (!cancelled) {
          setStatus(res.is_initialized ? "login" : "setup");
        }
      })
      .catch(() => {
        // Backend unreachable — still show the login form.
        if (!cancelled) setStatus("login");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      {status === "loading" && (
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      )}
      {status === "setup" && <SetupWizard />}
      {status === "login" && <LoginForm />}
    </div>
  );
}
