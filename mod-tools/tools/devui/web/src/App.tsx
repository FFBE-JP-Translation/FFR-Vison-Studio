import { useEffect, useRef, useState } from "react";
import { api, Catalog, Layout, Unit } from "./api";
import Picker from "./Picker";
import Editor from "./Editor";
import Easy from "./Easy";
import CustomUnit from './CustomUnit';
import AttackLab from './AttackLab';

type BuildState = { running: boolean; result: string | null; log: string[]; stage?: string; stages?: string[]; message?: string | null; install?: boolean };
type Mode = "easy" | "advanced";

export default function App() {
  const [cat, setCat] = useState<Catalog | null>(null);
  const [units, setUnits] = useState<Unit[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [picker, setPicker] = useState(false);
  const [custom, setCustom] = useState(false);
  const [attackLab, setAttackLab] = useState(() => new URLSearchParams(location.search).get('tool') === 'attacks');
  const [status, setStatus] = useState<any>(null);
  const [log, setLog] = useState<BuildState | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>(() => new URLSearchParams(location.search).get('mode') === 'advanced' ? 'advanced' : (localStorage.getItem("ffr-mode") as Mode) || "easy");
  const timer = useRef<any>(null);

  function loadAll() {
    api.catalog().then(setCat).catch((e) => setErr("catalog: " + e.message));
    api.spec().then(setUnits).catch((e) => setErr("spec: " + e.message));
  }
  useEffect(() => {
    api.status().then((s) => { setStatus(s); if (!s.setupNeeded) loadAll(); }).catch((e) => setErr("status: " + e.message));
    const t = setInterval(refreshStatus, 8000);
    return () => clearInterval(t);
  }, []);

  function refreshStatus() { api.status().then(setStatus).catch(() => {}); }
  function update(u: Unit) { setUnits((all) => all.map((x) => (x.key === u.key ? u : x))); setDirty(true); }
  async function save() { try { await api.saveSpec(units); setDirty(false); setErr(null); return true; } catch (e: any) { setErr("save: " + e.message); return false; } }
  async function openImport(own = false) { if (dirty && !await save()) return; if (own) setCustom(true); else setPicker(true); }
  function switchMode(m: Mode) { setMode(m); localStorage.setItem("ffr-mode", m); }

  async function startBuild(install: boolean) {
    if (dirty && !await save()) return;
    try {
      await api.build(install);
      setLog({ running: true, result: null, log: [], stage: "Starting", stages: [] });
      clearInterval(timer.current);
      timer.current = setInterval(async () => {
        const l = await api.buildLog();
        setLog(l);
        if (!l.running) { clearInterval(timer.current); refreshStatus(); }
      }, 1200);
    } catch (e: any) { setErr("build: " + e.message); }
  }

  async function removeUnit(key: string) {
    const u = units.find((x) => x.key === key);
    if (!confirm(`Remove ${u?.en || key} from the mod?`)) return;
    await api.delUnit(key);
    setUnits(await api.spec()); if (sel === key) setSel(null);
  }

  if (status?.setupNeeded) return <Setup status={status} onDone={() => { refreshStatus(); loadAll(); }} />;

  const unit = units.find((u) => u.key === sel) || null;
  const onInstall = async () => { try { const r = await api.install(); setLog({ running: false, result: "ok", log: log?.log || [], stage: "Done", stages: log?.stages || [], message: r.message, install: true }); refreshStatus(); } catch (e: any) { setErr(e.message); } };
  return (
    <div className="app">
      <aside className="side">
        <h1>FFR Vision Studio</h1>
        <div className="modeswitch" title="Easy: build a vision from what the game already has. Advanced: everything, including Brave Exvius imports and animation edits.">
          <button className={mode === "easy" ? "active" : ""} onClick={() => switchMode("easy")}>Easy</button>
          <button className={mode === "advanced" ? "active" : ""} onClick={() => switchMode("advanced")}>Advanced</button>
        </div>
        {mode === 'advanced' && <button className={'attack-lab-nav' + (attackLab ? ' active' : '')} onClick={() => setAttackLab(v => !v)}>{attackLab ? 'Back to unit editor' : 'Attack Lab'}</button>}
        <div className="units">
          <div className={"unit" + (sel === null ? " active" : "")} onClick={() => setSel(null)}>
            <span style={{ width: 32, textAlign: "center", fontSize: 18 }}>⌂</span><div>Home<small>{units.length} units in the mod</small></div>
          </div>
          {units.map((u) => (
            <div key={u.key} className={"unit" + (sel === u.key ? " active" : "")} onClick={() => setSel(u.key)}>
              <img src={`/api/spec/${u.key}/icon/ability`} onError={(e) => ((e.target as HTMLImageElement).style.visibility = "hidden")} />
              <div>{u.en}<small>{u.attackType === "Magic" ? "Magic" : "Physical"} · {(u.roles || []).map((r) => r.replace("eUnitRole::", "")).join(", ")}</small></div>
            </div>
          ))}
        </div>
        <div className="foot">
          <button className="primary" onClick={() => openImport()}>+ Add a unit</button>
          {mode === 'advanced' && <button onClick={() => openImport(true)}>Create a custom unit</button>}
          <button onClick={save} disabled={!dirty}>{dirty ? "Save changes" : "All changes saved"}</button>
          {status && <div className="muted" style={{ fontSize: 11 }}>
            Game: <b className={status.gameRunning ? "warn" : "ok"}>{status.gameRunning ? "running" : "closed"}</b> · Mod: {status.modInstalled ? "installed" : "not installed"}
            {status.lastResult && <div>Last build: {status.lastResult}</div>}
          </div>}
        </div>
      </aside>
      <main className="main">
        {err && <div className="panel bad" style={{ marginBottom: 12 }}>{err} <button onClick={() => setErr(null)}>×</button></div>}
        {attackLab && mode === 'advanced' ? <AttackLab unit={unit} onBeforeBuild={async () => !dirty || await save()} /> : custom && cat ? <CustomUnit cat={cat} onClose={() => setCustom(false)} onAdded={async u => { setUnits(await api.spec()); setSel(u.key); setCustom(false); setDirty(false); switchMode('advanced'); }} /> : unit && cat ? (
          mode === "easy"
            ? <><Easy unit={unit} cat={cat} onChange={update} /><div className="row" style={{ marginTop: 16 }}><button className="danger" onClick={() => removeUnit(unit.key)}>Remove this unit from the mod</button><span className="hint">Advanced mode has the Brave Exvius kit import, sprite settings and animation edits for this unit.</span></div></>
            : <Editor unit={unit} cat={cat} onChange={update} onRemove={() => removeUnit(unit.key)} />
        ) : (
          <Home units={units} status={status} log={log} mode={mode} onBuild={startBuild} onSelect={setSel} onInstall={onInstall} onAdd={() => openImport()} />
        )}
      </main>
      {picker && cat && (
        <Picker cat={cat} existing={units} simple={mode === "easy"} onClose={() => setPicker(false)} onAdded={async (u) => { setUnits(await api.spec()); setSel(u.key); setPicker(false); }} />
      )}
    </div>
  );
}

function Home({ units, status, log, mode, onBuild, onSelect, onInstall, onAdd }: { units: Unit[]; status: any; log: any; mode: Mode; onBuild: (i: boolean) => void; onSelect: (k: string) => void; onInstall: () => void; onAdd: () => void }) {
  const gameRunning = status?.gameRunning;
  const [tab, setTab] = useState<"units" | "icons">("units");
  return (
    <div>
      <div className="toolbar">
        <h2 style={{ margin: 0 }}>Your visions</h2>
        <span className="spacer" />
        {mode === "advanced" && <button onClick={() => onBuild(false)} disabled={log?.running}>Build mod</button>}
        <button className="primary" onClick={() => onBuild(true)} disabled={log?.running || gameRunning} title={gameRunning ? "Close the game first" : "Build the mod and copy it into the game"}>{mode === "easy" ? "Install into the game" : "Build & install"}</button>
        <button onClick={onInstall} disabled={gameRunning || log?.running}>Install last build</button>
      </div>
      {gameRunning && <div className="hint" style={{ marginBottom: 8 }}>The game is running. Close it to install; you can keep editing meanwhile.</div>}
      {mode === "advanced" && <div className="tabs"><button className={tab === "units" ? "active" : ""} onClick={() => setTab("units")}>Units</button><button className={tab === "icons" ? "active" : ""} onClick={() => setTab("icons")}>Icon frames</button></div>}
      {(tab === "units" || mode === "easy") && (
        <div className="cards">
          {units.map((u) => {
            const abilities = (u.awakening || []).reduce((n, t) => n + t.filter((g) => g[0] === "ActiveSkill").length, 0);
            const bonuses = (u.awakening || []).reduce((n, t) => n + t.filter((g) => g[0] !== "ActiveSkill").length, 0);
            return (
              <div key={u.key} className="card" onClick={() => onSelect(u.key)}>
                <img src={`/api/spec/${u.key}/icon/face`} onError={(e) => ((e.target as HTMLImageElement).style.visibility = "hidden")} />
                <div>
                  <div className="name">{u.en}</div>
                  <div className="meta">{u.attackType === "Magic" ? "Magic" : "Physical"} · {(u.roles || []).map((r) => r.replace("eUnitRole::", "")).join(", ")}</div>
                  <div className="meta">{abilities} abilities · {bonuses} bonuses</div>
                  <div className="meta">Resonance: {u.lb_custom ? u.lb_custom.en : "borrowed"}</div>
                </div>
              </div>
            );
          })}
          <div className="card" onClick={onAdd} style={{ alignItems: "center", justifyContent: "center", color: "var(--muted)" }}>+ Add a unit from Brave Exvius</div>
        </div>
      )}
      {mode === "easy" && units.length === 0 && <div className="hint" style={{ marginTop: 10 }}>Add a unit, give it abilities, bonuses, stats and a Resonance, then press "Install into the game". The unit appears in the Mitra item shop.</div>}
      {mode === "advanced" && tab === "icons" && <IconLayout units={units} />}
      {log && <BuildStatus log={log} />}
    </div>
  );
}

// first run of the packaged app: find the game, prepare its data (a few minutes, once)
function Setup({ status, onDone }: { status: any; onDone: () => void }) {
  const [game, setGame] = useState<string>(status.gameRoot || "");
  const [log, setLog] = useState<any>(null);
  const timer = useRef<any>(null);
  async function start() {
    try {
      await api.setup({ game });
      setLog({ running: true, log: [] });
      clearInterval(timer.current);
      timer.current = setInterval(async () => {
        const l = await api.setupLog(); setLog(l);
        if (!l.running) { clearInterval(timer.current); if (l.result === "ok") onDone(); }
      }, 1000);
    } catch (e: any) { setLog({ running: false, result: "failed", log: [e.message] }); }
  }
  return (
    <div className="main" style={{ maxWidth: 760, margin: "40px auto" }}>
      <h1>FFR Vision Studio</h1>
      <div className="panel">
        <h3>First run: prepare the game's data</h3>
        <p className="muted">The studio reads the game's own tables, sprites and battle sequences from your installation and converts them once. Nothing in the game folder is changed until you press "Install into the game".</p>
        <div className="row"><label>Game folder</label><input value={game} onChange={(e) => setGame(e.target.value)} style={{ flex: 1 }} placeholder="…\\steamapps\\common\\FINAL FANTASY RESONANCE DEMO" /></div>
        {status.gameRoot ? <div className="hint">Found through Steam. Change it if you installed the game elsewhere.</div> : <div className="hint">Steam's library was not found automatically; paste the folder that contains FFRS.exe.</div>}
        {status.setupMissing?.length > 0 && <div className="hint">To prepare: {status.setupMissing.join(", ")}</div>}
        <div className="row" style={{ marginTop: 10 }}><button className="primary" onClick={start} disabled={!game || log?.running}>{log?.running ? "Preparing…" : "Prepare"}</button>{log?.running && <span className="spinner" />}</div>
        {log && <div className="log" style={{ marginTop: 8 }}>{(log.log || []).slice(-40).join("\n")}</div>}
        {log && !log.running && log.result !== "ok" && <div className="bad">The preparation did not finish. The console above says why.</div>}
      </div>
    </div>
  );
}

const KINDS: [string, string, number][] = [["face", "Menu frame (diamond)", 128], ["timeline", "Battle frame (circle)", 128], ["ability", "Command icon", 64]];
const FIELDS: [string, string, number, number, number][] = [["iconScale", "Portrait size", 0.3, 2.5, 0.01], ["iconX", "Portrait left / right", -0.5, 0.5, 0.005], ["iconY", "Portrait up / down", -0.5, 0.5, 0.005],
  ["chipScale", "Rarity chip size", 0.3, 3, 0.01], ["chipX", "Chip left / right", -0.6, 0.3, 0.005], ["chipY", "Chip up / down", -0.6, 0.3, 0.005]];

const CHIPS = ["2", "3", "4", "5", "6", "7", "NV", "NV+"];
const CHIP_DEFAULT: Record<string, number> = { NV: 0.7, "NV+": 0.55 };

function IconLayout({ units }: { units: Unit[] }) {
  const [layout, setLayout] = useState<Layout | null>(null);
  const [saved, setSaved] = useState(true);
  const [kind, setKind] = useState("face");
  const sample = units.filter((u) => u.ffbe).slice(0, 4);
  useEffect(() => { api.layout().then(setLayout); }, []);
  if (!layout) return <div className="muted">loading…</div>;
  const lay = layout[kind] || {};
  const chips = layout.chips || {};
  const chipVal = (r: string) => chips[r] ?? CHIP_DEFAULT[r] ?? 1;
  const q = encodeURIComponent(JSON.stringify(layout));
  const size = KINDS.find((k) => k[0] === kind)![2];
  const chipUnit = sample[0];
  return (
    <div className="grid2">
      <div className="panel">
        <h3>Frame layout (applies to every unit)</h3>
        <div className="tabs">{KINDS.map(([k, label]) => <button key={k} className={kind === k ? "active" : ""} onClick={() => setKind(k)}>{label}</button>)}</div>
        {FIELDS.map(([f, label, min, max, step]) => (
          <div className="row" key={f}><label style={{ minWidth: 150 }}>{label}</label>
            <input type="range" min={min} max={max} step={step} value={lay[f] ?? (f.endsWith("Scale") ? 1 : 0)} style={{ flex: 1 }}
              onChange={(e) => { setLayout({ ...layout, [kind]: { ...lay, [f]: +e.target.value } }); setSaved(false); }} />
            <span className="muted" style={{ width: 52 }}>{(lay[f] ?? (f.endsWith("Scale") ? 1 : 0)).toFixed(2)}</span>
          </div>
        ))}
        <div className="row" style={{ marginTop: 10 }}>
          <button className="primary" disabled={saved} onClick={async () => { await api.saveLayout(layout); setSaved(true); }}>{saved ? "Applied to all units" : "Apply to all units"}</button>
          <button onClick={() => { setLayout({ ...layout, [kind]: { iconScale: 1, iconX: 0, iconY: 0, chipScale: 1, chipX: 0, chipY: 0 } }); setSaved(false); }}>Reset this frame</button>
          <span className="hint">Anything outside the frame is cropped, like in the game. The mod uses the applied layout at the next build.</span>
        </div>
      </div>
      <div className="panel">
        <h3>Live preview</h3>
        <div className="anims">
          {sample.map((u) => <div key={u.key} className="anim"><img className="preview" src={`/api/spec/${u.key}/icon/${kind}?l=${q}`} style={{ width: size * (size === 64 ? 2 : 1.5), imageRendering: "auto" }} />{u.en}</div>)}
        </div>
        <div className="hint" style={{ marginTop: 8 }}>Shown at {size === 64 ? "2×" : "1.5×"}; the game draws the {size}px texture.</div>
      </div>
      <div className="panel" style={{ gridColumn: "1 / -1" }}>
        <h3>Rarity chips (size per chip, on top of the frame's chip size)</h3>
        <div className="anims">
          {CHIPS.map((r) => (
            <div key={r} className="anim" style={{ minWidth: 150 }}>
              {chipUnit && <img className="preview" src={`/api/spec/${chipUnit.key}/icon/${kind}?l=${q}&rarity=${encodeURIComponent(r)}&style=border`} style={{ width: size === 64 ? 96 : 128, imageRendering: "auto" }} />}
              <div className="row" style={{ marginTop: 4 }}>
                <span style={{ width: 34 }}>{r}</span>
                <input type="range" min={0.2} max={2} step={0.01} value={chipVal(r)} style={{ flex: 1 }}
                  onChange={(e) => { setLayout({ ...layout, chips: { ...chips, [r]: +e.target.value } }); setSaved(false); }} />
                <span className="muted" style={{ width: 40 }}>{chipVal(r).toFixed(2)}</span>
              </div>
            </div>
          ))}
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          <button className="primary" disabled={saved} onClick={async () => { await api.saveLayout(layout); setSaved(true); }}>{saved ? "Applied to all units" : "Apply to all units"}</button>
          <button onClick={() => { setLayout({ ...layout, chips: {} }); setSaved(false); }}>Reset chip sizes</button>
          <span className="hint">Previews use {chipUnit ? chipUnit.en : "the first unit"}'s portrait in the {KINDS.find((k) => k[0] === kind)![1].toLowerCase()}; every unit with that rarity gets the same chip size at the next build.</span>
        </div>
      </div>
    </div>
  );
}

const STAGE_ORDER = ["Starting", "Preparing the game tables", "Writing game tables and copying battle sequences", "Applying Resonance and animation edits", "Converting sprites and icons", "Packing the mod", "Verifying the game tables", "Done"];
export function BuildStatus({ log }: { log: BuildState }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => { if (box.current) box.current.scrollTop = box.current.scrollHeight; }, [log.log.length, open]);
  const stage = log.stage || "Starting";
  const idx = Math.max(0, STAGE_ORDER.findIndex((s) => stage.startsWith(s)));
  const pct = log.running ? Math.round((idx / (STAGE_ORDER.length - 1)) * 100) : 100;
  const ok = !log.running && log.result === "ok"; const failed = !log.running && log.result !== "ok";
  return (
    <div className={"panel buildbox" + (ok ? " ok" : failed ? " failed" : "")} style={{ marginTop: 16 }}>
      <div className="row" style={{ marginBottom: 6 }}>
        {log.running && <span className="spinner" />}
        <b style={{ fontSize: 14 }}>{log.running ? stage : ok ? "Success" : "Something went wrong"}</b>
        <span className="spacer" style={{ flex: 1 }} />
        <button onClick={() => setOpen(!open)}>{open ? "Hide console" : "Open console"}</button>
      </div>
      {log.running && <div className="bar"><div style={{ width: pct + "%" }} /></div>}
      {!log.running && log.message && <div className={ok ? "ok" : "bad"} style={{ fontSize: 13 }}>{log.message}</div>}
      {log.running && <div className="hint">A full build takes a few minutes: sprites are converted for every unit each time.</div>}
      {open && <div className="log" ref={box} style={{ marginTop: 8 }}>{log.log.join("\n")}</div>}
    </div>
  );
}
