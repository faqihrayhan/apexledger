/**
 * Connect screen — first-run server selection for the desktop app.
 *
 * The web UI talks to the same origin, so this screen never appears in
 * the browser. Tauri has no backend on its own origin, so the user
 * must enter the factory server address once (persisted in the server
 * store); the login page then takes over as usual.
 */

import { useState } from "react";
import { api } from "@/lib/api";
import { Button, Card, Input, Label } from "@/components/ui";
import { BookOpen, Loader2, PlugZap } from "lucide-react";
import { useServerStore } from "@/stores/server";

interface SystemStatus {
  is_initialized: boolean;
}

export function ConnectScreen() {
  const setBaseUrl = useServerStore((s) => s.setBaseUrl);
  const [url, setUrl] = useState(useServerStore.getState().baseUrl);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const candidate = url.trim();
    if (!candidate) return;
    setChecking(true);
    setError(null);
    try {
      // Probe the server before committing the URL: /system/status is
      // public and cheap. A 404 here means "not an ApexLedger server".
      await api.get<SystemStatus>("/system/status", { probeUrl: candidate });
      setBaseUrl(candidate);
    } catch {
      setError(
        "Could not reach an ApexLedger server at that address. Check the IP/port and that the backend is running.",
      );
    } finally {
      setChecking(false);
    }
};

  return (
    <Card className="w-[420px] p-2">
      <div className="mb-6 text-center">
        <div className="mb-3 inline-flex h-10 w-10 items-center justify-center rounded-md border border-border bg-secondary">
          <BookOpen className="h-5 w-5 text-primary" />
        </div>
        <h1 className="text-lg font-semibold tracking-tight">Connect to server</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Enter the address of your ApexLedger server (e.g.{" "}
          <span className="font-mono text-xs">192.168.1.100:8000</span>).
        </p>
      </div>

      <form onSubmit={submit} className="space-y-3 text-left">
        <div className="scheme-placeholder space-y-1.5">
          <Label htmlFor="server-url">Server address</Label>
          <Input
            id="server-url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="http://192.168.1.100:8000"
            required
            autoFocus
          />
        </div>

        {error && <p className="text-sm text-destructive">{error}</p>}

        <Button type="submit" className="w-full" disabled={checking || !url.trim()}>
          {checking ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlugZap className="h-4 w-4" />}
          {checking ? "Checking..." : "Connect"}
        </Button>
      </form>
    </Card>
  );
}
