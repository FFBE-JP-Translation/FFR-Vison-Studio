import { useEffect, useState } from 'react';
import { api, Catalog, Unit } from './api';

const STAT_NAMES: Record<string, string> = { MaxHitPoint: 'HP', MaxMagicPoint: 'MP', Attack: 'Attack', Defence: 'Defence', Intelligence: 'Intelligence', Mind: 'Mind', Agility: 'Agility' };
const ELEMENTS = ['None', 'Fire', 'Ice', 'Wind', 'Earth', 'Thunder', 'Water', 'Light', 'Dark'];

async function readJson(file: File) {
  if (file.size > 2 * 1024 * 1024) throw new Error('JSON files must be smaller than 2 MiB.');
  try { return JSON.parse(await file.text()); }
  catch { throw new Error(`${file.name} is not valid JSON. Check its commas and quotation marks.`); }
}

async function encoded(file: File) {
  if (file.size > 16 * 1024 * 1024) throw new Error(`${file.name} must be smaller than 16 MiB.`);
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error(`Could not read ${file.name}. Choose the file again.`));
    reader.onload = () => resolve(String(reader.result).split(',')[1]);
    reader.readAsDataURL(file);
  });
}

export default function CustomUnit({ cat, onAdded, onClose }: { cat: Catalog; onAdded: (u: Unit) => void; onClose: () => void }) {
  const [doc, setDoc] = useState<any>(null);
  const [sheet, setSheet] = useState<File | null>(null);
  const [icon, setIcon] = useState<File | null>(null);
  const [animations, setAnimations] = useState<any>(null);
  const [preview, setPreview] = useState('');
  const [hitFrames, setHitFrames] = useState('12, 24');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    fetch('/api/custom/template/unit').then(r => { if (!r.ok) throw new Error('Could not load the unit template. Reopen Create a unit to retry.'); return r.json(); }).then(setDoc).catch(e => setError(e.message));
  }, []);
  useEffect(() => {
    if (!sheet) { setPreview(''); return; }
    const url = URL.createObjectURL(sheet); setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [sheet]);
  const update = (patch: any) => setDoc({ ...doc, ...patch });
  async function loadUnit(file: File) {
    try {
      const data = await readJson(file);
      if (data?.schema !== 'ffr-custom-unit-1' || typeof data.name !== 'string' || typeof data.key !== 'string' ||
          (data.stats != null && (typeof data.stats !== 'object' || Array.isArray(data.stats))) ||
          (data.resonance != null && (typeof data.resonance !== 'object' || Array.isArray(data.resonance))) ||
          (data.skills != null && !Array.isArray(data.skills))) throw new Error('Use the downloadable unit JSON template: it needs a name, key, stats and resonance.');
      setDoc({ ...doc, ...data, stats: { ...doc.stats, ...data.stats }, resonance: { ...doc.resonance, ...data.resonance } });
      setHitFrames((data.resonance?.hitFrames || [12, 24]).join(', ')); setError('');
    } catch (e: any) { setError(e.message); }
  }
  async function loadAnimations(file: File) {
    try {
      const data = await readJson(file);
      if (data?.schema !== 'ffr-animations-1' || data.fps !== 60 || !data.animations || typeof data.animations !== 'object' || Array.isArray(data.animations)) throw new Error('Use the animation JSON template with fps 60 and an animations object.');
      setAnimations(data); setError('');
    } catch (e: any) { setAnimations(null); setError(e.message); }
  }
  async function create(event: React.FormEvent) {
    event.preventDefault(); if (!sheet || !animations) return;
    setBusy(true); setError('');
    try {
      const values = hitFrames.split(',').map(s => s.trim());
      if (values.some(s => !/^\d+$/.test(s))) throw new Error('Enter hit frames as whole numbers separated by commas, such as 12, 24.');
      const body = { unit: { ...doc, resonance: { ...doc.resonance, hitFrames: values.map(Number) } }, animations, sheet: await encoded(sheet), icon: icon ? await encoded(icon) : undefined };
      const result = await api.addCustom(body); onAdded(result.unit);
    } catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  }
  return <form className="custom-unit" onSubmit={create} aria-busy={busy}>
    <div className="toolbar"><h2>Create a unit</h2><span className="spacer" /><button type="button" disabled={busy} onClick={onClose}>Back to visions</button></div>
    <p className="muted">Bring your own sprites and animation timing. Fill out the profile or load a unit JSON, then add abilities and refine the resonance in the editor.</p>
    {error && <div className="panel bad" role="alert">{error}</div>}
    {!doc ? <p role="status">Loading unit template…</p> : <fieldset disabled={busy} className="import-fields">
      <div className="grid2 custom-columns">
        <section className="panel">
          <h3>Sprite assets</h3>
          <label className="field">Sprite sheet PNG<input required type="file" accept=".png,image/png" onChange={e => setSheet(e.target.files?.[0] || null)} /></label>
          <p className="hint">Face left. Transparent background, up to 4096 × 4096 pixels. Frames are anchored at the feet.</p>
          <label className="field">Animation JSON<input required type="file" accept=".json,application/json" onChange={e => { const f = e.target.files?.[0]; if (f) loadAnimations(f); else setAnimations(null); }} /></label>
          <p><a href="/api/custom/template/animations" download>Download animation template</a></p>
          <details><summary>How to describe your animations</summary><p>Use a regular grid with <code>frameSize</code>, or a <code>frames</code> list containing <code>rect: [x, y, width, height]</code> and <code>pivot: [x, y]</code>. Frame numbers start at zero and run left to right, then top to bottom.</p><p>Each animation step uses <code>frame</code> and <code>hold</code> (60 frames = 1 second). Optional <code>offset: [x, y]</code> moves the sprite; positive Y points down. Include <code>idle</code>, <code>attack</code> and <code>limitBurst</code>. Other missing motions use idle.</p><p>The template expects six 64 × 64 cells in a 192 × 128 sheet. Replace its dimensions and frame numbers for your artwork. Existing FFBE CSV timelines must be converted to this JSON format.</p></details>
          <label className="field">Portrait PNG (optional)<input type="file" accept=".png,image/png" onChange={e => setIcon(e.target.files?.[0] || null)} /></label>
          <p className="hint">Used inside the menu and command frames. Without a portrait, Studio uses the first idle sprite.</p>
          {preview && <figure className="sheet-preview"><img src={preview} alt="Uploaded sprite sheet" /><figcaption>{sheet?.name}</figcaption></figure>}
          {animations && <p className="muted" role="status">Loaded motions: {Object.keys(animations.animations).join(', ')}</p>}
        </section>
        <section className="panel">
          <h3>Unit profile</h3>
          <div className="template-tools"><a href="/api/custom/template/unit" download>Download example unit JSON</a><label className="field">Or load your unit JSON<input type="file" accept=".json,application/json" onChange={e => { const f = e.target.files?.[0]; if (f) loadUnit(f); }} /></label></div>
          <div className="grid2"><label className="field">Name<input required maxLength={80} value={doc.name} onChange={e => update({ name: e.target.value })} /></label><label className="field">Unique key<input required pattern="[a-z][a-z0-9_]*" maxLength={48} value={doc.key} onChange={e => update({ key: e.target.value })} /><span>Lowercase letters, numbers and underscores.</span></label></div>
          <label className="field">Description<textarea required maxLength={2000} value={doc.description} onChange={e => update({ description: e.target.value })} /></label>
          <div className="grid2"><label className="field">Attack type<select value={doc.attackType} onChange={e => update({ attackType: e.target.value })}><option value="Physic">Physical</option><option value="Magic">Magic</option></select></label><label className="field">Element<select value={doc.element} onChange={e => update({ element: e.target.value })}>{ELEMENTS.map(e => <option key={e}>{e}</option>)}</select></label></div>
          <h3>Base stats in Resonance</h3>
          <div className="custom-stats">{Object.entries(STAT_NAMES).map(([key, label]) => <label key={key} className="field">{label}<input required type="number" min={1} max={key === 'MaxHitPoint' ? 99999 : 9999} value={doc.stats[key]} onChange={e => update({ stats: { ...doc.stats, [key]: Number(e.target.value) } })} /></label>)}<label className="field">Shop price<input required type="number" min={0} max={9999999} value={doc.price} onChange={e => update({ price: Number(e.target.value) })} /></label></div>
          <h3>Resonance</h3>
          <label className="field">Move name<input required maxLength={100} value={doc.resonance.name} onChange={e => update({ resonance: { ...doc.resonance, name: e.target.value } })} /></label>
          <div className="grid2"><label className="field">Hit frames<input required value={hitFrames} onChange={e => setHitFrames(e.target.value)} /><span>1–30 hits, counted from limitBurst frame 0.</span></label><label className="field">Movement<select value={doc.resonance.moveType} onChange={e => update({ resonance: { ...doc.resonance, moveType: Number(e.target.value) } })}><option value={0}>Stay in place</option><option value={1}>Move toward the enemy</option></select></label></div>
          <p className="hint">Damage scales to Cloud's resonance total. The field follows your element. Your limitBurst motion plays with native impact effects and the common charging sound.</p>
          <h3>Starting abilities</h3><p className="hint">Optional. Add more in the editor after importing.</p>
          <select className="custom-skill-list" multiple aria-label="Starting abilities" value={(doc.skills || []).map(String)} onChange={e => update({ skills: Array.from(e.target.selectedOptions).map(o => Number(o.value)) })}>{cat.skills.filter(s => s.seq?.length && ['Ability', 'Magic', 'MagicSword'].includes(s.attr) && s.hasUnit === 'All').map(s => <option key={s.id} value={s.id}>{s.name} · {s.id}</option>)}</select>
        </section>
      </div>
      <div className="custom-actions"><span className="muted" role="status">{busy ? 'Validating files and creating unit…' : 'Creates a unit in your mod. Build and install when you are ready.'}</span><button className="primary" type="submit" disabled={!sheet || !animations}>{busy ? 'Creating unit…' : 'Create unit'}</button></div>
    </fieldset>}
  </form>;
}
