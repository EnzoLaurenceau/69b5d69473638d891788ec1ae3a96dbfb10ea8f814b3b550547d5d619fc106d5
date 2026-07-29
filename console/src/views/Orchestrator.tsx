import React, { useEffect, useRef, useState } from "react";
import { Button, Card, Icon, Input, StatusBadge } from "../design-system";
import { ViewHeader } from "../components/Shell";
import { usePoll } from "../components/usePoll";
import { api } from "../api/client";
import { openStream, type StreamHandle } from "../api/stream";
import type { BoardColumn, BoardTask, RunStatus, StreamEvent } from "../api/types";
import { useToken } from "../auth/AuthContext";

interface LiveRun {
  runId: string;
  task: string;
  status: RunStatus;
  events: StreamEvent[];
}

// Orchestrateur : on lance un agent et on suit son exécution EN DIRECT (WS /v1/stream).
// C'est la preuve de bout en bout de la Phase 2 (un run lancé ici apparaît live).
export function Orchestrator() {
  const token = useToken();
  const [task, setTask] = useState("");
  const [run, setRun] = useState<LiveRun | null>(null);
  const streamRef = useRef<StreamHandle | null>(null);

  useEffect(() => () => streamRef.current?.close(), []);

  const launch = async () => {
    const t = task.trim();
    if (!t) return;
    streamRef.current?.close();
    const { run_id } = await api.runAgent(token, { task: t });
    setRun({ runId: run_id, task: t, status: "running", events: [] });
    setTask("");
    streamRef.current = openStream(run_id, token, {
      onEvent: (ev) =>
        setRun((prev) => {
          if (!prev || prev.runId !== run_id) return prev;
          let status = prev.status;
          if (ev.type === "run.done") status = "done";
          else if (ev.type === "run.error") status = "error";
          return { ...prev, status, events: [...prev.events, ev] };
        }),
    });
  };

  // Le board est POLLÉ (il bouge hors console : le CLI `kanban.py` l'écrit aussi).
  const board = usePoll(() => api.getBoard(token), 8000);

  const columns: { key: BoardColumn; label: string; icon: string }[] = [
    { key: "todo", label: "à faire", icon: "circle" },
    { key: "doing", label: "en cours", icon: "player-play" },
    { key: "done", label: "terminé", icon: "circle-check" },
    { key: "blocked", label: "bloqué", icon: "ban" },
  ];

  // Le run en direct n'est pas une tâche du board : il vit dans la colonne qui
  // correspond à SON état, en tête, pour rester ce qu'il est — l'exécution en cours.
  const runColumn = (): BoardColumn | null => {
    if (!run) return null;
    if (run.status === "queued") return "todo";
    if (run.status === "running") return "doing";
    return ["done", "error"].includes(run.status) ? "done" : null;
  };

  const tasksOf = (key: BoardColumn): BoardTask[] => board.data?.columns?.[key] ?? [];
  const empty = !run && !board.data;

  return (
    <>
      <ViewHeader
        title="orchestrateur"
        action={
          <div style={{ display: "flex", gap: "var(--space-2)", width: 420 }}>
            <div style={{ flex: 1 }}>
              <Input
                icon="terminal-2"
                placeholder="décrivez une tâche pour la forge"
                value={task}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setTask(e.target.value)}
                onKeyDown={(e: React.KeyboardEvent) => e.key === "Enter" && launch()}
              />
            </div>
            <Button icon="bolt" onClick={launch} disabled={!task.trim()}>lancer un agent</Button>
          </div>
        }
      />

      {/* Un board qui n'est pas celui du tenant doit le dire : sinon on croit lire le sien. */}
      {board.data && (
        <Card style={{ marginBottom: "var(--space-4)", display: "flex", alignItems: "center", gap: "var(--space-3)", flexWrap: "wrap" }}>
          <Icon name="layout-kanban" size={18} color="var(--forge-blue-400)" />
          <span style={{ fontSize: "14px", color: "var(--text-secondary)" }}>
            {board.data.parent_task || "board"}
          </span>
          {board.data.scope === "global" && (
            <StatusBadge status="warn">board opérateur (global), pas celui du tenant</StatusBadge>
          )}
          {board.data.note && <StatusBadge status="idle">{board.data.note}</StatusBadge>}
        </Card>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "var(--space-4)" }}>
        {columns.map((c) => {
          const tasks = tasksOf(c.key);
          return (
            <div key={c.key}>
              <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", marginBottom: "var(--space-3)", color: "var(--text-secondary)", fontSize: "13px" }}>
                <Icon name={c.icon} size={15} color="var(--text-muted)" />
                {c.label}
                <span style={{ fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>{tasks.length || ""}</span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)", minHeight: 120 }}>
                {runColumn() === c.key && run && <RunCard run={run} live={run.status === "running"} />}
                {tasks.map((t) => <TaskCard key={t.id} task={t} />)}
                {tasks.length === 0 && runColumn() !== c.key && <Empty />}
              </div>
            </div>
          );
        })}
      </div>

      {empty && !board.loading && (
        <div style={{ marginTop: "var(--space-4)", color: "var(--text-muted)", fontSize: "13px" }}>
          aucun board et aucun run — lancez un agent, ou alimentez le kanban via
          <span style={{ fontFamily: "var(--font-mono)" }}> kanban.py</span>.
        </div>
      )}
    </>
  );
}

