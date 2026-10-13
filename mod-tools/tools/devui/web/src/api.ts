// thin client for tools/devui/server.py
export type Grant = (string | number)[];
export interface Unit {
  key: string; jp: string; en: string; id: number; sort: number; desc: string; donor: number;
  ffbe?: { dir: string; id: string; source?: string; base?: string };
  attackType: string; roles: string[]; stats: Record<string, number>; elemRes: Record<string, string>;
  command: { id: number; en: string; desc: string }; master: { id: number; en: string; desc: string };
  price: number; menuScale?: number; icon?: { style: string; rarity: string };
  lb: number; lb_custom?: any; skills: Record<string, any>; awakening: Grant[][]; synchro: Grant[][];
  ffbeMap?: { skills: Record<string, number>; passives: Record<string, any> };
  convertedPassives?: Record<string, any>; conversionReview?: any[];
  ffbeLibrary?: any[]; ffbeKit?: any;
  custom?: { schema: number; animations: string[]; warnings: string[] };
}
export interface Catalog {
  skills: any[]; passives: any[]; effects: any[]; visions: any[]; icons: any[]; niagara: string[]; sequences: any[];
  lbTemplates: any[]; motions: { name: string; ffbe: string }[]; skillMotions: string[]; enums: Record<string, string[]>; unusedIconTags: number[];
  colorGrading: { id: number; name: string }[];
}
export type Layout = Record<string, Record<string, number>>;

async function j<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  if (!r.ok) {
    let msg = r.statusText;
    try { const b = await r.json(); msg = b.detail || JSON.stringify(b); } catch {}
    throw new Error(msg);
  }
  return r.json();
}
const json = (body: any): RequestInit => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const api = {
  catalog: () => j<Catalog>("/api/ffr/catalog"),
  ffbeUnits: () => j<any[]>("/api/ffbe/units"),
  ffbeUnit: (id: string) => j<any>(`/api/ffbe/unit/${id}`),
  ffbeEffects: (kind: string, id: string) => j<any>(`/api/ffbe/effects/${kind}/${id}`),
  ffbeEffectLayers: (kind: string, id: string) => j<any>(`/api/ffbe/effects/layers/${kind}/${id}`),
  ffbeEffectPreview: (body: any) => j<any>("/api/ffbe/effects/preview", { ...json(body), method: "POST" }),
  ffbeEffectPreviewState: (job: string) => j<any>(`/api/ffbe/effects/preview/${job}/state`),
  spec: () => j<Unit[]>("/api/spec"),
  saveSpec: (units: Unit[]) => j<any>("/api/spec", { ...json(units), method: "PUT" }),
  addUnit: (body: { ffbeId: string; form?: string; name?: string; key?: string; autoport?: boolean }) => j<Unit>("/api/spec/add", json(body)),
  prepareAssets: (ffbeId: string, form: string) => j<{ job: string }>("/api/assets/prepare", json({ ffbeId, form })),
  assetProgress: (job: string) => j<any>(`/api/assets/prepare/${job}`),
  addCustom: (body: any) => j<{ unit: Unit; warnings: string[] }>("/api/spec/custom", json(body)),
  delUnit: (key: string) => j<any>(`/api/spec/${key}`, { method: "DELETE" }),
  autoport: (key: string) => j<Unit>(`/api/spec/${key}/autoport`, { method: "POST" }),
  portAbility: (unit: Unit, ability: any, region?: string, effectChoices: Record<string, string> = {}) => j<Unit>("/api/ffbe/ability/import", json({ unit, ability, region, effectChoices })),
  importKit: (unit: Unit) => j<Unit>("/api/ffbe/kit/import", json({ unit })),
  kitLoadout: (unit: Unit, sourceKey: string, replaceId?: string, remove = false) => j<Unit>('/api/ffbe/kit/loadout', json({unit, sourceKey, replaceId, remove})),
  layout: () => j<Layout>("/api/layout"),
  saveLayout: (l: Layout) => j<any>("/api/layout", { ...json(l), method: "PUT" }),
  seq: (skillId: number) => j<any>(`/api/seq/${skillId}`),
  build: (install: boolean) => j<any>("/api/build", json({ install })),
  buildLog: () => j<{ running: boolean; result: string | null; log: string[] }>("/api/build/log"),
  install: () => j<any>("/api/install", { method: "POST" }),
  status: () => j<any>("/api/status"),
  setup: (body: any) => j<any>("/api/setup", json(body)),
  setupLog: () => j<any>("/api/setup/log"),
};

export const uniqueSkillBase = (vid: number) => 445000 + (vid - 13100) * 100;
export const lbId = (vid: number) => 440000 + (vid - 13099) * 10;
export const short = (s: string) => (s || "").replace(/^e\w+::/, "");
export const iconUrl = (cat: Catalog | null, tag: string) => {
  const ic = cat?.icons.find((i) => i.tag === tag);
  return ic?.png ? `/api/ffr/icon/${ic.png}` : null;
};
export const iconLabel = (tag: string) => (tag || "").replace("UI.Skill.Action.Icon.", "").replace("UI.Skill.Command.Icon.", "Command ");

const TARGET_TEXT: Record<string, string> = { "Single|Enemies": "one enemy", "Group|Enemies": "all enemies", "Random|Enemies": "random enemies", "Spread|Enemies": "enemies in a line",
  "Single|Friendlies": "one ally", "Group|Friendlies": "all allies", "Self|Friendlies": "self", "Self|Enemies": "self" };
/** plain-language description of an FFR skill row with the spec's overrides applied for a manually selected native skill */
export function describe(row: any, o: Record<string, any> = {}): string {
  if (!row) return "";
  const dmg = o.DamageType ?? row.dmgType; const target = o.TargetType ?? row.target; const rel = row.relation;
  const element = o.element ?? row.element; const hits = o.hitCount ?? row.hits ?? 1; const mag = o.magnification ?? row.mag ?? 0; const brk = o.breakDamageValue ?? row.breakDmg ?? 0;
  const who = TARGET_TEXT[`${target}|${rel}`] || `${target} ${rel}`.toLowerCase();
  const el = !element || element === "None" ? "" : element + " ";
  let s: string;
  if ((dmg === "Physic" || dmg === "Magic") && mag > 0) { s = `Deal ${el}${dmg === "Physic" ? "physical" : "magic"} damage to ${who}`; if (hits > 1) s += ` (${hits} hits)`; }
  else if (row.effectType === "DamageAndRecovery" && rel === "Friendlies") s = `Restore HP to ${who}`;
  else if (brk > 0 && mag === 0) s = `Break attack on ${who} (no damage)`;
  else s = `${row.name || "Effect"} on ${who}`;
  if (brk >= 9999) s += ", staggers instantly"; else if (brk >= 40) s += ", high break power";
  return s + ".";
}
