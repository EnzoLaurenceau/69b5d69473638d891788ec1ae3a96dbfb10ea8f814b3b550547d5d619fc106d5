import React, { useState } from "react";
import { Button, Card, Icon, Input } from "../design-system";
import { checkToken } from "../api/client";
import { useAuth } from "./AuthContext";

// Écran d'entrée : saisie du token tenant. État vide actionnable (règle DS §6), jamais un
// écran passif. Le token n'est jamais persisté — il part directement dans le contexte mémoire.
export function Login() {
  const { setToken } = useAuth();
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async () => {
    const t = value.trim();
    if (!t) return;
    setBusy(true);
    setErr(null);
    const ok = await checkToken(t);
    setBusy(false);
    if (ok) setToken(t);
    else setErr("token refusé — vérifiez le jeton du tenant");
  };

  return (
    <div style={{
      minHeight: "100vh", display: "grid", placeItems: "center",
      background: "var(--bg)", fontFamily: "var(--font-ui)",
    }}>
      <Card style={{ width: 380, display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)" }}>
          <Icon name="flame" size={22} color="var(--accent)" />
          <span style={{ fontSize: "var(--text-h2)", fontWeight: 500, color: "var(--text-primary)" }}>
            la forge
          </span>
        </div>
        <p style={{ fontSize: "var(--text-label)", color: "var(--text-secondary)", margin: 0, lineHeight: 1.5 }}>
          collez le jeton de votre tenant pour ouvrir la console.
        </p>
        <Input
          icon="key"
          mono
          type="password"
          placeholder="token du tenant"
          value={value}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) => setValue(e.target.value)}
          onKeyDown={(e: React.KeyboardEvent) => e.key === "Enter" && submit()}
        />
        {err && (
          <span style={{ fontSize: "12px", color: "var(--status-error)", fontFamily: "var(--font-mono)" }}>
            {err}
          </span>
        )}
        <Button icon="arrow-right" onClick={submit} disabled={busy || !value.trim()}>
          {busy ? "vérification…" : "ouvrir la console"}
        </Button>
      </Card>
    </div>
  );
}
