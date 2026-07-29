import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Card } from "../design-system";
import { ViewHeader } from "../components/Shell";
import { api } from "../api/client";
import type { GraphData, GraphNode, GraphEdge } from "../api/types";
import { useToken } from "../auth/AuthContext";

// Neural map — RENDU CANVAS, pensé pour les MILLIERS de nœuds du graphe Forge (le SVG
// radial ne tenait pas l'échelle). Idées reprises des moteurs de graph intelligence :
//   - LemonGraph : nœuds typés + colorés, panneau "entity details", pivot depuis une entité ;
//   - XKeyscore / DataWave : query builder (recherche + filtres) pour naviguer à grande échelle,
//     "activity overview" (stats), correlation graph.
// Tenu au budget Forge : 0 dépendance graphe, layout déterministe clustered-par-type,
// pan/zoom maison. Statique (pas de simulation) → lisible et reproductible.

const TYPES = ["Agent", "Project", "Concept", "MemoryNode", "Decision", "Repository"] as const;
const TYPE_VAR: Record<string, string> = {
  Agent: "--forge-coral-400", Project: "--forge-teal-400", Concept: "--forge-blue-400",
  MemoryNode: "--forge-amber-400", Decision: "--forge-red-400", Repository: "--text-secondary",
};
const REL_TYPES = ["EXECUTES", "RECALLS", "LINKS_TO", "DEVIATION_FROM", "PRODUCED_BY",
  "DEPENDS_ON", "CITES", "REFERENCES", "HOSTS_TOOL", "USES"];

// Sous-groupes ("régions" niveau 2) par type — miroir de _SUBGROUP_FIELD côté backend.
// Agent = role_tag (9). Sert au graphe d'exemple ET de libellé de champ dans le volet.
const SAMPLE_GROUPS: Record<string, string[]> = {
  Agent: ["orchestrator", "backend", "frontend", "research", "security", "data", "devops", "qa", "writer"],
  Project: ["active", "done", "queued", "error"],
  Concept: ["technical", "product", "legal", "ops"],
  MemoryNode: ["episodic", "semantic", "procedural"],
  Decision: ["accepted", "proposed", "superseded"],
  Repository: ["python", "rust", "typescript", "go"],
};
const GROUP_FIELD_LABEL: Record<string, string> = {
  Agent: "rôle", Project: "statut", Concept: "catégorie",
  MemoryNode: "type mémoire", Decision: "statut", Repository: "langage",
};

const GOLDEN = Math.PI * (3 - Math.sqrt(5));

