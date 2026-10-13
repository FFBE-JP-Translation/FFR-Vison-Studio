import { useEffect, useMemo, useRef, useState } from "react";
import ReviewedKit from './ReviewedKit';
import { api, Catalog, Grant, Unit, short, iconUrl, iconLabel, describe } from "./api";

const TABS: [string, string][] = [["identity", "Profile"], ["sprites", "Sprites"], ["skills", "Abilities"], ["mastery", "Mastery"], ["resonance", "Resonance"]];
const PARAMS: [number, string][] = [[1, "HP"], [2, "MP"], [5, "Attack"], [6, "Defence"], [7, "Intelligence"], [8, "Mind"], [9, "Agility"], [11, "Equip cost"]];
const ELEMENTS = ["None", "Fire", "Ice", "Wind", "Earth", "Thunder", "Water", "Light", "Dark"];
const TARGETS: [string, string][] = [["Single", "One target"], ["Group", "All targets"], ["Self", "Self"], ["Random", "Random targets"]];
const linToHex = (c: { R: number; G: number; B: number }) => "#" + [c.R, c.G, c.B].map((v) => Math.round(255 * Math.pow(Math.max(0, Math.min(1, v)), 1 / 2.2)).toString(16).padStart(2, "0")).join("");
const hexToLin = (h: string) => { const n = parseInt(h.slice(1), 16); const f = (v: number) => +Math.pow(v / 255, 2.2).toFixed(4); return { R: f((n >> 16) & 255), G: f((n >> 8) & 255), B: f(n & 255), A: 1.0 }; };
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
const motionFfbe = (cat: Catalog, m: string) => (cat.motions.find((x) => x.name === m)?.ffbe || "idle").split("+")[0];

export default function Editor({ unit, cat, onChange, onRemove }: { unit: Unit; cat: Catalog; onChange: (u: Unit) => void; onRemove: () => void }) {
  const [tab, setTab] = useState("identity");
  const [detail, setDetail] = useState<any>(null);
  const current = useRef(unit); current.current = unit;
  const [kitError, setKitError] = useState('');
  useEffect(() => {
    let cancelled = false;
    setKitError('');
    if (unit.ffbe && !unit.custom && unit.ffbeKit?.form !== unit.ffbe.id) {
      api.importKit(unit).then(value => { if (!cancelled && current.current === unit) onChange(value); })
        .catch(e => { if (!cancelled) setKitError(e.message); });
    }
    return () => {cancelled = true;};
  }, [unit.key, unit.ffbe?.id]);
  useEffect(() => {
    setDetail(null);
    if (!unit.ffbe) return;
    const base = unit.ffbe.base || unit.ffbe.id.slice(0, 7) + "05";
    api.ffbeUnit(base).catch(() => api.ffbeUnit(unit.ffbe!.id)).then(setDetail).catch(() => setDetail({ error: true }));
  }, [unit.key]);
  const set = (patch: Partial<Unit>) => onChange({ ...unit, ...patch });
  return (
    <div>
      {kitError && <p role="alert">Could not import the FFBE kit: {kitError}</p>}
      <div className="toolbar">
        <img src={`/api/spec/${unit.key}/icon/face`} style={{ width: 48, height: 48 }} onError={(e) => ((e.target as HTMLImageElement).style.visibility = "hidden")} />
        <h2 style={{ margin: 0 }}>{unit.en}</h2>
        <span className="spacer" />
        <button className="danger" onClick={onRemove}>Remove from mod</button>
      </div>
      <div className="tabs">{TABS.map(([t, label]) => <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>{label}</button>)}</div>
      {unit.custom && <div className="panel" style={{ marginBottom: 12 }}><b>Custom unit</b><div className="muted">Your uploaded sprites and animation timing are stored with this unit.</div>{unit.custom.warnings.map(w => <div className="hint" key={w}>{w}</div>)}</div>}
      {tab === "identity" && <Identity unit={unit} cat={cat} detail={detail} set={set} />}
      {tab === "sprites" && <Sprites unit={unit} cat={cat} detail={detail} set={set} />}
      {tab === "skills" && <Skills unit={unit} cat={cat} detail={detail} set={set} />}
      {tab === "mastery" && <Mastery unit={unit} cat={cat} detail={detail} set={set} />}
      {tab === "resonance" && <Resonance unit={unit} cat={cat} detail={detail} set={set} />}
    </div>
  );
}

