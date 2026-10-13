import { useEffect, useMemo, useRef, useState } from "react";
import { api, Catalog, Unit } from "./api";

export default function Picker({ cat, existing, onClose, onAdded, simple }: { cat: Catalog; existing: Unit[]; onClose: () => void; onAdded: (u: Unit) => void; simple?: boolean }) {
  const [list, setList] = useState<any[]>([]);
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<any>(null);
  const [detail, setDetail] = useState<any>(null);
  const [form, setForm] = useState("");
  const [name, setName] = useState("");
  const [auto, setAuto] = useState(!simple);   // Easy mode adds the unit bare: abilities and bonuses are picked from the game afterwards
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [progress, setProgress] = useState<any>(null);
  const dialog = useRef<HTMLDivElement>(null);
  const opener = useRef(document.activeElement as HTMLElement | null);
  const closing = useRef({ busy, onClose }); closing.current = { busy, onClose };

  useEffect(() => {
    function keyboard(event: KeyboardEvent) {
      if (event.key === 'Escape') { event.preventDefault(); if (!closing.current.busy) closing.current.onClose(); return; }
      if (event.key !== 'Tab') return;
      const items = Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), a[href], [tabindex="0"]') || []).filter(el => el.offsetParent !== null);
      const first = items[0], last = items[items.length - 1];
      if (!first) { event.preventDefault(); dialog.current?.focus(); }
      else if (!dialog.current?.contains(document.activeElement) || event.shiftKey && document.activeElement === first) { event.preventDefault(); (event.shiftKey ? last : first)?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
    document.addEventListener('keydown', keyboard, true);
    return () => { document.removeEventListener('keydown', keyboard, true); if (opener.current?.isConnected) opener.current.focus(); };
  }, []);

  useEffect(() => { api.ffbeUnits().then(setList).catch((e) => setErr(e.message)); }, []);
  useEffect(() => {
    if (!sel) return;
    let active = true;
    setDetail(null); setErr(null);
    api.ffbeUnit(sel.id).then((d) => {
      if (!active) return;
      setDetail(d);
      setForm(d.maxForm || sel.iconForm || sel.id);
      setName(d.name || sel.name);
    }).catch((e) => { if (active) setErr(e.message); });
    return () => { active = false; };
  }, [sel]);

  const shown = useMemo(() => {
    const s = q.trim().toLowerCase();
    const arr = s ? list.filter((u) => (u.name || "").toLowerCase().includes(s) || (u.jpname || "").includes(s) || u.id.startsWith(s)) : list;
    return arr.slice(0, 150);
  }, [list, q]);

  async function add() {
    if (!sel) return;
    setBusy(true); setErr(null);
    try {
      const { job } = await api.prepareAssets(sel.id, form);
      while (true) {
        const state = await api.assetProgress(job); setProgress(state);
        if (state.state === 'failed') throw new Error(state.error);
        if (state.state === 'done') break;
        await new Promise((resolve) => setTimeout(resolve, 400));
      }
      setProgress({ stage: 'Importing sprites and kit' });
      onAdded(await api.addUnit({ ffbeId: sel.id, form, name, autoport: auto }));
    } catch (e: any) { setErr(e.message); }
    setBusy(false);
  }

  const forms: string[] = detail ? Array.from(new Set([...(sel?.spriteForms || []), ...Object.keys(detail.forms || {}).filter((f) => (detail.forms[f].sprites || []).length)])) : [];
  const formLabel = (f: string) => {
    const d = detail?.forms?.[f] || sel?.previewDetail?.forms?.[f] || {};
    const shift = d.shift || sel?.shift?.[f];
    return `${d.rarity || ''}${String(d.rarity || '').startsWith('NV') ? '' : '★'}${shift ? (shift.kind === 'brave_shift' ? ' · Brave Shift' : ' · Super limit burst') : ''} · ${f}`;
  };
  const lb = detail && form ? detail.forms[form]?.limitburst : null;
  const inSpec = (u: any) => existing.some((x) => x.ffbe?.base === u.id || (x.ffbe?.id || "").startsWith(u.id.slice(0, 7)));
  return (
    <div className="modal-bg" onClick={() => { if (!busy) onClose(); }}>
      <div ref={dialog} tabIndex={-1} className="modal" role="dialog" aria-modal="true" aria-labelledby="picker-title" onClick={(e) => e.stopPropagation()}>
        <div className="body">
          <h2 id="picker-title" style={{ margin: "0 0 10px" }}>Add a unit from Brave Exvius</h2>
          <div className="row">
            <input autoFocus aria-label="Search units" disabled={busy} placeholder="Search by name…" value={q} onChange={(e) => setQ(e.target.value)} style={{ flex: 1, fontSize: 14 }} />
            <span className="muted">{list.length} units available</span>
          </div>
          {err && <div className="bad">{err}</div>}
          <div className="grid2">
            <div style={{ maxHeight: "55vh", overflow: "auto" }}>
              {shown.map((u) => (
                <button type="button" disabled={busy} key={u.id} className={"pick pick-button" + (sel?.id === u.id ? " sel" : "")} onClick={() => setSel(u)}>
                  {u.iconForm ? <img src={`/api/ffbe/icon/${u.iconForm}`} loading="lazy" onError={(e) => ((e.target as HTMLImageElement).style.visibility = "hidden")} /> : <div className="noicon">🔒</div>}
                  <div>
                    <div>{u.name || u.jpname}{!u.english && <span className="chip jp">JP name</span>}{inSpec(u) && <span className="chip">in mod</span>}{u.locked && <span className="chip locked" title="the only copies of this unit's sprite sheets are encrypted inside the JP client archives">sprites locked</span>}
                      {(u.labels || []).map((l: string) => <span key={l} className={"chip src" + (l.startsWith("JP") ? " jp" : "")} title="data source">{l}</span>)}
                      {u.spriteSource && u.spriteSource !== "jp_export" && <span className="chip src" title="sprite source">{({ jp_live: "JP live sprites", gl_extracted: "GL sprites", jp_memorial: "memorial sprites" } as any)[u.spriteSource] || u.spriteSource}</span>}</div>
                    <div className="muted" style={{ fontSize: 11 }}>{u.rarity_min}★ → {u.rarity_max === "NV" ? "NV" : u.rarity_max + "★"} · {(u.roles || []).join(", ")}{u.jpname && u.name !== u.jpname ? ` · ${u.jpname}` : ""}</div>
                  </div>
                </button>
              ))}
              {q && shown.length === 0 && <div className="muted">No unit matches. Units without sprite sheets in any local source are not listed.</div>}
            </div>
            <div>
              {sel && !detail && <div className="muted">loading…</div>}
              {detail && (
                <div>
                  <div className="row"><img src={`/api/ffbe/icon/${form}`} style={{ width: 56, imageRendering: "pixelated" }} /><b style={{ fontSize: 15 }}>{detail.name}</b> <span className="muted">{detail.jpname}</span></div>
                  {sel?.locked && <div className="bad">This unit's sprite sheets only exist encrypted inside the JP client archives (unit*.cpk). It can be added once a readable sheet is placed in a sprite folder.</div>}
                  {detail.description && <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>{detail.description}</div>}
                  <label className="field"><span>Name in FF Resonance</span><input disabled={busy} value={name} onChange={(e) => setName(e.target.value)} /></label>
                  <div className="field" style={{ marginTop: 6 }}><span>Sprite form (the highest rarity gives the stats)</span>
                    <select aria-label="Sprite form" disabled={busy} value={form} onChange={(e) => setForm(e.target.value)}>
                      {forms.map((f) => <option key={f} value={f}>{formLabel(f)}</option>)}
                    </select>
                  </div>
                  {!simple && <label className="row" style={{ marginTop: 8 }}><input disabled={busy} type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} /> Port the whole kit automatically (abilities, passives, limit burst)</label>}
                  {simple && <div className="hint" style={{ marginTop: 8 }}>The unit is added with its Brave Exvius look and stats; you pick its abilities, bonuses and Resonance from the game next.</div>}
                  {detail.previewOnly ? <p className="muted">Full stats and kit download when you press Add unit.</p> : <div className="muted" style={{ marginTop: 8 }}>
                    {(detail.abilities || []).length} abilities · {(detail.passives || []).length} passives · Limit burst: {lb?.name || "-"}<br />
                    Resonance stats: HP {detail.ffrStats?.MaxHitPoint} · MP {detail.ffrStats?.MaxMagicPoint} · ATK {detail.ffrStats?.Attack} · DEF {detail.ffrStats?.Defence} · INT {detail.ffrStats?.Intelligence} · MND {detail.ffrStats?.Mind}
                  </div>}
                  <div style={{ marginTop: 8 }}><img key={form} alt={`${detail.name} idle preview`} className="preview" src={`/api/ffbe/idle/${form}.webp`} style={{ maxHeight: 140 }} onError={(e) => { e.currentTarget.hidden = true; }} /></div>
                </div>
              )}
            </div>
          </div>
        </div>
        <div className="foot">
          {busy && <div className="import-progress" role="status"><span>{progress?.stage || 'Preparing download'}</span><progress value={progress?.total ? progress.received : undefined} max={progress?.total || 1} />{progress?.total > 0 && <small>{Math.round(100 * progress.received / progress.total)}%</small>}</div>}
          <button disabled={busy} onClick={onClose}>Cancel</button>
          <button className="primary" disabled={!detail || !form || busy || !!sel?.locked} onClick={add}>{busy ? "Adding unit…" : "Add unit"}</button>
        </div>
      </div>
    </div>
  );
}