function cssVar(name: string, fallback = "#888"): string {
  if (typeof window === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

function nodeKey(n: GraphNode): string {
  for (const k of ["key", "name", "id", "adr_id", "label", "title"]) {
    const v = n[k];
    if (typeof v === "string" && v) return v;
  }
  return "node";
}

// Graphe d'exemple synthétique à grande échelle : prouve que la carte tient les milliers de
// nœuds quand le graphe réel est vide (Kuzu non peuplé). Interne/démo — clic explicite.
function buildSample(n = 2400): GraphData {
  const nodes: GraphNode[] = [];
  const edges: GraphEdge[] = [];
  const stats: Record<string, number> = {};
  const perType: Record<string, number> = {};
  for (let i = 0; i < n; i++) {
    const t = TYPES[i % TYPES.length];
    stats[t] = (stats[t] ?? 0) + 1;
    const ti = perType[t] = (perType[t] ?? 0) + 1;   // index PAR TYPE (évite l'aliasing 6↔9)
    const groups = SAMPLE_GROUPS[t] ?? [""];
    nodes.push({ type: t, key: `${t.toLowerCase()}-${i}`, group: groups[ti % groups.length] });
  }
  // quelques relations plausibles (chaînage local) pour montrer les arêtes sans tout saturer
  for (let i = 0; i < n; i += 3) {
    const a = nodes[i], b = nodes[(i * 7 + 5) % n];
    if (a.key !== b.key) {
      edges.push({ source: a.key!, target: b.key!, type: REL_TYPES[i % REL_TYPES.length],
        source_type: a.type, target_type: b.type });
    }
  }
  return { nodes, edges, stats };
}

interface P { x: number; y: number; type: string }

export function NeuralMap() {
  const token = useToken();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [data, setData] = useState<GraphData>({ nodes: [], edges: [], stats: {} });
  const [loading, setLoading] = useState(true);

  // Query builder
  const [search, setSearch] = useState("");
  const [typeOff, setTypeOff] = useState<Set<string>>(new Set());
  const [relOff, setRelOff] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<string | null>(null);
  // Zone focalisée (niveau 1 "continent") : clic sur un label de zone → on entre dedans.
  const [focusZone, setFocusZone] = useState<string | null>(null);
  // Sous-groupe sélectionné dans le volet de tri (niveau 2 "région" dans la zone focalisée).
  const [groupFilter, setGroupFilter] = useState<string | null>(null);

  // Caméra (pan/zoom) — refs pour éviter de re-render à chaque frame.
  const cam = useRef({ x: 0, y: 0, zoom: 1 });
  const drag = useRef<{ x: number; y: number } | null>(null);
  const anim = useRef<number | null>(null);           // handle rAF du vol de caméra en cours
  const zoneHit = useRef<{ type: string; sx: number; sy: number; w: number }[]>([]); // labels de zone à l'écran (hit-test)
  const [, force] = useState(0);
  const redraw = useCallback(() => force((k) => k + 1), []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await api.getGraph(token);
      setData(d?.nodes?.length ? d : { nodes: [], edges: [], stats: {} });
    } catch {
      setData({ nodes: [], edges: [], stats: {} });
    }
    setLoading(false);
  }, [token]);

  useEffect(() => { void load(); }, [load]);

  // Layout déterministe : clusters par type (LemonGraph "communities"), packing phyllotaxique.
  const layout = useMemo(() => {
    const pos = new Map<string, P>();
    const byType = new Map<string, GraphNode[]>();
    data.nodes.forEach((n) => {
      const t = n.type ?? "?";
      if (!byType.has(t)) byType.set(t, []);
      byType.get(t)!.push(n);
    });
    const types = [...byType.keys()];
    const RING = 1600;
    types.forEach((t, ti) => {
      const ca = (ti / Math.max(1, types.length)) * Math.PI * 2 - Math.PI / 2;
      const ccx = Math.cos(ca) * RING, ccy = Math.sin(ca) * RING;
      const arr = byType.get(t)!;
      const spread = 60 + 34 * Math.sqrt(arr.length);
      arr.forEach((n, j) => {
        const r = spread * Math.sqrt((j + 0.5) / arr.length);
        const a = j * GOLDEN;
        pos.set(nodeKey(n), { x: ccx + r * Math.cos(a), y: ccy + r * Math.sin(a), type: t });
      });
    });
    return pos;
  }, [data]);

  // Zones = "continents" niveau 1. Centroïde + rayon de chaque cluster de type, calculés
  // À PARTIR des positions réelles du layout (pas de la formule de packing → zéro drift si le
  // layout change). Chaque type présent devient une zone, ce qui couvre 100% des nœuds.
  const zones = useMemo(() => {
    const sum = new Map<string, { sx: number; sy: number; n: number }>();
    layout.forEach((p) => {
      const a = sum.get(p.type) ?? { sx: 0, sy: 0, n: 0 };
      a.sx += p.x; a.sy += p.y; a.n += 1; sum.set(p.type, a);
    });
    const center = new Map<string, { cx: number; cy: number }>();
    sum.forEach((a, t) => center.set(t, { cx: a.sx / a.n, cy: a.sy / a.n }));
    const rad = new Map<string, number>();
    layout.forEach((p) => {
      const c = center.get(p.type)!;
      rad.set(p.type, Math.max(rad.get(p.type) ?? 0, Math.hypot(p.x - c.cx, p.y - c.cy)));
    });
    const out: { type: string; cx: number; cy: number; r: number; n: number }[] = [];
    sum.forEach((a, t) => {
      const c = center.get(t)!;
      out.push({ type: t, cx: c.cx, cy: c.cy, r: (rad.get(t) ?? 40) + 26, n: a.n });
    });
    return out;
  }, [layout]);

  // Clé → sous-groupe (role/status/…), pour le volet de tri et le filtrage niveau 2.
  const groupOf = useMemo(() => {
    const m = new Map<string, string>();
    data.nodes.forEach((n) => m.set(nodeKey(n), typeof n.group === "string" ? n.group : ""));
    return m;
  }, [data]);

  // Filtrage (query builder) : type actif, texte, sous-groupe (si zone focalisée), — et
  // relations dont les deux bouts restent.
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const keys = new Set<string>();
    data.nodes.forEach((n) => {
      const k = nodeKey(n);
      if (typeOff.has(n.type ?? "?")) return;
      if (q && !k.toLowerCase().includes(q)) return;
      if (focusZone && groupFilter && n.type === focusZone && (groupOf.get(k) ?? "") !== groupFilter) return;
      keys.add(k);
    });
    const edges = data.edges.filter(
      (e) => keys.has(e.source) && keys.has(e.target) && !relOff.has(e.type ?? ""),
    );
    const degree = new Map<string, number>();
    edges.forEach((e) => {
      degree.set(e.source, (degree.get(e.source) ?? 0) + 1);
      degree.set(e.target, (degree.get(e.target) ?? 0) + 1);
    });
    return { keys, edges, degree };
  }, [data, search, typeOff, relOff, focusZone, groupFilter, groupOf]);

  // Vol de caméra animé (easeOutCubic). instant=true pose la caméra sans transition
  // (chargement initial). Sinon on interpole ~420ms → sensation "on entre dans la zone".
  const flyTo = useCallback((tx: number, ty: number, tz: number, instant = false) => {
    if (anim.current) cancelAnimationFrame(anim.current);
    if (instant) { cam.current = { x: tx, y: ty, zoom: tz }; redraw(); return; }
    const start = { ...cam.current }, t0 = performance.now(), dur = 420;
    const step = (now: number) => {
      const k = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - k, 3);
      cam.current = {
        x: start.x + (tx - start.x) * e, y: start.y + (ty - start.y) * e,
        zoom: start.zoom + (tz - start.zoom) * e,
      };
      redraw();
      if (k < 1) anim.current = requestAnimationFrame(step);
    };
    anim.current = requestAnimationFrame(step);
  }, [redraw]);

  // Ajuste la caméra pour tout voir (au chargement / reset).
  const fit = useCallback((instant = false) => {
    const cvs = canvasRef.current; if (!cvs) return;
    const w = cvs.clientWidth, h = cvs.clientHeight;
    // Garde-fou : si le canvas n'a pas encore de dimensions (vue montée hors layout, fenêtre
    // 0px…), NE PAS calculer — un zoom=0 écraserait tout au centre. On réessaiera au prochain fit.
    if (w <= 0 || h <= 0) return;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    filtered.keys.forEach((k) => {
      const p = layout.get(k); if (!p) return;
      minX = Math.min(minX, p.x); minY = Math.min(minY, p.y);
      maxX = Math.max(maxX, p.x); maxY = Math.max(maxY, p.y);
    });
    if (!isFinite(minX)) { flyTo(0, 0, 1, instant); return; }
    const gw = maxX - minX || 1, gh = maxY - minY || 1;
    const zoom = Math.max(0.02, Math.min(w / (gw + 160), h / (gh + 160), 2)); // jamais 0
    flyTo((minX + maxX) / 2, (minY + maxY) / 2, zoom, instant);
  }, [filtered, layout, flyTo]);

  // Entrer dans une zone : cadre le cluster du type dans le canvas, vol animé.
  const zoomToZone = useCallback((type: string) => {
    const z = zones.find((x) => x.type === type); const cvs = canvasRef.current;
    if (!z || !cvs) return;
    const zoom = Math.min(cvs.clientWidth / (z.r * 2 + 120), cvs.clientHeight / (z.r * 2 + 120), 4);
    setFocusZone(type); setGroupFilter(null); setSelected(null); flyTo(z.cx, z.cy, zoom);
  }, [zones, flyTo]);

  const overview = useCallback(() => { setFocusZone(null); setGroupFilter(null); fit(); }, [fit]);

  // Sous-groupes ("régions") de la zone focalisée : valeurs distinctes de `group` + effectifs,
  // pour peupler le volet de tri. Vide hors focus.
  const zoneGroups = useMemo(() => {
    if (!focusZone) return [];
    const count = new Map<string, number>();
    data.nodes.forEach((n) => {
      if (n.type !== focusZone) return;
      const g = (typeof n.group === "string" && n.group) ? n.group : "—";
      count.set(g, (count.get(g) ?? 0) + 1);
    });
    return [...count.entries()].map(([group, n]) => ({ group, n })).sort((a, b) => b.n - a.n);
  }, [focusZone, data]);

  useEffect(() => { fit(true); /* eslint-disable-next-line */ }, [data]);

  // Le canvas peut être monté à 0px (fenêtre étroite / panneau replié) puis gagner sa largeur.
  // On observe ses dimensions : re-dimensionne le backing store (redraw) et refit si la caméra
  // est encore dégénérée (zoom 0). Sans ça la carte resterait écrasée au centre.
  useEffect(() => {
    const cvs = canvasRef.current;
    if (!cvs || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => { if (cam.current.zoom <= 0) fit(true); else redraw(); });
    ro.observe(cvs);
    return () => ro.disconnect();
  }, [fit, redraw]);

  const neighbors = useMemo(() => {
    if (!selected) return null;
    const set = new Set<string>(); const rels: GraphEdge[] = [];
    filtered.edges.forEach((e) => {
      if (e.source === selected) { set.add(e.target); rels.push(e); }
      else if (e.target === selected) { set.add(e.source); rels.push(e); }
    });
    return { set, rels };
  }, [selected, filtered]);

  // ── Rendu canvas ─────────────────────────────────────────────────────────────
  useEffect(() => {
    const cvs = canvasRef.current; if (!cvs) return;
    const dpr = window.devicePixelRatio || 1;
    const w = cvs.clientWidth, h = cvs.clientHeight;
    cvs.width = w * dpr; cvs.height = h * dpr;
    const ctx = cvs.getContext("2d"); if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const colors: Record<string, string> = {};
    TYPES.forEach((t) => (colors[t] = cssVar(TYPE_VAR[t])));
    const muted = cssVar("--text-muted", "#888");
    const strong = cssVar("--border-strong", "#333");
    const hot = cssVar("--forge-coral-400", "#e76a4b");
    const { x: cx, y: cy, zoom } = cam.current;
    const toS = (p: P) => ({ x: (p.x - cx) * zoom + w / 2, y: (p.y - cy) * zoom + h / 2 });

    // ── Zones (continents niveau 1) : halo coloré + label cliquable ──────────────
    // Chaque type = un continent. Dessiné DERRIÈRE arêtes/nœuds. Le label est un point
    // d'entrée : un clic dessus vole dans la zone (voir onUp → zoneHit).
    zoneHit.current = [];
    zones.forEach((z) => {
      if (typeOff.has(z.type)) return;
      const c = toS({ x: z.cx, y: z.cy, type: z.type });
      const rr = z.r * zoom;
      const col = colors[z.type] ?? muted;
      const dimZ = focusZone && focusZone !== z.type;
      ctx.fillStyle = col;
      ctx.globalAlpha = dimZ ? 0.04 : 0.08;
      ctx.beginPath(); ctx.arc(c.x, c.y, rr, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = col; ctx.lineWidth = 1; ctx.setLineDash([4, 4]);
      ctx.globalAlpha = dimZ ? 0.1 : 0.35;
      ctx.beginPath(); ctx.arc(c.x, c.y, rr, 0, Math.PI * 2); ctx.stroke();
      ctx.setLineDash([]);
      const label = `${z.type.toLowerCase()} · ${z.n}`;
      const ly = Math.max(14, c.y - rr - 8); // clampé pour ne jamais sortir en haut du canvas
      ctx.globalAlpha = dimZ ? 0.3 : 1;
      ctx.fillStyle = col; ctx.font = "600 12px ui-sans-serif, system-ui, sans-serif";
      const lw = ctx.measureText(label).width;
      ctx.fillText(label, c.x - lw / 2, ly);
      zoneHit.current.push({ type: z.type, sx: c.x, sy: ly, w: lw });
    });
    ctx.globalAlpha = 1;

    // Arêtes
    ctx.lineWidth = 0.6;
    filtered.edges.forEach((e) => {
      const a = layout.get(e.source), b = layout.get(e.target); if (!a || !b) return;
      const A = toS(a), B = toS(b);
      const isHot = selected && (e.source === selected || e.target === selected);
      ctx.strokeStyle = isHot ? hot : strong;
      ctx.globalAlpha = selected ? (isHot ? 0.9 : 0.06) : 0.28;
      ctx.beginPath(); ctx.moveTo(A.x, A.y); ctx.lineTo(B.x, B.y); ctx.stroke();
    });
    ctx.globalAlpha = 1;

    // Nœuds
    const R = 3.2;
    const showLabels = filtered.keys.size <= 140 || zoom > 1.6;
    filtered.keys.forEach((k) => {
      const p = layout.get(k); if (!p) return;
      const S = toS(p);
      if (S.x < -20 || S.x > w + 20 || S.y < -20 || S.y > h + 20) return; // cull hors écran
      const isSel = selected === k;
      const outOfZone = focusZone && p.type !== focusZone;
      const dim = (selected && !isSel && !(neighbors && neighbors.set.has(k))) || !!outOfZone;
      ctx.globalAlpha = dim ? 0.15 : 1;
      ctx.fillStyle = colors[p.type] ?? muted;
      ctx.beginPath(); ctx.arc(S.x, S.y, isSel ? R + 2.5 : R, 0, Math.PI * 2); ctx.fill();
      if (isSel) { ctx.strokeStyle = cssVar("--text-primary", "#fff"); ctx.lineWidth = 1.5; ctx.stroke(); }
      if (showLabels || isSel || (neighbors && neighbors.set.has(k))) {
        ctx.globalAlpha = dim ? 0.2 : 0.9;
        ctx.fillStyle = muted; ctx.font = "10px ui-monospace, monospace";
        ctx.fillText(k.slice(0, 18), S.x + 6, S.y + 3);
      }
    });
    ctx.globalAlpha = 1;
  });

  // ── Interactions ─────────────────────────────────────────────────────────────
  const pick = useCallback((mx: number, my: number): string | null => {
    const cvs = canvasRef.current; if (!cvs) return null;
    const w = cvs.clientWidth, h = cvs.clientHeight;
    const { x: cx, y: cy, zoom } = cam.current;
    const wx = (mx - w / 2) / zoom + cx, wy = (my - h / 2) / zoom + cy;
    let best: string | null = null, bestD = (10 / zoom) ** 2;
    filtered.keys.forEach((k) => {
      const p = layout.get(k); if (!p) return;
      const d = (p.x - wx) ** 2 + (p.y - wy) ** 2;
      if (d < bestD) { bestD = d; best = k; }
    });
    return best;
  }, [filtered, layout]);

  const onWheel = (e: React.WheelEvent) => {
    const cvs = canvasRef.current; if (!cvs) return;
    const rect = cvs.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    const { x: cx, y: cy, zoom } = cam.current;
    const wx = (mx - cvs.clientWidth / 2) / zoom + cx, wy = (my - cvs.clientHeight / 2) / zoom + cy;
    const nz = Math.max(0.05, Math.min(8, zoom * (e.deltaY < 0 ? 1.15 : 0.87)));
    cam.current = { zoom: nz, x: wx - (mx - cvs.clientWidth / 2) / nz, y: wy - (my - cvs.clientHeight / 2) / nz };
    redraw();
  };
  const onDown = (e: React.MouseEvent) => { drag.current = { x: e.clientX, y: e.clientY }; };
  const onMove = (e: React.MouseEvent) => {
    if (!drag.current) return;
    const dx = e.clientX - drag.current.x, dy = e.clientY - drag.current.y;
    drag.current = { x: e.clientX, y: e.clientY };
    cam.current = { ...cam.current, x: cam.current.x - dx / cam.current.zoom, y: cam.current.y - dy / cam.current.zoom };
    redraw();
  };
  const onUp = (e: React.MouseEvent) => {
    const moved = drag.current; drag.current = null;
    const cvs = canvasRef.current; if (!cvs || !moved) return;
    const rect = cvs.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    // 1) Label de zone — PRIORITAIRE sur les nœuds : c'est le point d'entrée du continent.
    //    (sinon un nœud proche du label capterait le clic et on ne pourrait jamais entrer.)
    let zt: string | null = null, zbest = Infinity;
    zoneHit.current.forEach((z) => {
      if (Math.abs(mx - z.sx) < z.w / 2 + 8 && Math.abs(my - z.sy) < 12) {
        const d = Math.abs(my - z.sy);
        if (d < zbest) { zbest = d; zt = z.type; }
      }
    });
    if (zt) { zoomToZone(zt); return; }
    // 2) Sinon, un nœud sous le curseur → sélection / pivot.
    const k = pick(mx, my);
    if (k) setSelected(k);
  };

  const stats = data.stats ?? {};
  const total = data.nodes.length;

  const toggle = (set: Set<string>, v: string, setter: (s: Set<string>) => void) => {
    const n = new Set(set); n.has(v) ? n.delete(v) : n.add(v); setter(n);
  };

  return (
    <>
      <ViewHeader title="neural map" />

      {/* Query builder (XKeyscore/DataWave) : recherche + filtres type/relation + stats. */}
      <Card style={{ marginBottom: "var(--space-4)" }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-3)", alignItems: "center" }}>
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="rechercher une entité…"
            style={{
              background: "var(--surface-2)", border: "1px solid var(--border)", borderRadius: "var(--radius-md,8px)",
              padding: "6px 10px", color: "var(--text-primary)", fontFamily: "var(--font-mono)", fontSize: "13px", minWidth: 200,
            }} />
          <span style={{ fontSize: "12px", color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
            {filtered.keys.size} / {total} nœuds · {filtered.edges.length} relations
          </span>
          <div style={{ flex: 1 }} />
          <button onClick={() => void load()} title="recharger"
            style={pill(false)}>{loading ? "…" : "↻"}</button>
          <button onClick={() => fit()} title="tout voir" style={pill(false)}>ajuster</button>
          {data.truncated && <span style={{ fontSize: "11px", color: "var(--forge-amber-400)" }}>tronqué au plafond</span>}
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", marginTop: "var(--space-3)" }}>
          {TYPES.filter((t) => (stats[t] ?? 0) > 0 || data.nodes.some((n) => n.type === t)).map((t) => (
            <button key={t} onClick={() => toggle(typeOff, t, setTypeOff)} style={pill(!typeOff.has(t))}>
              <span style={{ width: 8, height: 8, borderRadius: "50%", background: `var(${TYPE_VAR[t]})`,
                display: "inline-block", marginRight: 6, opacity: typeOff.has(t) ? 0.3 : 1 }} />
              {t.toLowerCase()} {stats[t] ? `· ${stats[t]}` : ""}
            </button>
          ))}
        </div>
        {data.edges.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", marginTop: "var(--space-2)" }}>
            {REL_TYPES.filter((r) => data.edges.some((e) => e.type === r)).map((r) => (
              <button key={r} onClick={() => toggle(relOff, r, setRelOff)} style={pill(!relOff.has(r))}>
                {r.toLowerCase()}
              </button>
            ))}
          </div>
        )}
      </Card>

      <div style={{ display: "flex", gap: "var(--space-4)", alignItems: "flex-start" }}>
        <Card padded={false} style={{ overflow: "hidden", flex: 1, position: "relative" }}>
          {total === 0 && !loading && (
            <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center",
              color: "var(--text-muted)", fontSize: "14px", zIndex: 1, pointerEvents: "none" }}>
              <div style={{ textAlign: "center", pointerEvents: "auto" }}>
                graphe vide — lancez des agents pour peupler la carte.
                <div style={{ marginTop: "var(--space-4)" }}>
                  <button onClick={() => { setData(buildSample()); }} style={pill(false)}>
                    voir un exemple (≈2400 nœuds)
                  </button>
                </div>
              </div>
            </div>
          )}
          {focusZone && (
            <button onClick={overview} style={{
              position: "absolute", top: "var(--space-3)", left: "var(--space-3)", zIndex: 2,
              ...pill(true),
            }}>← vue d'ensemble · <span style={{ color: `var(${TYPE_VAR[focusZone] ?? "--text-muted"})`, marginLeft: 4 }}>{focusZone.toLowerCase()}</span></button>
          )}
          <canvas ref={canvasRef}
            style={{ width: "100%", height: 520, display: "block", cursor: drag.current ? "grabbing" : "grab" }}
            onWheel={onWheel} onMouseDown={onDown} onMouseMove={onMove} onMouseUp={onUp}
            onMouseLeave={() => (drag.current = null)} />
        </Card>

        {/* Volet de tri (niveau 2) : sous-groupes de la zone focalisée. Masqué si un nœud est
            sélectionné (le panneau détail prend alors la place). */}
        {focusZone && !selected && (
          <Card style={{ width: 230, flexShrink: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <span style={{ width: 9, height: 9, borderRadius: "50%", background: `var(${TYPE_VAR[focusZone] ?? "--text-muted"})` }} />
              <span style={{ fontFamily: "var(--font-mono)", fontSize: "13px", color: "var(--text-primary)" }}>{focusZone.toLowerCase()}</span>
            </div>
            <div style={{ marginTop: "var(--space-2)", color: "var(--text-muted)", fontSize: "11px" }}>
              trier par {GROUP_FIELD_LABEL[focusZone] ?? "groupe"} · {zoneGroups.length} région(s)
            </div>
            <div style={{ marginTop: "var(--space-3)", display: "flex", flexWrap: "wrap", gap: "6px", maxHeight: 360, overflow: "auto" }}>
              <button onClick={() => setGroupFilter(null)} style={pill(groupFilter === null)}>tout</button>
              {zoneGroups.map((g) => (
                <button key={g.group} onClick={() => setGroupFilter(groupFilter === g.group ? null : g.group)}
                  style={pill(groupFilter === g.group)}>{g.group} · {g.n}</button>
              ))}
            </div>
          </Card>
        )}

        {/* Panneau détail / pivot (LemonGraph "entity details"). */}
        {selected && (
          <Card style={{ width: 230, flexShrink: 0 }}>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: "13px", color: "var(--text-primary)", wordBreak: "break-all" }}>
              {selected}
            </div>
            <div style={{ marginTop: "var(--space-2)", display: "flex", alignItems: "center", gap: "6px" }}>
              <span style={{ width: 8, height: 8, borderRadius: "50%", background: `var(${TYPE_VAR[layout.get(selected)?.type ?? ""] ?? "--text-muted"})` }} />
              <span style={{ color: "var(--text-secondary)", fontSize: "12px" }}>
                {(layout.get(selected)?.type ?? "—").toLowerCase()}
              </span>
            </div>
            <div style={{ marginTop: "var(--space-3)", color: "var(--text-muted)", fontSize: "12px" }}>
              {neighbors?.rels.length ?? 0} relation(s)
            </div>
            <div style={{ marginTop: "var(--space-2)", display: "flex", flexDirection: "column", gap: "4px", maxHeight: 320, overflow: "auto" }}>
              {neighbors?.rels.slice(0, 40).map((e, i) => {
                const other = e.source === selected ? e.target : e.source;
                return (
                  <button key={i} onClick={() => setSelected(other)} style={{
                    textAlign: "left", cursor: "pointer", background: "transparent", border: "none",
                    color: "var(--text-secondary)", fontSize: "11px", fontFamily: "var(--font-mono)", padding: 0,
                  }}>
                    <span style={{ color: "var(--text-muted)" }}>{(e.type ?? "").toLowerCase()}</span> → {other.slice(0, 20)}
                  </button>
                );
              })}
            </div>
            <button onClick={() => setSelected(null)} style={{ ...pill(false), marginTop: "var(--space-3)" }}>fermer</button>
          </Card>
        )}
      </div>
    </>
  );
}

function pill(active: boolean): React.CSSProperties {
  return {
    display: "inline-flex", alignItems: "center", cursor: "pointer",
    background: active ? "var(--surface-2)" : "transparent",
    border: "1px solid var(--border)", borderRadius: "var(--radius-full,999px)",
    padding: "3px 10px", color: "var(--text-secondary)", fontSize: "12px", fontFamily: "var(--font-mono)",
  };
}
