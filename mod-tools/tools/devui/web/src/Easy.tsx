// Easy mode: build a vision from what the game already ships. Nothing custom is generated here -- abilities, passives and
// Resonance mechanics are the game's own rows (granted by id), so every animation, icon and hit effect already exists.
// The spec it edits is the same units.json the Advanced editor uses; switching modes never loses anything.
import { useEffect, useMemo, useState } from "react";
import { api, Catalog, Grant, Unit, describe, iconUrl } from "./api";
import { Storyboard, iconTagFor } from "./Editor";

const STEPS: [string, string][] = [["abilities", "Abilities"], ["bonuses", "Bonuses"], ["stats", "Stats"], ["resonance", "Resonance"]];
const ELEMENTS = ["None", "Fire", "Ice", "Wind", "Earth", "Thunder", "Water", "Light", "Dark"];
const STAT_PARAMS: [number, string, number][] = [[1, "HP", 50], [2, "MP", 10], [5, "Attack", 5], [6, "Defence", 5], [7, "Intelligence", 5], [8, "Mind", 5], [9, "Agility", 3]];
const STATS: [string, string, number, number][] = [["MaxHitPoint", "HP", 200, 3000], ["MaxMagicPoint", "MP", 30, 400], ["Attack", "Attack", 5, 120], ["Defence", "Defence", 5, 120], ["Intelligence", "Intelligence", 5, 120], ["Mind", "Mind", 5, 120], ["Agility", "Agility", 5, 120]];
const ROLES: [string, string][] = [["eUnitRole::Attacker", "Attacker"], ["eUnitRole::Breaker", "Breaker"], ["eUnitRole::Defender", "Defender"], ["eUnitRole::Healer", "Healer"], ["eUnitRole::Enhancer", "Enhancer"], ["eUnitRole::Jammer", "Jammer"]];
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
const TIER_CAP = 8;

// what a game skill-effect row does, in plain words (the handful of types the shipped Resonances use)
function effectLabel(e: any): string | null {
  if (!e) return null;
  const p: number[] = e.params || [];
  switch (e.type) {
    case "Deffence": return p[0] === 1 ? `Protect: physical defence +${p[1]}%` : p[0] === 2 ? `Shell: magic defence +${p[1]}%` : `Cuts the next hit by ${p[1]}%`;
    case "CureStatusCondition": return p[1] === 1 ? "Dispels buffs on the target" : "Cures status ailments";
    case "OverHeal": return "Healing can exceed max HP";
    case "ParameterVariation": return e.status && e.status !== "None" ? `Inflicts ${e.status} (${p[0]}% per turn, ${p[2]} turns)` : "Changes a stat";
    case "AccuracyVariation": return `${e.status || "Accuracy"}: accuracy ${p[0]}%`;
    case "InstantDeath": return `${e.prob}% chance of instant death`;
    case "Steal": return "Steals an item";
    case "CritMul": return `Critical damage +${p[0]}%`;
    case "MulBaseSkillByLevel": case "AppendDamage": case "DmgMulSpecificSkill": return null;   // internal scaling rows
    default: return e.type;
  }
}

export function ownerOf(cat: Catalog, finishBlow: number) { return cat.visions.find((v) => v.finishBlow === finishBlow)?.name; }

export default function Easy({ unit, cat, onChange }: { unit: Unit; cat: Catalog; onChange: (u: Unit) => void }) {
  const [step, setStep] = useState("abilities");
  const [detail, setDetail] = useState<any>(null);
  useEffect(() => { if (unit.ffbe) api.ffbeUnit(unit.ffbe.base || unit.ffbe.id).then(setDetail).catch(() => setDetail(null)); }, [unit.key]);
  const set = (patch: Partial<Unit>) => onChange({ ...unit, ...patch });
  return (
    <div>
      <div className="toolbar">
        <img src={`/api/spec/${unit.key}/icon/face`} style={{ width: 56, height: 56, imageRendering: "pixelated" }} onError={(e) => ((e.target as HTMLImageElement).style.visibility = "hidden")} />
        <div><h2 style={{ margin: 0 }}>{unit.en}</h2><div className="muted">{unit.attackType === "Magic" ? "Magic" : "Physical"} · {(unit.roles || []).map((r) => r.replace("eUnitRole::", "")).join(", ")} · Resonance: {unit.lb_custom?.en || "borrowed"}</div></div>
      </div>
      <div className="tabs">{STEPS.map(([k, label], i) => <button key={k} className={step === k ? "active" : ""} onClick={() => setStep(k)}>{i + 1}. {label}</button>)}</div>
      {step === "abilities" && <Abilities unit={unit} cat={cat} set={set} />}
      {step === "bonuses" && <Bonuses unit={unit} cat={cat} set={set} />}
      {step === "stats" && <Stats unit={unit} cat={cat} detail={detail} set={set} />}
      {step === "resonance" && <EasyResonance unit={unit} cat={cat} detail={detail} set={set} />}
    </div>
  );
}