const TASK_BADGE: Record<string, "active" | "idle" | "info" | "error"> = {
  pending: "idle", in_progress: "active", done: "info", blocked: "error",
};

function TaskCard({ task }: { task: BoardTask }) {
  return (
    <Card style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "var(--space-2)" }}>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--text-muted)" }}>{task.id}</span>
        {/* Statut BRUT : si le serveur en invente un, on le voit au lieu de le lisser. */}
        <StatusBadge status={TASK_BADGE[task.status] ?? "idle"}>{task.est || task.status}</StatusBadge>
      </div>
      <span style={{ fontSize: "13px", color: "var(--text-primary)", lineHeight: 1.4 }}>{task.name}</span>
      {task.block_reason && (
        <span style={{ fontSize: "12px", color: "var(--forge-coral-400)" }}>{task.block_reason}</span>
      )}
    </Card>
  );
}

function Empty() {
  return (
    <div style={{
      border: "0.5px dashed var(--border-strong)", borderRadius: "var(--radius-lg)",
      padding: "var(--space-4)", color: "var(--text-muted)", fontSize: "13px", textAlign: "center",
    }}>
      —
    </div>
  );
}

function RunCard({ run, live = false }: { run: LiveRun; live?: boolean }) {
  const badge = run.status === "error" ? "error" : run.status === "done" ? "info" : "active";
  const label = run.status === "error" ? "erreur" : run.status === "done" ? "terminé" : "en cours";
  return (
    <Card style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "var(--space-2)" }}>
        <span style={{ fontSize: "14px", color: "var(--text-primary)" }}>{run.task}</span>
        <StatusBadge status={badge} pulse={live}>{label}</StatusBadge>
      </div>
      <span style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--text-muted)" }}>{run.runId}</span>
      {run.events.length > 0 && (
        <div style={{
          background: "var(--bg)", borderRadius: "var(--radius-md)", padding: "var(--space-3)",
          maxHeight: 220, overflow: "auto", display: "flex", flexDirection: "column", gap: 4,
        }}>
          {run.events.slice(-40).map((ev) => (
            <div key={ev.seq} style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--text-secondary)", lineHeight: 1.5 }}>
              <span style={{ color: "var(--forge-blue-400)" }}>{ev.type}</span>{" "}
              {shortData(ev)}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function shortData(ev: StreamEvent): string {
  const d = ev.data || {};
  if (typeof d.content === "string") return d.content.slice(0, 120);
  if (typeof d.delta === "string") return d.delta.slice(0, 120);
  if (typeof d.error === "string") return d.error.slice(0, 120);
  const s = JSON.stringify(d);
  return s === "{}" ? "" : s.slice(0, 120);
}