// ---------------------------------------------------------------- profile & stats
function Identity({ unit, cat, detail, set }: any) {
  const roles = cat.enums.eUnitRole.filter((r: string) => r !== "None");
  const res = cat.enums.eResistance;
  const FF: Record<string, string> = { MaxHitPoint: "HP", MaxMagicPoint: "MP", Attack: "ATK", Defence: "DEF", Intelligence: "MAG", Mind: "SPR" };
  const LABEL: Record<string, string> = { MaxHitPoint: "HP", MaxMagicPoint: "MP", Attack: "Attack", Defence: "Defence", Intelligence: "Intelligence", Mind: "Mind", Agility: "Agility" };
  return (
    <div className="grid2">
      <div className="panel">
        <h3>Profile</h3>
        <div className="row"><label>Name</label><input value={unit.en} onChange={(e) => set({ en: e.target.value })} /></div>
        <div className="row"><label>Description</label><textarea value={unit.desc} onChange={(e) => set({ desc: e.target.value })} /></div>
        <div className="row"><label>Attack type</label>
          <select value={unit.attackType} onChange={(e) => set({ attackType: e.target.value })}><option value="Physic">Physical</option><option value="Magic">Magic</option></select>
          <label>Shop price</label><input type="number" value={unit.price} onChange={(e) => set({ price: +e.target.value })} /> gil
        </div>
        <div className="row"><label>Roles</label>
          {roles.map((r: string) => { const v = `eUnitRole::${r}`; const on = unit.roles.includes(v); return (
            <label key={r} style={{ minWidth: 0 }}><input type="checkbox" checked={on} onChange={() => set({ roles: on ? unit.roles.filter((x: string) => x !== v) : [...unit.roles, v] })} /> {r}</label>); })}
        </div>
        <div className="row"><label>Level curve of</label>
          <select value={unit.donor} onChange={(e) => set({ donor: +e.target.value })}>
            {cat.visions.map((v: any) => <option key={v.id} value={v.id}>{v.name}</option>)}
          </select>
          <span className="hint">the unit grows like this vision</span>
        </div>
        <div className="row"><label>Command name</label><input value={unit.command.en} onChange={(e) => set({ command: { ...unit.command, en: e.target.value } })} /></div>
        <div className="row"><label>Master skill</label><input value={unit.master.en} onChange={(e) => set({ master: { ...unit.master, en: e.target.value } })} /><input value={unit.master.desc} style={{ flex: 1 }} onChange={(e) => set({ master: { ...unit.master, desc: e.target.value } })} /></div>
        <h3 style={{ marginTop: 14 }}>Element resistances</h3>
        {Object.entries(unit.elemRes || {}).map(([el, r]) => (
          <div className="row" key={el}><label>{short(el)}</label>
            <select value={r as string} onChange={(e) => set({ elemRes: { ...unit.elemRes, [el]: e.target.value } })}>{res.map((x: string) => <option key={x} value={`eResistance::${x}`}>{x}</option>)}</select>
            <button onClick={() => { const c = { ...unit.elemRes }; delete c[el]; set({ elemRes: c }); }}>×</button>
          </div>
        ))}
        <div className="row"><label>Add</label>
          <select value="" onChange={(e) => { if (e.target.value) set({ elemRes: { ...unit.elemRes, [`eElement::${e.target.value}`]: "eResistance::Halved" } }); }}>
            <option value="">element…</option>{ELEMENTS.filter((e) => e !== "None").map((e) => <option key={e}>{e}</option>)}
          </select>
        </div>
      </div>
      <div>
        <div className="panel">
          <h3>Stats</h3>
          <table><thead><tr><th></th><th>Resonance</th><th>Brave Exvius (max)</th></tr></thead><tbody>
            {Object.entries(unit.stats).map(([k, v]) => (
              <tr key={k}><td>{LABEL[k] || k}</td><td><input type="number" value={v as number} onChange={(e) => set({ stats: { ...unit.stats, [k]: +e.target.value } })} /></td>
                <td className="muted">{detail?.statsMax && FF[k] ? detail.statsMax[FF[k]] : "-"}</td></tr>
            ))}
          </tbody></table>
          <div className="row" style={{ marginTop: 8 }}>
            <button disabled={!detail?.ffrStats} onClick={() => set({ stats: { ...detail.ffrStats } })}>Recompute from Brave Exvius</button>
            <span className="hint">scaled so that Magitek Warrior Terra matches Resonance's Terra</span>
          </div>
        </div>
        <div className="panel" style={{ marginTop: 12 }}>
          <h3>Icons</h3>
          <div className="row"><label>Style</label>
            <select value={unit.icon?.style || "gem"} onChange={(e) => set({ icon: { ...(unit.icon || { rarity: "7" }), style: e.target.value } })}><option value="border">Brave Exvius frame + rarity</option><option value="gem">Resonance frame + gem</option></select>
            <label>Rarity</label>
            <select value={unit.icon?.rarity || "7"} onChange={(e) => set({ icon: { ...(unit.icon || { style: "border" }), rarity: e.target.value } })}>{["2", "3", "4", "5", "6", "7", "NV", "NV+"].map((r) => <option key={r}>{r}</option>)}</select>
            <label>Menu sprite scale</label><input type="number" step="0.01" value={unit.menuScale ?? 2.52} onChange={(e) => set({ menuScale: +e.target.value })} />
            <label style={{ minWidth: 0 }} title="when the kit is auto-ported, every ability that has Brave Exvius effect files gets them spawned from its battle sequence (first build renders them, slow)"><input type="checkbox" checked={!!unit.portEffects} onChange={(e) => set({ portEffects: e.target.checked })} /> port Brave Exvius effects</label>
          </div>
          <div className="row">
            {[["face", "Menu"], ["timeline", "Battle"], ["ability", "Command"]].map(([k, l]) => <div key={k} className="anim"><img className="preview" src={`/api/spec/${unit.key}/icon/${k}?style=${encodeURIComponent(unit.icon?.style || "gem")}&rarity=${encodeURIComponent(unit.icon?.rarity || "7")}&v=${encodeURIComponent(JSON.stringify(unit.icon || {}))}`} style={{ width: k === "ability" ? 64 : 128 }} />{l}</div>)}
            <span className="hint">previews follow the dropdowns; "Save changes" then Build puts them in the mod. Frame placement and per-rarity chip sizes live on the Home page (Icon frames) and apply to all units</span>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- sprites
function Sprites({ unit, cat, detail, set }: any) {
  const [progress, setProgress] = useState<any>(null);
  const [error, setError] = useState('');
  if (!unit.ffbe) return <div className="muted">This unit uses another vision's sprites.</div>;
  const forms: string[] = detail?.forms ? Object.keys(detail.forms).filter((f) => detail.forms[f].available || detail.forms[f].sprites?.length) : [unit.ffbe.id];
  const anims: string[] = detail?.forms?.[unit.ffbe.id]?.sprites || [];
  async function changeForm(f: string) {
    setError(''); setProgress({ stage: 'Preparing look' });
    try {
      const { job } = await api.prepareAssets(detail.id, f);
      while (true) {
        const state = await api.assetProgress(job); setProgress(state);
        if (state.state === 'failed') throw new Error(state.error);
        if (state.state === 'done') break;
        await new Promise(resolve => setTimeout(resolve, 400));
      }
      const shift = detail.forms[f]?.shift;
      set({ ffbe: { ...unit.ffbe, id: f, dir: unit.ffbe.dir.replace(/\/\d+$/, '/' + f), baseForm: shift?.base,
        baseDir: shift ? unit.ffbe.dir.replace(/\/\d+$/, '/' + shift.base) : undefined, shift: shift?.kind },
        lb_custom: unit.lb_custom ? { ...unit.lb_custom, ffbe_lb_id: undefined, ffbe_lb: undefined } : undefined });
    } catch (e: any) { setError(e.message); }
    finally { setProgress(null); }
  }
  return (
    <div>
      <div className="panel" style={{ marginBottom: 12 }}>
        <div className="row"><label>Sprite form</label>
          <select disabled={!!progress || !!unit.custom} value={unit.ffbe.id} onChange={(e) => changeForm(e.target.value)}>
            {forms.map((f) => <option key={f} value={f}>{detail?.forms?.[f] ? (detail.forms[f].rarity === "NV" ? "Neo Vision" : detail.forms[f].rarity + "★") : f}</option>)}
          </select>
        </div>
        {error && <p className="bad" role="alert">{error}</p>}
        {progress && <p role="status">{progress.stage}{progress.total ? ` · ${Math.round(100 * progress.received / progress.total)}%` : ''}</p>}
        <h3>How each Resonance motion is played</h3>
        <div className="anims">
          {cat.motions.map((m: any) => {
            const a = m.ffbe.split("+")[0]; const fallback = unit.custom && !anims.includes(a); const ok = !!unit.custom || anims.includes(a) || !anims.length;
            return <div key={m.name} className="anim"><img alt={`${m.name}${fallback ? ', idle fallback' : ''}`} className="preview" src={`/api/ffbe/preview/${unit.ffbe.id}/${fallback ? 'idle' : a}`} onError={(e) => ((e.target as HTMLImageElement).style.opacity = "0.2")} /><b style={{ color: ok ? "inherit" : "var(--bad)" }}>{m.name}</b><br />{fallback ? 'idle fallback' : m.ffbe}</div>;
          })}
        </div>
      </div>
      <div className="panel">
        <h3>{unit.custom ? 'Your uploaded animations' : 'All Brave Exvius animations of this form'}</h3>
        <div className="anims">{anims.map((a) => <div key={a} className="anim"><img className="preview" src={`/api/ffbe/preview/${unit.ffbe.id}/${a}`} />{a}</div>)}</div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- storyboard of an FFR skill sequence
export function Storyboard({ skillId, form, cat }: { skillId: number; form?: string; cat: Catalog }) {
  const [seq, setSeq] = useState<any>(null);
  useEffect(() => { setSeq(null); api.seq(skillId).then(setSeq).catch(() => setSeq({ error: true })); }, [skillId]);
  if (!seq) return <div className="muted">loading the sequence…</div>;
  if (seq.error) return <div className="bad">This skill has no battle sequence in the demo, so nothing would play.</div>;
  const tint = (id: number) => cat.colorGrading?.find((c) => c.id === id)?.name || id;
  return (
    <div className="story">
      {seq.events.map((e: any, i: number) => {
        let body: any = null; let cls = "";
        if (e.type === "UnitPlayAnimByName") { cls = "motion"; const m = e.Unit_PlayAnimByName_AnimationName; body = <><b>Unit plays {m}</b>{form && <img className="preview" src={`/api/ffbe/preview/${form}/${motionFfbe(cat, m)}`} style={{ maxHeight: 90, display: "block", marginTop: 4 }} />}</>; }
        else if (e.type.startsWith("EffectSpawn")) { cls = "effect"; body = <><b>Effect</b> {String(e.niagaraAsset || "").replace("import:", "").replace(/^NS_EF_/, "")} <span className="muted">{e.PartName ? `at ${e.PartName}` : ""}{e.Effect_SpawnTarget_bAllTarget || e.Effect_SpawnNiagara_bAllEnemies ? " · all targets" : ""}{e.Effect_SpawnNiagara_bAllFriends ? " · all allies" : ""}</span></>; }
        else if (e.type === "OtherReaction") { cls = "hit"; body = <b>Hit lands</b>; }
        else if (e.type === "UnitMoveToTarget") { cls = "motion"; body = <b>Unit dashes to the target</b>; }
        else if (e.type === "UnitMoveToDefaultLocation" || e.type === "UnitMoveToLocation") { cls = "motion"; body = <b>Unit moves back</b>; }
        else if (e.type === "PostSetColorGradingGlobalParameter") { cls = "colour"; body = <><b>Screen tint</b> {tint(e.Post_SetColorGradingGlobalParameter_Id)}</>; }
        else if (e.type === "OtherChangeSubSpaceColor") { const c = e; cls = "colour"; body = <><b>Domain colour</b> <span style={{ background: linToHex({ R: c["Other_ChangeSubSpaceColor_Color.R"], G: c["Other_ChangeSubSpaceColor_Color.G"], B: c["Other_ChangeSubSpaceColor_Color.B"] }), padding: "0 10px" }}>&nbsp;</span>{e.disabled ? " (track disabled by the game; enabled in copies)" : ""}</>; }
        else if (e.type === "BGChange") { cls = "colour"; body = <b>Domain appears</b>; }
        else if (e.type === "CameraShake") { cls = "camera"; body = <b>Camera shake</b>; }
        else if (e.type === "CameraSetZoomInOut") { cls = "camera"; body = <b>Camera zoom</b>; }
        else if (e.type === "UnitStartAfterimage") { cls = "motion"; body = <b>Afterimage trail</b>; }
        else if (e.type === "Sound") { cls = "sound"; body = <><b>{e.voice ? "Voice" : "Sound"}</b> {e.cue}</>; }
        else return null;
        return <div key={i} className={"ev " + cls}><span className="t">{e.t != null ? e.t.toFixed(2) + "s" : ""}</span><div>{body}</div></div>;
      })}
      <div className="hint">Effects and camera are described, not rendered: the game's particle systems cannot be drawn in a browser. The unit motions use this unit's own sprites.</div>
    </div>
  );
}

// ---------------------------------------------------------------- abilities
export function iconTagFor(cat: Catalog, element: string, physical: boolean, supportive: boolean) {
  const has = (t: string) => cat.icons.some((i) => i.tag === t);
  if (supportive) return has("UI.Skill.Action.Icon.Support") ? "UI.Skill.Action.Icon.Support" : "UI.Skill.Action.Icon.Heal";
  if (element && element !== "None" && has(`UI.Skill.Action.Icon.${element}`)) return `UI.Skill.Action.Icon.${element}`;
  return "UI.Skill.Action.Icon.Attack";
}
function FfbeAbilityIcon({ icon }: { icon?: string }) {
  const [failed, fail] = useState(false);
  return icon && !failed ? <img className="abicon" src={`/api/ffbe/abilityicon/${encodeURIComponent(icon.replace(/\\/g, "/").split("/").pop()!)}`} alt="FFBE ability icon" onError={() => fail(true)} />
    : <span title="FFBE icon unavailable in local data" aria-label="FFBE icon unavailable">◇</span>;
}
function EffectReview({ review, unit, region, set }: any) {
  const [choices, choose] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const components = review.decisions || [];
  async function apply() {
    setBusy(true); setError("");
    try {
      const raw = review.snapshot?.records?.find((r: any) => `${r.source}/${r.kind}/${r.id}` === review.snapshot.root);
      if (!raw) throw Error("Original structured source is missing; refresh this unit's kit.");
      set(await api.portAbility(unit, {id:review.id, kind:review.kind, name:review.name, icon:review.icon, sourceRecord:raw}, region, choices));
    } catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  }
  return <details className="ffbe-skill"><summary><FfbeAbilityIcon icon={review.icon} /> <b>{review.name || review.id}</b> · {review.class || "unsupported"} · disabled</summary>
    <p>{review.issues?.join("; ") || "No executable effects"}</p>
    {components.map((d: any, i: number) => <div key={i} className="field"><b>{d.key} · {d.label}</b>
      <p>{d.suggestion}</p>
      {!!d.options?.length && <select value={choices[d.key] || ""} disabled={busy} onChange={e => choose(c => { const n = {...c}; if (e.target.value) n[d.key] = e.target.value; else delete n[d.key]; return n; })}>
        <option value="">Keep disabled / original effect</option>{d.options.map((o: any) => <option key={o.id} value={o.id}>{o.label}</option>)}
      </select>}
      {d.options?.filter((o: any) => o.id === choices[d.key]).map((o: any) => <p key={o.id}>{o.changes}</p>)}
    </div>)}
    <button disabled={busy || !Object.keys(choices).length || components.some((d: any) => d.issues?.length && !choices[d.key])} onClick={apply}>Apply choices and import</button>
    {error && <p role="alert">{error}</p>}
  </details>;
}
function FfbeCard({ ab, right, dim }: { ab: any; right?: any; dim?: boolean }) {
  return (
    <div className="ffbe-skill" style={{ opacity: dim ? 0.5 : 1 }}>
      <div className="t"><span style={{ display: "flex", alignItems: "center", gap: 6 }}><FfbeAbilityIcon icon={ab.icon} /><span>{ab.name}<small style={{ marginLeft: 6 }}>{ab.rarity === "NV" ? "NV" : ab.rarity + "★"} · Lv {ab.level}</small></span></span>{right}</div>
      <div className="fx">{(ab.effects || []).join(" · ")}</div>
      {ab.cost?.MP != null && <div className="fx">{ab.cost.MP} MP{ab.attack_count?.length ? ` · ${ab.attack_count.join("/")} hits` : ""}</div>}
    </div>
  );
}

function Skills({ unit, cat, detail, set }: any) {
  const [over, setOver] = useState(false);
  const [story, setStory] = useState<string | null>(null);
  const skills: Record<string, any> = unit.skills || {};
  const donors = useMemo(() => cat.skills.filter((s: any) => s.seq.length && s.hasUnit === "All").sort((a: any, b: any) => a.name.localeCompare(b.name)), [cat]);
  const abilities: any[] = detail?.abilities || [];
  const byId = (id: number) => cat.skills.find((x: any) => x.id === id);

  const [porting, setPorting] = useState(false);
  async function port(ab: any) {
    if (porting) return;
    setPorting(true);
    try { set(await api.portAbility(unit, ab, detail?.region)); }
    catch (e: any) { alert(e.message); }
    finally { setPorting(false); }
  }
  function upd(sid: string, patch: any) {
    const s = { ...skills[sid], ...patch };
    if (s.descAuto !== false && s.mechanics !== "converted") s.desc = describe(byId(s.from), s.set || {});
    set({ skills: { ...skills, [sid]: s } });
  }
  function updSet(sid: string, k: string, v: any) { const s = skills[sid]; const ns = { ...(s.set || {}) }; if (v === "" || v === null || v === undefined) delete ns[k]; else ns[k] = v; upd(sid, { set: ns }); }
  function remove(sid: string) {
    const ns = { ...skills }; delete ns[sid];
    const aw = unit.awakening.map((t: Grant[]) => t.filter((g) => !(g[0] === "ActiveSkill" && +g[1] === +sid)));
    const map = { ...(unit.ffbeMap?.skills || {}) }; for (const k of Object.keys(map)) if (map[k] === +sid) delete map[k];
    set({ skills: ns, awakening: aw, ffbeMap: { ...(unit.ffbeMap || { passives: {} }), skills: map } });
  }
  const ported = new Set(Object.values(skills).map((s: any) => s.ffbe?.id));
  const [fxPrev, setFxPrev] = useState<string | null>(null);
  return (
    <div className="grid2">
      <div className="panel">
        {unit.ffbeLibrary ? <ReviewedKit unit={unit} set={set}/> : <>
        <h3>Brave Exvius abilities {detail ? `(${abilities.length})` : ""}</h3>
        {!unit.custom && <div className="row"><button disabled={porting} title="Imports ready abilities and retains the rest for review" onClick={async () => { setPorting(true); try { set(await api.importKit(unit)); } catch (e: any) { alert(e.message); } finally { setPorting(false); } }}>Import ready abilities</button><span className="hint">Shared effect rules; replacements need your choice.</span></div>}
        <p className="hint">Direct / adaptation / replacement describe the conversion. Table compatibility does not verify gameplay. Icons use local FFBE assets; complete SFX and effect animation binding is pending.</p>
        {!!unit.conversionReview?.length && <details className="hint"><summary>{unit.conversionReview.length} abilities need attention</summary>
          {unit.conversionReview.map((r: any, i: number) => <EffectReview key={r.source?.key || i} review={r} unit={unit} region={detail?.region} set={set} />)}
        </details>}
        {!detail && <div className="muted">loading…</div>}
        {abilities.map((ab) => (
          <div key={ab.id} draggable onDragStart={(e) => e.dataTransfer.setData("text/plain", String(ab.id))}>
            <FfbeCard ab={ab} dim={ported.has(ab.id)} right={<button onClick={() => port(ab)} disabled={porting || ported.has(ab.id)}>{ported.has(ab.id) ? "ported" : "→ port"}</button>} />
          </div>
        ))}
        </>}
      </div>
      <div className="panel" onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); const id = +e.dataTransfer.getData("text/plain"); const ab = abilities.find((a) => a.id === id); if (ab && !ported.has(id)) port(ab); }}>
        <h3>Resonance abilities ({Object.keys(skills).length}/10)</h3>
        {fxPrev && skills[fxPrev] && <FfbePreview unit={unit} kind={skills[fxPrev].ffbe?.kind === "MAGIC" ? "magic" : "ability"} sid={String(skills[fxPrev].ffbe.id)}
          anim={motionFfbe(cat, skills[fxPrev].motion || "magic_attack")} title={skills[fxPrev].en} current={skills[fxPrev].ffbe_effects}
          onUse={(entries: any[]) => { upd(fxPrev, { ffbe_effects: entries, clone_sequence: true, mute: skills[fxPrev].mute || [] }); setFxPrev(null); }} onClose={() => setFxPrev(null)} />}
        <div className={"drop" + (over ? " over" : "")}>Drop a Brave Exvius ability here</div>
        {Object.entries(skills).map(([sid, s]: any) => {
          const donor = byId(s.from) || {}; const vis = byId(s.visuals ?? s.from) || donor;
          const st = s.set || {};
          const inTier = unit.awakening.findIndex((t: Grant[]) => t.some((g) => g[0] === "ActiveSkill" && +g[1] === +sid));
          const iconTag = st["SkillIcon.TagName"] || donor.icon;
          return (
            <div key={sid} className="skillbox">
              <div className="head">
                {s.ffbe ? <FfbeAbilityIcon icon={s.ffbe.icon} /> : iconUrl(cat, iconTag) && <img className="icon16" src={iconUrl(cat, iconTag)!} />}
                <input className="name" value={s.en} onChange={(e) => upd(sid, { en: e.target.value })} />
                <span className="spacer" style={{ flex: 1 }} />
                <label className="muted">Unlocked at tier <select value={inTier} onChange={(e) => { const t = +e.target.value; const aw = unit.awakening.map((tt: Grant[]) => tt.filter((g) => !(g[0] === "ActiveSkill" && +g[1] === +sid))); if (t >= 0) aw[t] = [...aw[t], ["ActiveSkill", +sid]]; set({ awakening: aw }); }}>
                  <option value={-1}>none</option>{[0, 1, 2, 3].map((t) => <option key={t} value={t}>{t + 1}</option>)}</select></label>
                <button className="danger" onClick={() => remove(sid)}>×</button>
              </div>
              <div className="row" style={{ marginBottom: 4 }}>
                <input value={s.desc} style={{ flex: 1 }} readOnly={s.descAuto !== false} onChange={(e) => upd(sid, { desc: e.target.value, descAuto: false })} />
                <label className="muted" style={{ minWidth: 0 }}><input type="checkbox" checked={s.descAuto !== false} onChange={(e) => upd(sid, { descAuto: e.target.checked })} /> auto text</label>
              </div>
              {s.ffbe?.effects && <div className="hint">Brave Exvius: {s.ffbe.effects.join(" · ")}</div>}
              {s.mechanics === "converted" && <div className="hint">{s.conversionClass || 'Legacy conversion — review required'} · uses this unit’s motion and the source hit timing · gameplay not verified.</div>}
              {!!s.conversionChanges?.length && <details className="hint"><summary>Conversion changes</summary>{s.conversionChanges.map((change: string, i: number) => <p key={i}>{change}</p>)}</details>}
              <div className="fields">
                {s.mechanics !== "converted" && <><div className="field"><span>Effect</span>
                  <select value={s.from} onChange={(e) => upd(sid, { from: +e.target.value, visuals: s.visuals === s.from ? +e.target.value : s.visuals })}>{donors.map((d: any) => <option key={d.id} value={d.id}>{d.name} · {describe(d)}</option>)}</select></div>
                <div className="field"><span>Animation</span>
                  <select value={s.visuals ?? s.from} onChange={(e) => upd(sid, { visuals: +e.target.value })}>{donors.map((d: any) => <option key={d.id} value={d.id}>{d.name}</option>)}</select>
                  <button style={{ marginTop: 4 }} onClick={() => setStory(story === sid ? null : sid)}>{story === sid ? "Hide preview" : "Preview sequence"}</button>
                  {s.ffbe?.id && unit.ffbe && <button style={{ marginTop: 4 }} onClick={() => setFxPrev(sid)}>Brave Exvius animation{s.ffbe_effects?.length ? ` (${s.ffbe_effects.length} layers)` : ""}</button>}</div></>}
                <div className="field"><span>Unit motion</span>
                  <select value={s.motion || ""} onChange={(e) => upd(sid, { motion: e.target.value || undefined })}><option value="">as in the animation</option>{cat.skillMotions.filter((m: string) => s.mechanics !== "converted" || ["attack_A", "magic_attack"].includes(m)).map((m: string) => <option key={m} value={m}>{m} ({motionFfbe(cat, m)})</option>)}</select>
                  {s.motion && unit.ffbe && <img className="preview" src={`/api/ffbe/preview/${unit.ffbe.id}/${motionFfbe(cat, s.motion)}`} style={{ maxHeight: 90, marginTop: 4 }} />}</div>
                <div className="field"><span>{s.ffbe ? 'FFR game icon (FFBE icon shown in Studio)' : 'Icon'}</span>
                  <select value={st["SkillIcon.TagName"] || ""} onChange={(e) => updSet(sid, "SkillIcon.TagName", e.target.value)}><option value="">{iconLabel(donor.icon)} (from effect)</option>{cat.icons.filter((i: any) => i.png).map((i: any) => <option key={i.tag} value={i.tag}>{iconLabel(i.tag)}</option>)}</select></div>
                <div className="field"><span>MP cost</span><input type="number" disabled={s.mechanics === "converted"} value={st.Cost ?? donor.cost ?? 0} onChange={(e) => updSet(sid, "Cost", +e.target.value)} /></div>
                <div className="field"><span>Element</span><select disabled={s.mechanics === "converted"} value={st.element || donor.element || "None"} onChange={(e) => updSet(sid, "element", e.target.value)}>{ELEMENTS.map((x) => <option key={x}>{x}</option>)}</select></div>
                <div className="field"><span>Targets</span><select disabled={s.mechanics === "converted"} value={st.TargetType || donor.target || "Single"} onChange={(e) => updSet(sid, "TargetType", e.target.value)}>{TARGETS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></div>
                <div className="field"><span>Power (%)</span><input type="number" disabled={s.mechanics === "converted"} value={st.magnification ?? donor.mag ?? 0} onChange={(e) => updSet(sid, "magnification", +e.target.value)} /></div>
                <div className="field"><span>Hits</span><input type="number" disabled={s.mechanics === "converted"} value={st.hitCount ?? donor.hits ?? 1} onChange={(e) => updSet(sid, "hitCount", +e.target.value)} /></div>
                <div className="field"><span>Break power</span><input type="number" disabled={s.mechanics === "converted"} value={st.breakDamageValue ?? donor.breakDmg ?? 0} onChange={(e) => updSet(sid, "breakDamageValue", +e.target.value)} /></div>
                <div className="field"><span>Accuracy</span><input type="number" disabled={s.mechanics === "converted"} value={st.accuracy ?? donor.accuracy ?? 100} onChange={(e) => updSet(sid, "accuracy", +e.target.value)} /></div>
              </div>
              {story === sid && <div style={{ marginTop: 8 }}><Storyboard skillId={s.visuals ?? s.from} form={unit.ffbe?.id} cat={cat} /></div>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- mastery
function grantLabel(g: Grant, unit: Unit, cat: Catalog) {
  const t = String(g[0]);
  if (t === "ActiveSkill") return unit.skills?.[String(g[1])]?.en || cat.skills.find((s) => s.id === +g[1])?.name || `skill ${g[1]}`;
  if (t === "PassiveSkill") return unit.convertedPassives?.[String(g[1])]?.en || cat.passives.find((p) => p.id === +g[1])?.name || `passive ${g[1]}`;
  if (t === "BaseParameter") return `${PARAMS.find((p) => p[0] === +g[1])?.[1] || g[1]} +${g[2] ?? 0}`;
  return unit.master.en;
}
function GrantRow({ g, unit, cat, onChange, onRemove, dragId }: { g: Grant; unit: Unit; cat: Catalog; onChange: (g: Grant) => void; onRemove: () => void; dragId?: string }) {
  const type = String(g[0]);
  const custom = Object.entries(unit.skills || {}).map(([sid, s]: any) => ({ id: +sid, name: s.en }));
  const ffr = cat.skills.filter((s) => s.seq.length && s.hasUnit === "All");
  const customPassives = Object.entries(unit.convertedPassives || {}).map(([id, p]: any) => ({ id: +id, name: p.en, desc: p.desc }));
  const p = customPassives.find((x) => x.id === +g[1]) || cat.passives.find((x) => x.id === +g[1]);
  return (
    <div className="grant" draggable={!!dragId} onDragStart={(e) => { if (dragId) { e.dataTransfer.setData("text/grant", dragId); e.dataTransfer.effectAllowed = "move"; } }} title={dragId ? "drag to another tier" : ""}>
      {dragId && <span className="handle">⋮⋮</span>}
      <select value={type} onChange={(e) => onChange([e.target.value, e.target.value === "MasterSkill" ? unit.master.id : e.target.value === "BaseParameter" ? 5 : 0, ...(e.target.value === "BaseParameter" ? [5] : [])])}>
        <option value="ActiveSkill">Ability</option><option value="PassiveSkill">Passive</option><option value="BaseParameter">Stat bonus</option><option value="MasterSkill">Master skill</option>
      </select>
      {type === "ActiveSkill" && <select value={+g[1]} onChange={(e) => onChange([type, +e.target.value])} style={{ maxWidth: 320 }}>
        <option value={0}>choose…</option>
        <optgroup label="This unit">{custom.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</optgroup>
        <optgroup label="Resonance">{ffr.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</optgroup>
      </select>}
      {type === "PassiveSkill" && <><select value={+g[1]} onChange={(e) => onChange([type, +e.target.value])} style={{ maxWidth: 320 }}>
        <option value={0}>choose…</option>{[...customPassives, ...cat.passives].map((x) => <option key={x.id} value={x.id} title={x.desc}>{x.name}</option>)}</select>
        <span className="hint" style={{ maxWidth: 260 }}>{p?.desc}</span></>}
      {type === "BaseParameter" && <><select value={+g[1]} onChange={(e) => onChange([type, +e.target.value, g[2] ?? 5])}>{PARAMS.map(([id, n]) => <option key={id} value={id}>{n}</option>)}</select>
        <input type="number" value={+(g[2] ?? 0)} onChange={(e) => onChange([type, +g[1], +e.target.value])} /></>}
      {type === "MasterSkill" && <span className="muted">{unit.master.en}</span>}
      <button onClick={onRemove}>×</button>
    </div>
  );
}
function Mastery({ unit, cat, detail, set }: any) {
  const passives: any[] = detail?.passives || [];
  const [porting, setPorting] = useState(false);
  const [overTier, setOverTier] = useState<string | null>(null);
  const mapped = unit.ffbeMap?.passives || {};
  function tierSet(kind: "awakening" | "synchro", i: number, grants: Grant[]) { const c = clone(unit[kind]); c[i] = grants; set({ [kind]: c }); }
  function moveGrant(from: string, toKind: "awakening" | "synchro", toTier: number) {
    const [fk, ft, fi] = from.split(":"); const fromKind = fk as "awakening" | "synchro"; const ti = +ft; const gi = +fi;
    if (fromKind === toKind && ti === toTier) return;
    const src = clone(unit[fromKind]); const [g] = src[ti].splice(gi, 1);
    const dst = fromKind === toKind ? src : clone(unit[toKind]);
    if (!unit.fullKit && toKind === "awakening" && dst[toTier].length >= 8) { alert("That tier already has 8 bonuses."); return; }
    dst[toTier] = [...dst[toTier], g];
    const patch: any = { [fromKind]: src }; patch[toKind] = dst;
    if (String(g[0]) === "PassiveSkill" || String(g[0]) === "BaseParameter") {
      const map = clone(mapped); for (const k of Object.keys(map)) if (JSON.stringify(map[k].grant) === JSON.stringify(g) && map[k].tier === ti) map[k].tier = toTier;
      patch.ffbeMap = { ...(unit.ffbeMap || { skills: {} }), passives: map };
    }
    set(patch);
  }
  async function portPassive(ps: any) {
    if (porting) return;
    setPorting(true);
    try { set(await api.portAbility(unit, ps, detail?.region)); }
    catch (e: any) { alert(e.message); }
    finally { setPorting(false); }
  }
  const dropProps = (kind: "awakening" | "synchro", i: number) => ({
    onDragOver: (e: any) => { if (e.dataTransfer.types.includes("text/grant")) { e.preventDefault(); setOverTier(`${kind}:${i}`); } },
    onDragLeave: () => setOverTier(null),
    onDrop: (e: any) => { e.preventDefault(); setOverTier(null); const from = e.dataTransfer.getData("text/grant"); if (from) moveGrant(from, kind, i); },
  });
  return (
    <div className="grid2">
      <div className="panel">
        <h3>Brave Exvius passives {detail ? `(${passives.length})` : ""}</h3>
        {passives.map((ps) => {
          const done = mapped[ps.id];
          return <FfbeCard key={ps.id} ab={ps} dim={!!done} right={done
            ? <span className="muted">tier {done.tier + 1}: {grantLabel(done.grant, unit, cat)}</span>
            : <button disabled={porting} onClick={() => portPassive(ps)}>→ port</button>} />;
        })}
      </div>
      <div>
        <div className="panel">
          <h3>Awakening tiers <span className="hint">drag a bonus to move it between tiers</span></h3>
          {unit.awakening.map((tier: Grant[], i: number) => (
            <div key={i} className={"tier" + (overTier === `awakening:${i}` ? " over" : "")} {...dropProps("awakening", i)}><h4>Tier {i + 1} · {tier.length}{unit.fullKit ? " learned" : "/8"}</h4>
              {tier.map((g, j) => <GrantRow key={j} g={g} unit={unit} cat={cat} dragId={`awakening:${i}:${j}`} onChange={(ng) => tierSet("awakening", i, tier.map((x, k) => (k === j ? ng : x)))} onRemove={() => tierSet("awakening", i, tier.filter((_, k) => k !== j))} />)}
              <button disabled={!unit.fullKit && tier.length >= 8} onClick={() => tierSet("awakening", i, [...tier, ["PassiveSkill", 0]])}>+ bonus</button>
            </div>
          ))}
        </div>
        <div className="panel" style={{ marginTop: 12 }}>
          <h3>Synchro levels</h3>
          {unit.synchro.map((lv: Grant[], i: number) => (
            <div key={i} className={"tier" + (overTier === `synchro:${i}` ? " over" : "")} {...dropProps("synchro", i)}><h4>Level {i}</h4>
              {lv.map((g, j) => <GrantRow key={j} g={g} unit={unit} cat={cat} dragId={`synchro:${i}:${j}`} onChange={(ng) => tierSet("synchro", i, lv.map((x, k) => (k === j ? ng : x)))} onRemove={() => tierSet("synchro", i, lv.filter((_, k) => k !== j))} />)}
              <button onClick={() => tierSet("synchro", i, [...lv, ["BaseParameter", 5, 5]])}>+ bonus</button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- resonance
// Brave Exvius animation preview: the unit's FFBE motion + the converted effect layers, rendered by the studio before a build
function FfbePreview({ unit, kind, sid, anim, title, current, onUse, onClose }: any) {
  const [layers, setLayers] = useState<any[] | null>(null);
  const [sel, setSel] = useState<Set<number>>(new Set());
  const [job, setJob] = useState<string | null>(null);
  const [state, setState] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [seconds, setSeconds] = useState(4);
  const [mode, setMode] = useState<"ffr" | "ffbe">("ffr");   // ffr: the layers as converted for the game; ffbe: the Brave Exvius data itself
  useEffect(() => {
    api.ffbeEffectLayers(kind, sid).then((d) => {
      // start from what the mod already has for this skill, else from the automatic pick
      // Resonance layers are timed "LB1" + delay in the mod; the preview's limit motion starts at 0, so show the delay as the time
      const base = (current && current.length) ? current.map((e: any) => ({ ...e, time: e.time === "LB1" || e.time === "event" ? +(e.delay ?? 0) : +(e.time ?? 0),
        anchor: e.at_target ? "target" : "caster", layer: (e.offset?.[0] ?? -80) > 0 ? "back" : "front", offsetXY: [e.offset?.[1] ?? 0, e.offset?.[2] ?? 0] })) : d.layers;
      setLayers(base); setSel(new Set(base.map((_: any, i: number) => i)));
    }).catch((e) => setErr(e.message));
  }, [kind, sid]);
  useEffect(() => {
    if (!job) return;
    const t = setInterval(async () => {
      try { const st = await api.ffbeEffectPreviewState(job); setState(st); if (st.state !== "rendering") clearInterval(t); } catch (e: any) { setErr(e.message); clearInterval(t); }
    }, 1500);
    return () => clearInterval(t);
  }, [job]);
  const upd = (i: number, patch: any) => setLayers((ls) => ls!.map((l, k) => (k === i ? { ...l, ...patch } : l)));
  async function render() {
    if (!layers) return;
    setState(null); setErr(null);
    try { const r = await api.ffbeEffectPreview({ form: unit.ffbe.id, anim, seconds, mode, kind, sid, layers: layers.filter((_, i) => sel.has(i)) }); setJob(r.job); setState({ state: "rendering", log: [] }); } catch (e: any) { setErr(e.message); }
  }
  function use() {
    if (!layers) return;
    const entries = layers.filter((_, i) => sel.has(i)).map((l, i) => ({
      name: l.name, source: l.source, id: l.id || l.name, spawn: { any: true, index: i }, ...(kind === "lb" ? { time: "LB1", delay: +l.time } : { time: +l.time }), part: "NULL_Center",
      follow: l.anchor !== "target", at_target: l.anchor === "target", scale: +l.scale || 1, add_gain: +l.add_gain || 1.0,
      // depth: front/back +-80, plus the FFBE group's "toward the camera" offset kept from the automatic pick (l.offset[0])
      offset: [l.offset?.[0] !== undefined && Math.sign(l.offset[0]) === (l.layer === "back" ? 1 : -1) ? l.offset[0] : (l.layer === "back" ? 80 : -80), +(l.offsetXY?.[0] ?? 0), +(l.offsetXY?.[1] ?? 0)], ffbeGroup: l.ffbeGroup,
      // bake options (tools/ffbe_effects/layer_spec.py): repeated spawns of one file, emitters left out, plate size cap
      ...(l.repeat > 1 ? { repeat: +l.repeat, interval: +(l.interval ?? 0) } : {}), ...(l.exclude?.length ? { exclude: l.exclude } : {}), ...(l.max_units ? { max_units: +l.max_units } : {}),
      // one actor made of several files (layer_spec.py "compose"), and the loop guard
      ...(l.compose ? { compose: l.compose } : {}), ...(l.min_frames ? { min_frames: +l.min_frames } : {}) }));
    onUse(entries);
  }
  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} style={{ width: "min(1100px, 96vw)" }}>
        <div className="body">
          <h2 style={{ margin: "0 0 8px" }}>Brave Exvius animation: {title}</h2>
          <div className="hint">The unit's <b>{anim}</b> motion with the effect. <label>Show <select value={mode} onChange={(e) => setMode(e.target.value as any)}><option value="ffr">the FF Resonance conversion (these layers, as the game gets them)</option><option value="ffbe">the Brave Exvius data (the skill's own effect groups, raw bake, no port knobs)</option></select></label> Targets are on the left as in Brave Exvius.{mode === "ffbe" && <span className="muted"> The reference ignores the layer list below; it shows the effect files, timing, anchors and offsets from Brave Exvius' tables as decoded (FORMAT.md 4.4 lists what is still approximate).</span>}</div>
          {err && <div className="bad">{err}</div>}
          <div className="grid2" style={{ marginTop: 8 }}>
            <div>
              {!layers && <div className="muted">looking up the effect files…</div>}
              {layers && layers.length === 0 && <div className="muted">This skill has no sprite effect files in Brave Exvius (movie, sound-only or plates only).</div>}
              {layers && layers.map((l, i) => (
                <div key={i} className="ffbe-skill" style={{ cursor: "default", marginBottom: 6, opacity: sel.has(i) ? 1 : 0.5 }}>
                  <div className="t"><label><input type="checkbox" checked={sel.has(i)} onChange={(e) => { const n = new Set(sel); e.target.checked ? n.add(i) : n.delete(i); setSel(n); }} /> {l.source || `${l.name} (${(l.compose || []).length} files in one actor)`}</label> <small className="muted">{l.ffbeGroup}{l.repeat > 1 ? ` · ×${l.repeat} every ${l.interval} s` : ""}{l.exclude?.length ? ` · without emitter ${l.exclude.join(", ")}` : ""}</small>
                    {l.compose && <div className="muted" style={{ fontSize: 11, marginLeft: 22 }}>{l.compose.map((c: any, k: number) => <div key={k}>{c.source} at +{c.time ?? 0} s, offset {(c.offset || [0, 0]).join(", ")}{c.repeat > 1 ? `, ×${c.repeat} every ${c.interval} s` : ""}{c.exclude?.length ? `, without emitter ${c.exclude.join(", ")}` : ""}</div>)}</div>}</div>
                  <div className="row" style={{ fontSize: 12 }}>
                    <label>on <select value={l.anchor} onChange={(e) => upd(i, { anchor: e.target.value })}><option value="caster">the unit</option><option value="target">the targets</option></select></label>
                    <label>drawn <select value={l.layer} onChange={(e) => upd(i, { layer: e.target.value })}><option value="front">in front</option><option value="back">behind</option></select></label>
                    <label>at <input type="number" step={0.05} value={l.time} style={{ width: 60 }} onChange={(e) => upd(i, { time: +e.target.value })} /> s</label>
                    <label>size ×<input type="number" step={0.1} value={l.scale ?? 1} style={{ width: 52 }} onChange={(e) => upd(i, { scale: +e.target.value })} /></label>
                    <label title="how many times the file plays, and how many seconds apart (Brave Exvius groups spawn e.g. the Firaga flame 7 times)">×<input type="number" min={1} max={12} value={l.repeat ?? 1} style={{ width: 40 }} onChange={(e) => upd(i, { repeat: +e.target.value })} /> every <input type="number" step={0.05} value={l.interval ?? 0} style={{ width: 52 }} onChange={(e) => upd(i, { interval: +e.target.value })} /> s</label>
                    <label title="additive brightness: below 1 dims, above 1 brightens the glow colour (Brave Exvius draws its low-alpha flame textures hot)">glow <input type="number" step={0.05} min={0} max={3} value={l.add_gain ?? 1.0} style={{ width: 52 }} onChange={(e) => upd(i, { add_gain: +e.target.value })} /></label>
                    <label>offset <input type="number" value={l.offsetXY?.[0] ?? 0} style={{ width: 52 }} onChange={(e) => upd(i, { offsetXY: [+e.target.value, l.offsetXY?.[1] ?? 0] })} />, <input type="number" value={l.offsetXY?.[1] ?? 0} style={{ width: 52 }} onChange={(e) => upd(i, { offsetXY: [l.offsetXY?.[0] ?? 0, +e.target.value] })} /></label>
                  </div>
                </div>
              ))}
              <div className="row" style={{ marginTop: 8 }}>
                <button className="primary" onClick={render} disabled={!layers || state?.state === "rendering"}>{state?.state === "rendering" ? "Rendering…" : "Render preview"}</button>
                <label className="muted">for <input type="number" min={1} max={12} value={seconds} style={{ width: 50 }} onChange={(e) => setSeconds(+e.target.value)} /> s</label>
                <button onClick={use} disabled={!layers}>Use these layers in the mod</button>
                <button onClick={onClose}>Close</button>
              </div>
              {state?.state === "rendering" && <div className="muted" style={{ marginTop: 6 }}>{(state.log || []).slice(-1)[0] || "first render of a file takes about a minute; later ones seconds"}</div>}
              {state?.state === "error" && <div className="bad">{state.error}</div>}
            </div>
            <div>
              {state?.state === "done" && job && <img src={`/api/ffbe/effects/preview/${job}/image?t=${Date.now()}`} style={{ width: "100%", imageRendering: "auto", borderRadius: 6 }} />}
              {state?.state !== "done" && <div className="muted" style={{ padding: 20 }}>The preview appears here.</div>}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function FfbeEffects({ unit }: any) {
  const [fx, setFx] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (!unit.ffbe?.id) return;
    api.ffbeEffects("lb", unit.ffbe.id).then(setFx).catch((e) => setErr(e.message));
  }, [unit.ffbe?.id]);
  if (!unit.ffbe?.id) return null;
  if (err) return <div className="muted">Brave Exvius effect data: {err}</div>;
  if (!fx) return <div className="muted">looking up the Brave Exvius effects…</div>;
  const ported = new Set((unit.lb_custom?.ffbe_effects || []).map((e: any) => e.source || e.name));
  return (
    <div className="ffbe-skill" style={{ cursor: "default", marginTop: 6 }}>
      <div className="t">Brave Exvius effects of "{fx.name}" {fx.attack_frames ? <small style={{ marginLeft: 6 }}>hits {fx.attack_frames}</small> : null}</div>
      {fx.groups.length === 0 && <div className="fx">this limit burst plays no sprite effects (movie or none)</div>}
      {fx.groups.map((g: any, i: number) => (
        <div className="fx" key={i}>
          <b>{g.group?.name || g.group?.groupId || "?"}</b> at frame {g.frame}
          {(g.group?.effects || []).map((e: any, j: number) => <span key={j} style={{ marginLeft: 8 }}>{e.file || e.effectId}{e.x || e.y ? ` (${e.x},${e.y})` : ""}{e.exists ? "" : " · file missing"}{ported.has(e.file) ? " · ported" : ""}</span>)}
          {(g.group?.sounds || []).length > 0 && <span className="muted" style={{ marginLeft: 8 }}>sound cue {g.group.sounds.map((sn: any) => sn.seId).join(", ")}</span>}
        </div>
      ))}
      {(unit.lb_custom?.ffbe_effects || []).length > 0 && <div className="fx">Spawned by this Resonance: {(unit.lb_custom.ffbe_effects).map((e: any) => e.name).join(", ")}</div>}
    </div>
  );
}

function Resonance({ unit, cat, detail, set }: any) {
  const lb = unit.lb_custom;
  const own = !!unit.ffbe && lb?.presentation !== 'template';
  const [fxPrev, setFxPrev] = useState(false);
  const [seq, setSeq] = useState<any>(null);
  const [story, setStory] = useState(false);
  const finish = cat.skills.filter((s: any) => s.attr === "FinishBlow");
  const vis = lb?.visuals ?? lb?.from;
  useEffect(() => { setSeq(null); if (vis) api.seq(vis).then(setSeq).catch(() => setSeq({ error: true })); }, [vis]);
  const ffbeLb = detail?.forms?.[unit.ffbe?.id]?.limitburst || detail?.forms?.[detail?.maxForm]?.limitburst;
  function upd(patch: any) { set({ lb_custom: { ...lb, ...patch } }); }
  function enable() {
    set({ lb_custom: { from: 414090, clone_sequence: true, mute: ["VO_"], caption_from: 440260, jp: `${unit.jp}_LB`, en: ffbeLb?.name || `${unit.en}'s Resonance`, desc: (ffbeLb?.effects || []).join(" ") || "", set: {},
      sequence_edits: { master: [{ match: { EventType: "OtherChangeSubSpaceColor" }, set: { Other_ChangeSubSpaceColor_Color: { R: 0.25, G: 0.25, B: 0.35, A: 1.0 } } }] }, effect_swaps: [] } });
  }
  const color = lb?.sequence_edits?.master?.find((e: any) => e.match?.EventType === "OtherChangeSubSpaceColor")?.set?.Other_ChangeSubSpaceColor_Color || { R: 0.25, G: 0.25, B: 0.35 };
  function setColor(hex: string) {
    if (own) { upd({ field_color_mode: 'custom', field_color: hex }); return; }
    const master = (lb.sequence_edits?.master || []).filter((e: any) => e.match?.EventType !== "OtherChangeSubSpaceColor");
    master.push({ match: { EventType: "OtherChangeSubSpaceColor" }, set: { Other_ChangeSubSpaceColor_Color: hexToLin(hex) } });
    upd({ sequence_edits: { ...(lb.sequence_edits || {}), master } });
  }
  const spawns: string[] = useMemo(() => { const ev = seq?.events || []; return Array.from(new Set(ev.filter((e: any) => e.niagaraAsset).map((e: any) => String(e.niagaraAsset).replace("import:", "")))) as string[]; }, [seq]);
  const pathOf = (name: string) => cat.niagara.find((p: string) => p.endsWith("/" + name)) || "";
  const swapFor = (name: string) => { const pair = (lb.effect_swaps || []).find((p: string[]) => p[0] === name); return pair ? pair[1] : ""; };
  function setSwap(name: string, newPath: string) {
    const rest = (lb.effect_swaps || []).filter((p: string[]) => p[0] !== name && p[0] !== pathOf(name));
    if (newPath) { const nn = newPath.split("/").slice(-1)[0]; rest.push([pathOf(name), newPath], [name, nn]); }
    upd({ effect_swaps: rest });
  }
  const templ = (id: number) => cat.lbTemplates.find((t: any) => t.id === id);
  if (!lb) return <div className="panel"><div className="muted">This unit borrows the Resonance of {cat.skills.find((s: any) => s.id === unit.lb)?.name}.</div><button className="primary" style={{ marginTop: 8 }} onClick={enable}>Create its own Resonance</button></div>;
  return (
    <div className="grid2">
      <div className="panel">
        <h3>Resonance</h3>
        {ffbeLb && <div className="ffbe-skill" style={{ cursor: "default" }}><div className="t">{unit.custom ? 'Custom limit burst' : 'Brave Exvius limit burst'}: {ffbeLb.name}</div><div className="fx">{(ffbeLb.effects || []).join(" · ")}{!unit.custom && ffbeLb.attack_count?.length ? ` · ${ffbeLb.attack_count.join("/")} hits` : ""}</div></div>}
        {own && <p className="hint">Uses this unit's limit burst motion, hit timing and shared sounds. Native impact effects play while full attack effects are being added.</p>}
        {!own && !unit.custom && <FfbeEffects unit={unit} />}
        {!own && unit.ffbe && !unit.custom && <button onClick={() => setFxPrev(true)}>Brave Exvius animation{lb.ffbe_effects?.length ? ` (${lb.ffbe_effects.length} layers)` : ""}</button>}
        {fxPrev && <FfbePreview unit={unit} kind="lb" sid={String(unit.ffbe.id)} anim="limitatk" title={lb.en} current={lb.ffbe_effects}
          onUse={(entries: any[]) => { upd({ ffbe_effects: entries }); setFxPrev(false); }} onClose={() => setFxPrev(false)} />}
        <div className="row"><label>Name</label><input value={lb.en} onChange={(e) => upd({ en: e.target.value, nameAuto: false })} /></div>
        {own && <><div className="row"><label>Mechanics</label><select value={lb.mechanics || 'ffbe'} onChange={e => upd({ mechanics: e.target.value })}><option value="ffbe">Imported hit timing and mechanics</option><option value="custom">Custom numbers from an FFR effect</option></select></div><div className="row"><label>Sound</label><select value={lb.audio || 'native'} onChange={e => upd({ audio: e.target.value, audio_codec: 'host' })}><option value="native">Charging and available attack sounds</option><option value="disabled">Muted</option></select></div></>}
        <div className="row"><label>Description</label><textarea value={lb.desc} onChange={(e) => upd({ desc: e.target.value })} /></div>
        <div className="row"><label>Effect</label>
          <select disabled={own && lb.mechanics !== 'custom'} value={lb.from} onChange={(e) => upd({ from: +e.target.value })}>{finish.map((s: any) => <option key={s.id} value={s.id}>{s.name} · {describe(s)}</option>)}</select></div>
        {!own && <div className="row"><label>Animation</label>
          <select value={vis} onChange={(e) => upd({ visuals: +e.target.value, effect_swaps: [] })}>{cat.lbTemplates.map((t: any) => <option key={t.id} value={t.id}>{t.name} · {describe(t)}</option>)}</select>
          <button onClick={() => setStory(!story)}>{story ? "Hide preview" : "Preview sequence"}</button></div>}
        <div className="row"><label>Caption lines</label>
          <select value={lb.caption_from || ""} onChange={(e) => upd({ caption_from: +e.target.value })}>{finish.filter((s: any) => s.id >= 440000 && s.id < 441000).map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></div>
        {own && <div className="row"><label>Field colour</label><select value={lb.field_color_mode || 'element'} onChange={e => upd({ field_color_mode: e.target.value })}><option value="element">Match the attack element</option><option value="custom">Custom colour</option></select></div>}
        <div className="row"><label>Domain colour</label><input type="color" disabled={own && lb.field_color_mode !== 'custom'} value={own ? lb.field_color || '#808080' : linToHex(color)} onChange={(e) => setColor(e.target.value)} />
          <label>Screen tint</label>
          <select value={lb.tint ?? ""} onChange={(e) => upd({ tint: e.target.value === "" ? undefined : +e.target.value })}><option value="">as the animation</option>{(cat.colorGrading || []).map((c: any) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></div>
        <div className="row"><label>Voice</label><label style={{ minWidth: 0 }}><input type="checkbox" checked={(lb.mute || []).includes("VO_")} onChange={(e) => upd({ mute: e.target.checked ? ["VO_"] : [] })} /> mute the original unit's lines</label>
          <label>Element</label><select disabled={own && lb.mechanics !== 'custom'} value={lb.set?.element || "None"} onChange={(e) => upd({ set: { ...(lb.set || {}), element: e.target.value } })}>{ELEMENTS.map((x) => <option key={x}>{x}</option>)}</select>
          <label>Damage</label><select disabled={own && lb.mechanics !== 'custom'} value={lb.set?.DamageType || ""} onChange={(e) => upd({ set: { ...(lb.set || {}), DamageType: e.target.value || undefined, damageCalcType: e.target.value || undefined } })}><option value="">as the effect</option><option value="Physic">Physical</option><option value="Magic">Magic</option></select></div>
        <div className="row"><label>Icon</label>
          <select value={lb.set?.["SkillIcon.TagName"] || ""} onChange={(e) => upd({ set: { ...(lb.set || {}), "SkillIcon.TagName": e.target.value || undefined } })}><option value="">as the effect</option>{cat.icons.filter((i: any) => i.png).map((i: any) => <option key={i.tag} value={i.tag}>{iconLabel(i.tag)}</option>)}</select></div>
        <div className="row"><label>Timing</label>
          <select value={lb.stretch === false ? "off" : typeof lb.stretch === "number" ? "custom" : "auto"} onChange={(e) => upd({ stretch: e.target.value === "off" ? false : e.target.value === "custom" ? (typeof lb.stretch === "number" ? lb.stretch : 1) : "auto" })}>
            <option value="auto">make room for this unit's limit-burst motion (automatic)</option><option value="custom">push the keys after LB1 by a fixed time</option><option value="off">keep the template's timing</option></select>
          {typeof lb.stretch === "number" && <input type="number" step={0.1} min={0} max={10} value={lb.stretch} onChange={(e) => upd({ stretch: +e.target.value })} style={{ width: 70 }} />}
          {typeof lb.stretch === "number" && <span className="muted">seconds</span>}</div>
        <button className="danger" onClick={() => { const u = { ...unit }; delete u.lb_custom; set(u); }}>Use a borrowed Resonance instead</button>
      </div>
      <div className="panel">
        <h3>{own ? 'Your limit burst animation' : `Animation: ${templ(vis)?.name || vis}`}</h3>
        {own && <><img className="preview" alt={`${unit.en} limit burst`} src={`/api/ffbe/anim/${unit.ffbe.id}/limitatk.webp`} style={{ maxWidth: '100%', maxHeight: 320 }} /><p className="hint">The unit's motion is shown here. Native particles and the field colour are rendered by the game.</p></>}
        {!own && spawns.length > 0 && <div><b>Effects</b> <span className="hint">pick a replacement from the game's effects, or leave blank to keep</span>
          <table><tbody>{spawns.map((n) => (
            <tr key={n}><td>{n.replace(/^NS_EF_/, "")}</td><td><input list="niagara" value={swapFor(n)} placeholder="keep" style={{ width: 340 }} onChange={(e) => setSwap(n, e.target.value)} /></td></tr>))}</tbody></table>
          <datalist id="niagara">{cat.niagara.map((p: string) => <option key={p} value={p} />)}</datalist></div>}
        {story && <div style={{ marginTop: 10 }}><Storyboard skillId={vis} form={unit.ffbe?.id} cat={cat} /></div>}
      </div>
    </div>
  );
}