// ---------------------------------------------------------------- tiers (shared by abilities and bonuses)
function tierCount(unit: Unit, i: number) { return (unit.awakening[i] || []).length; }
function hasGrant(unit: Unit, g: Grant) { return unit.awakening.some((t) => t.some((x) => x[0] === g[0] && +x[1] === +g[1])); }

function Tiers({ unit, set, kinds, render, dropType, onDrop, hint }: { unit: Unit; set: (p: Partial<Unit>) => void; kinds: string[]; render: (g: Grant, i: number, j: number) => any; dropType: string; onDrop: (tier: number, payload: string) => void; hint: string }) {
  const [over, setOver] = useState<number | null>(null);
  return (
    <div className="panel">
      <h3>Learned by awakening tier <span className="hint">{hint}</span></h3>
      {unit.awakening.map((tier: Grant[], i: number) => {
        const mine = tier.map((g, j) => [g, j] as [Grant, number]).filter(([g]) => kinds.includes(String(g[0])));
        const full = tier.length >= TIER_CAP;
        return (
          <div key={i} className={"tier" + (over === i ? " over" : "")}
            onDragOver={(e) => { if (e.dataTransfer.types.includes(dropType)) { e.preventDefault(); setOver(i); } }} onDragLeave={() => setOver(null)}
            onDrop={(e) => { e.preventDefault(); setOver(null); const d = e.dataTransfer.getData(dropType); if (d) onDrop(i, d); }}>
            <h4>Tier {i + 1} <span className="muted">· {tier.length}/{TIER_CAP} bonuses in this tier{full ? " (full)" : ""}</span></h4>
            {mine.length === 0 && <div className="drop" style={{ padding: 8, marginBottom: 4 }}>Drop here</div>}
            {mine.map(([g, j]) => render(g, i, j))}
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------- 1. abilities: the game's own skills, granted by id
function Abilities({ unit, cat, set }: { unit: Unit; cat: Catalog; set: (p: Partial<Unit>) => void }) {
  const [q, setQ] = useState("");
  const [group, setGroup] = useState("all");
  const lib = useMemo(() => cat.skills.filter((s) => s.seq.length && s.hasUnit === "All" && ["Ability", "Magic", "MagicSword"].includes(s.attr) && s.id < 460000)
    .map((s) => ({ ...s, group: s.attr === "Magic" || s.attr === "MagicSword" ? (s.element && s.element !== "None" ? `${s.element} magic` : s.relation === "Friendlies" || s.dmgType === "None" ? "White magic" : "Magic") : (s.relation === "Friendlies" || s.dmgType === "None") ? "Support abilities" : "Attack abilities" }))
    .sort((a, b) => a.group.localeCompare(b.group) || a.name.localeCompare(b.name)), [cat]);
  const groups = useMemo(() => Array.from(new Set(lib.map((s) => s.group))), [lib]);
  const shown = useMemo(() => {
    const s = q.trim().toLowerCase();
    return lib.filter((x) => (group === "all" || x.group === group) && (!s || x.name.toLowerCase().includes(s) || describe(x).toLowerCase().includes(s)));
  }, [lib, q, group]);
  const granted = new Set(unit.awakening.flatMap((t) => t.filter((g) => g[0] === "ActiveSkill").map((g) => +g[1])));
  function add(tier: number, id: number) {
    if (granted.has(id)) return;
    if (tierCount(unit, tier) >= TIER_CAP) { alert(`Tier ${tier + 1} already holds ${TIER_CAP} bonuses. Choose another tier.`); return; }
    const aw = clone(unit.awakening); aw[tier] = [...aw[tier], ["ActiveSkill", id]]; set({ awakening: aw });
  }
  function move(g: Grant, from: number, to: number) {
    if (from === to) return;
    if (tierCount(unit, to) >= TIER_CAP) { alert(`Tier ${to + 1} is full.`); return; }
    const aw = clone(unit.awakening); aw[from] = aw[from].filter((x: Grant) => !(x[0] === g[0] && +x[1] === +g[1])); aw[to] = [...aw[to], g]; set({ awakening: aw });
  }
  function remove(i: number, j: number) { const aw = clone(unit.awakening); aw[i].splice(j, 1); set({ awakening: aw }); }
  const byId = (id: number) => cat.skills.find((s) => s.id === id);
  return (
    <div className="grid2">
      <div className="panel">
        <h3>The game's abilities <span className="hint">drag one onto a tier on the right, or use "add"</span></h3>
        <div className="row"><input placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} style={{ flex: 1 }} />
          <select value={group} onChange={(e) => setGroup(e.target.value)}><option value="all">All groups</option>{groups.map((g) => <option key={g}>{g}</option>)}</select></div>
        <div style={{ maxHeight: "62vh", overflow: "auto" }}>
          {shown.map((s) => {
            const done = granted.has(s.id); const ic = iconUrl(cat, s.icon);
            return (
              <div key={s.id} className="ffbe-skill" style={{ opacity: done ? 0.45 : 1 }} draggable={!done} onDragStart={(e) => { e.dataTransfer.setData("text/ffr-skill", String(s.id)); e.dataTransfer.effectAllowed = "copy"; }}>
                <div className="t"><span style={{ display: "flex", alignItems: "center", gap: 6 }}>{ic && <img src={ic} className="icon16" />}<span>{s.name}<small style={{ marginLeft: 6 }}>{s.group}</small></span></span>
                  {done ? <span className="muted">learned</span> : <select value="" onChange={(e) => { if (e.target.value !== "") add(+e.target.value, s.id); }} title="add to a tier"><option value="">add at tier…</option>{[0, 1, 2, 3].map((t) => <option key={t} value={t}>tier {t + 1}</option>)}</select>}</div>
                <div className="fx">{describe(s)} {s.cost ? `· ${s.cost} MP` : ""}</div>
              </div>
            );
          })}
          {shown.length === 0 && <div className="muted">Nothing matches.</div>}
        </div>
      </div>
      <Tiers unit={unit} set={set} kinds={["ActiveSkill"]} dropType="text/ffr-skill" onDrop={(tier, d) => add(tier, +d)} hint="tier 1 is available at level 1"
        render={(g, i, j) => {
          const custom = unit.skills?.[String(g[1])]; const s = byId(+g[1]); const ic = iconUrl(cat, custom?.set?.["SkillIcon.TagName"] || s?.icon);
          return (
            <div key={j} className="grant">
              {ic && <img src={ic} className="icon16" />}
              <span style={{ flex: 1 }}>{custom ? <>{custom.en} <span className="chip" title="made in Advanced mode">custom</span></> : s ? <>{s.name} <span className="muted">· {describe(s)}</span></> : `skill ${g[1]}`}</span>
              <select value={i} onChange={(e) => move(g, i, +e.target.value)} title="learned at tier">{[0, 1, 2, 3].map((t) => <option key={t} value={t}>tier {t + 1}</option>)}</select>
              <button onClick={() => remove(i, j)} title="remove">×</button>
            </div>
          );
        }} />
    </div>
  );
}

// ---------------------------------------------------------------- 2. bonuses: stat boosts and the game's passives
function Bonuses({ unit, cat, set }: { unit: Unit; cat: Catalog; set: (p: Partial<Unit>) => void }) {
  const [q, setQ] = useState("");
  const [amounts, setAmounts] = useState<Record<number, number>>(Object.fromEntries(STAT_PARAMS.map(([id, , d]) => [id, d])));
  const passives = useMemo(() => {
    const s = q.trim().toLowerCase();
    return cat.passives.filter((p) => p.name && !/[぀-ヿ一-鿿]/.test(p.name) && (!s || p.name.toLowerCase().includes(s) || (p.desc || "").toLowerCase().includes(s))).sort((a, b) => a.name.localeCompare(b.name));
  }, [cat, q]);
  const grantedP = new Set(unit.awakening.flatMap((t) => t.filter((g) => g[0] === "PassiveSkill").map((g) => +g[1])));
  function add(tier: number, g: Grant) {
    if (g[0] === "PassiveSkill" && grantedP.has(+g[1])) return;
    if (tierCount(unit, tier) >= TIER_CAP) { alert(`Tier ${tier + 1} already holds ${TIER_CAP} bonuses. Choose another tier.`); return; }
    const aw = clone(unit.awakening); aw[tier] = [...aw[tier], g]; set({ awakening: aw });
  }
  function update(i: number, j: number, g: Grant) { const aw = clone(unit.awakening); aw[i][j] = g; set({ awakening: aw }); }
  function remove(i: number, j: number) { const aw = clone(unit.awakening); aw[i].splice(j, 1); set({ awakening: aw }); }
  function move(g: Grant, i: number, j: number, to: number) {
    if (i === to) return;
    if (tierCount(unit, to) >= TIER_CAP) { alert(`Tier ${to + 1} is full.`); return; }
    const aw = clone(unit.awakening); aw[i].splice(j, 1); aw[to] = [...aw[to], g]; set({ awakening: aw });
  }
  const payload = (g: Grant) => JSON.stringify(g);
  return (
    <div className="grid2">
      <div>
        <div className="panel" style={{ marginBottom: 12 }}>
          <h3>Stat bonuses <span className="hint">set the amount, then drag the chip onto a tier</span></h3>
          {STAT_PARAMS.map(([id, name]) => (
            <div key={id} className="grant">
              <span className="chip" style={{ cursor: "grab", fontSize: 12, padding: "3px 10px" }} draggable onDragStart={(e) => { e.dataTransfer.setData("text/ffr-grant", payload(["BaseParameter", id, amounts[id]])); }}>⋮⋮ {name} +{amounts[id]}</span>
              <input type="number" min={1} max={500} value={amounts[id]} onChange={(e) => setAmounts({ ...amounts, [id]: +e.target.value })} />
              <select value="" onChange={(e) => { if (e.target.value !== "") add(+e.target.value, ["BaseParameter", id, amounts[id]]); }}><option value="">add at tier…</option>{[0, 1, 2, 3].map((t) => <option key={t} value={t}>tier {t + 1}</option>)}</select>
            </div>
          ))}
        </div>
        <div className="panel">
          <h3>The game's passives</h3>
          <input placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: "100%", marginBottom: 6 }} />
          <div style={{ maxHeight: "40vh", overflow: "auto" }}>
            {passives.map((p) => {
              const done = grantedP.has(p.id); const ic = iconUrl(cat, p.icon);
              return (
                <div key={p.id} className="ffbe-skill" style={{ opacity: done ? 0.45 : 1 }} draggable={!done} onDragStart={(e) => e.dataTransfer.setData("text/ffr-grant", payload(["PassiveSkill", p.id]))}>
                  <div className="t"><span style={{ display: "flex", alignItems: "center", gap: 6 }}>{ic && <img src={ic} className="icon16" />}<span>{p.name}</span></span>
                    {done ? <span className="muted">granted</span> : <select value="" onChange={(e) => { if (e.target.value !== "") add(+e.target.value, ["PassiveSkill", p.id]); }}><option value="">add at tier…</option>{[0, 1, 2, 3].map((t) => <option key={t} value={t}>tier {t + 1}</option>)}</select>}</div>
                  <div className="fx">{p.desc}</div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
      <Tiers unit={unit} set={set} kinds={["PassiveSkill", "BaseParameter"]} dropType="text/ffr-grant" onDrop={(tier, d) => add(tier, JSON.parse(d))} hint="abilities from step 1 count toward the 8 per tier"
        render={(g, i, j) => {
          if (g[0] === "BaseParameter") {
            const name = STAT_PARAMS.find((p) => p[0] === +g[1])?.[1] || `stat ${g[1]}`;
            return <div key={j} className="grant"><span style={{ flex: 1 }}>{name}</span><span className="muted">+</span><input type="number" value={+(g[2] ?? 0)} onChange={(e) => update(i, j, ["BaseParameter", +g[1], +e.target.value])} />
              <select value={i} onChange={(e) => move(g, i, j, +e.target.value)}>{[0, 1, 2, 3].map((t) => <option key={t} value={t}>tier {t + 1}</option>)}</select><button onClick={() => remove(i, j)}>×</button></div>;
          }
          const p = cat.passives.find((x) => x.id === +g[1]);
          return <div key={j} className="grant">{iconUrl(cat, p?.icon) && <img src={iconUrl(cat, p!.icon)!} className="icon16" />}<span style={{ flex: 1 }}>{p?.name || `passive ${g[1]}`} <span className="muted">· {p?.desc}</span></span>
            <select value={i} onChange={(e) => move(g, i, j, +e.target.value)}>{[0, 1, 2, 3].map((t) => <option key={t} value={t}>tier {t + 1}</option>)}</select><button onClick={() => remove(i, j)}>×</button></div>;
        }} />
    </div>
  );
}

// ---------------------------------------------------------------- 3. stats
function Stats({ unit, cat, detail, set }: { unit: Unit; cat: Catalog; detail: any; set: (p: Partial<Unit>) => void }) {
  const visions = useMemo(() => cat.visions.filter((v) => v.stats?.MaxHitPoint).sort((a, b) => a.name.localeCompare(b.name)), [cat]);
  const setStat = (k: string, v: number) => set({ stats: { ...unit.stats, [k]: v } });
  return (
    <div className="grid2">
      <div className="panel">
        <h3>Stats at level 1 <span className="hint">the level curve comes from the unit's template</span></h3>
        {STATS.map(([k, label, min, max]) => (
          <div key={k} className="row"><label style={{ minWidth: 90 }}>{label}</label>
            <input type="range" min={min} max={max} value={unit.stats[k] ?? min} style={{ flex: 1 }} onChange={(e) => setStat(k, +e.target.value)} />
            <input type="number" value={unit.stats[k] ?? min} onChange={(e) => setStat(k, +e.target.value)} /></div>
        ))}
        <div className="row" style={{ marginTop: 10 }}><label style={{ minWidth: 90 }}>Copy from</label>
          <select value="" onChange={(e) => { const v = visions.find((x) => x.id === +e.target.value); if (v) set({ stats: { ...unit.stats, ...v.stats } }); }}><option value="">a vision in the game…</option>{visions.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}</select>
          {detail?.ffrStats && <button onClick={() => set({ stats: { ...unit.stats, ...detail.ffrStats } })}>Brave Exvius-based</button>}</div>
      </div>
      <div className="panel">
        <h3>Type and roles</h3>
        <div className="row"><label>Attacks with</label>
          <label style={{ minWidth: 0 }}><input type="radio" checked={unit.attackType !== "Magic"} onChange={() => set({ attackType: "Physic" })} /> Physical</label>
          <label style={{ minWidth: 0 }}><input type="radio" checked={unit.attackType === "Magic"} onChange={() => set({ attackType: "Magic" })} /> Magic</label></div>
        <div className="row" style={{ alignItems: "flex-start" }}><label>Roles</label>
          <div>{ROLES.map(([v, label]) => <label key={v} style={{ display: "block", minWidth: 0 }}><input type="checkbox" checked={(unit.roles || []).includes(v)} onChange={(e) => { const r = (unit.roles || []).filter((x) => x !== v); set({ roles: e.target.checked ? [...r, v] : r.length ? r : ["eUnitRole::Attacker"] }); }} /> {label}</label>)}</div></div>
        <div className="row"><label>Name</label><input value={unit.en} onChange={(e) => set({ en: e.target.value })} /></div>
        <div className="row" style={{ alignItems: "flex-start" }}><label>Description</label><textarea value={unit.desc} onChange={(e) => set({ desc: e.target.value })} /></div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- 4. resonance: one of the game's Resonance animations + one of its mechanics
export function EasyResonance({ unit, cat, detail, set }: { unit: Unit; cat: Catalog; detail: any; set: (p: Partial<Unit>) => void }) {
  const lb = unit.lb_custom;
  const [story, setStory] = useState(false);
  const finish = useMemo(() => cat.skills.filter((s) => s.attr === "FinishBlow"), [cat]);
  const effById = useMemo(() => Object.fromEntries(cat.effects.map((e) => [e.id, e])), [cat]);
  const ffbeLb = detail?.forms?.[unit.ffbe?.id]?.limitburst || detail?.forms?.[detail?.maxForm]?.limitburst;
  const label = (s: any) => `${ownerOf(cat, s.id) ? ownerOf(cat, s.id) + "'s " : ""}${s.name}`;
  const damaging = finish.filter((s) => (s.dmgType === "Physic" || s.dmgType === "Magic") && s.mag > 0);
  const healing = finish.filter((s) => s.dmgType === "None" && s.relation === "Friendlies" && s.effectType === "DamageAndRecovery" && s.mag > 0);
  const buffing = finish.filter((s) => s.dmgType === "None" && s.relation === "Friendlies" && !healing.includes(s));
  const debuffing = finish.filter((s) => s.relation === "Enemies" && s.effects.some((id: number) => ["ParameterVariation", "AccuracyVariation"].includes(effById[id]?.type) && effById[id]?.status && effById[id]?.status !== "None"));
  useEffect(() => { if (!lb) enable(); }, [unit.key]);   // the easy editor always works on the unit's own Resonance
  function enable() {
    set({ lb_custom: { from: 414090, visuals: 414090, clone_sequence: true, mute: ["VO_"], caption_from: 440260, jp: `${unit.jp}_LB`, en: ffbeLb?.name || `${unit.en}'s Resonance`,
      desc: "", descAuto: true, set: { element: "None" },
      sequence_edits: { master: [{ match: { EventType: "OtherChangeSubSpaceColor" }, set: { Other_ChangeSubSpaceColor_Color: { R: 0.25, G: 0.25, B: 0.35, A: 1.0 } } }] }, effect_swaps: [] } });
  }
  if (!lb) return <div className="muted">preparing…</div>;
  const mech = finish.find((s) => s.id === lb.from) || finish[0];
  const kind = mech && (mech.dmgType === "Physic" || mech.dmgType === "Magic") && mech.mag > 0 ? "damage" : healing.includes(mech) ? "heal" : buffing.includes(mech) ? "buff" : "debuff";
  const st = lb.set || {};
  const element = st.element || mech?.element || "None";
  const physical = (st.DamageType || mech?.dmgType) === "Physic";
  function autoDesc(from: any, s: any) {
    const base = describe(from, s);
    const fx = (from?.effects || []).map((id: number) => effectLabel(effById[id])).filter(Boolean);
    return [base, ...fx].join(" ");
  }
  function upd(patch: any) {
    const n = { ...lb, ...patch };
    if (n.descAuto !== false) n.desc = autoDesc(finish.find((s) => s.id === n.from), n.set || {});
    set({ lb_custom: n });
  }
  function setMech(id: number) {
    const m = finish.find((s) => s.id === id)!;
    const dmg = (m.dmgType === "Physic" || m.dmgType === "Magic") && m.mag > 0;
    const s: any = { ...st };
    if (dmg) { s.element = st.element ?? m.element; s.DamageType = m.dmgType; s.damageCalcType = m.dmgType; s["SkillIcon.TagName"] = iconTagFor(cat, s.element || "None", m.dmgType === "Physic", false); }
    else { delete s.DamageType; delete s.damageCalcType; s.element = "None"; s["SkillIcon.TagName"] = healing.includes(m) ? "UI.Skill.Action.Icon.Heal" : m.relation === "Enemies" ? "UI.Skill.Action.Icon.BadStatus" : "UI.Skill.Action.Icon.Support"; }
    upd({ from: id, caption_from: id >= 440000 && id < 441000 ? id : lb.caption_from || 440260, set: s });
  }
  function setKind(k: string) {
    const pool = k === "damage" ? damaging : k === "heal" ? healing : k === "buff" ? buffing : debuffing;
    if (pool.length) setMech(pool.find((s) => s.target === "Group") ? pool.find((s) => s.target === "Group")!.id : pool[0].id);
  }
  function setDamageType(phys: boolean) {
    const pool = damaging.filter((s) => (s.dmgType === "Physic") === phys);
    const same = pool.find((s) => s.target === mech?.target) || pool[0];
    if (same) { setMech(same.id); }
  }
  const vis = lb.visuals ?? lb.from;
  const templ = cat.lbTemplates.find((t) => t.id === vis);
  const pool = kind === "damage" ? damaging.filter((s) => (s.dmgType === "Physic") === physical) : kind === "heal" ? healing : kind === "buff" ? buffing : debuffing;
  return (
    <div className="grid2">
      <div className="panel">
        <h3>Resonance</h3>
        {ffbeLb && <div className="hint" style={{ marginBottom: 8 }}>In Brave Exvius: <b>{ffbeLb.name}</b> — {(ffbeLb.effects || []).join(" · ")}</div>}
        <div className="row"><label>Name</label><input value={lb.en} onChange={(e) => upd({ en: e.target.value })} style={{ flex: 1 }} /></div>
        <div className="row"><label>Animation</label>
          <select value={vis} onChange={(e) => upd({ visuals: +e.target.value, effect_swaps: [] })}>{cat.lbTemplates.map((t) => <option key={t.id} value={t.id}>{label(t)}</option>)}</select>
          <button onClick={() => setStory(!story)}>{story ? "Hide" : "Show what happens"}</button></div>
        <div className="hint" style={{ marginBottom: 10 }}>These are the Resonance animations the demo ships with a full battle sequence; the unit's own limit-burst motion and Tronn's domain are kept.</div>
        <div className="row"><label>It is</label>
          {[["damage", "a damaging ability"], ["heal", "a healing ability"], ["buff", "a buffing ability"], ["debuff", "a debuffing ability"]].map(([k, l]) => <label key={k} style={{ minWidth: 0 }}><input type="radio" checked={kind === k} onChange={() => setKind(k)} /> {l}</label>)}</div>
        {kind === "damage" && <>
          <div className="row"><label>Damage</label>
            <label style={{ minWidth: 0 }}><input type="radio" checked={physical} onChange={() => setDamageType(true)} /> Physical</label>
            <label style={{ minWidth: 0 }}><input type="radio" checked={!physical} onChange={() => setDamageType(false)} /> Magical</label></div>
          <div className="row"><label>Element</label>
            <select value={element} onChange={(e) => upd({ set: { ...st, element: e.target.value, "SkillIcon.TagName": iconTagFor(cat, e.target.value, physical, false) } })}>{ELEMENTS.map((x) => <option key={x} value={x}>{x === "None" ? "Non-elemental" : x}</option>)}</select></div>
          <div className="row"><label>Targets</label>
            <select value={st.TargetType || mech?.target || "Group"} onChange={(e) => upd({ set: { ...st, TargetType: e.target.value } })}><option value="Single">One enemy</option><option value="Group">All enemies</option><option value="Random">Random enemies</option></select></div>
        </>}
        <div className="row" style={{ alignItems: "flex-start" }}><label>Numbers like</label>
          <div style={{ flex: 1 }}>
            <select value={lb.from} onChange={(e) => setMech(+e.target.value)} style={{ width: "100%" }}>{pool.map((s) => <option key={s.id} value={s.id}>{label(s)} — {describe(s)}</option>)}</select>
            <div className="hint">The power, hit count and extra effects of that vision's Resonance, with your element and damage type applied.</div>
            {mech && <div style={{ marginTop: 6 }}>{(mech.effects as number[]).map((id) => effectLabel(effById[id])).filter(Boolean).map((t, i) => <span key={i} className="chip" style={{ marginLeft: 0, marginRight: 6 }}>{t}</span>)}</div>}
          </div></div>
        <div className="row" style={{ alignItems: "flex-start" }}><label>Description</label>
          <div style={{ flex: 1 }}><textarea value={lb.desc} readOnly={lb.descAuto !== false} onChange={(e) => upd({ desc: e.target.value, descAuto: false })} />
            <label className="muted" style={{ minWidth: 0 }}><input type="checkbox" checked={lb.descAuto !== false} onChange={(e) => upd({ descAuto: e.target.checked })} /> write it for me</label></div></div>
      </div>
      <div className="panel">
        <h3>Animation: {templ ? label(templ) : "-"}</h3>
        {story ? <Storyboard skillId={vis} form={unit.ffbe?.id} cat={cat} /> : <div className="muted">"Show what happens" lists the animation's motions, effects and camera moves in order, using this unit's own sprites for the motions.</div>}
      </div>
    </div>
  );
}
