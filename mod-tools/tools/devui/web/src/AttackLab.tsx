import { useEffect, useMemo, useRef, useState } from 'react';
import type { Unit } from './api';
import './attack-lab.css';

type Settings = Record<string, any> & { layers: Record<string, Record<string, any>> };
type Move = { sourceKey: string; name: string; kind: string; status: string; prepared: boolean };
type Layer = { id: string; name: string; anchor: string; order: string; frame: number; frames: number; phase: string };
type Detail = { form: string; key: string; name: string; kind: string; prepared: boolean; moving: boolean;
  settings: Settings; layers: Layer[]; durationFrames: number; sounds: number; hasOverride: boolean; issues: string[] };

async function request(path: string, body?: any, method = 'POST') {
  const response = await fetch('/api/attack-lab' + path, body === undefined ? undefined : {
    method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Request failed (${response.status})`);
  }
  return response.json();
}

function NumberControl({ label, value, min, max, step = .01, suffix = '', onChange }:
  { label: string; value: number; min: number; max: number; step?: number; suffix?: string; onChange: (n: number) => void }) {
  const id = 'attack-' + label.replace(/\W/g, '-').toLowerCase();
  function change(text: string) {
    const n = Number(text);
    if (text !== '' && Number.isFinite(n)) onChange(Math.max(min, Math.min(max, n)));
  }
  return <div className="al-number">
    <label htmlFor={id}>{label}</label>
    <div><input aria-label={label + ' slider'} type="range" min={min} max={max} step={step} value={value} onChange={e => change(e.target.value)} />
      <input id={id} type="number" min={min} max={max} step={step} value={value} onChange={e => change(e.target.value)} /><span>{suffix}</span></div>
  </div>;
}

const STAGES = ['Visibility', 'Cast close-up', 'Action framing', 'Effects & sound', 'Return & restore'];
// Keep in-progress edits when the surrounding Studio switches tools or modes.
// Only the explicit Save/Build actions write these values to the game profile.
const drafts = new Map<string, Settings>();
const selectedMoves = new Map<string, string>();
let lastForm = '';
const draftId = (form: string, key: string) => form + ':' + key;

export default function AttackLab({ unit, onBeforeBuild }: { unit: Unit | null; onBeforeBuild: () => Promise<boolean> }) {
  const [catalog, setCatalog] = useState<any>(null);
  const [query, setQuery] = useState('');
  const [vision, setVision] = useState('');
  const [form, setForm] = useState(lastForm || unit?.ffbe?.id || '100032707');
  const [moves, setMoves] = useState<Move[]>([]);
  const [moveQuery, setMoveQuery] = useState('');
  const [key, setKey] = useState('');
  const [detail, setDetail] = useState<Detail | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [selectedLayer, setSelectedLayer] = useState(0);
  const [tab, setTab] = useState('Camera');
  const [dirty, setDirty] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [progress, setProgress] = useState<any>(null);
  const [pending, setPending] = useState(false);
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(false);
  const revision = useRef(0);

  useEffect(() => {
    request('/catalog').then(data => {
      setCatalog(data);
      const owner = data.units.find((u: any) => u.forms.includes(form)) || data.units[0];
      if (owner) { setVision(owner.id); if (!owner.forms.includes(form)) setForm(owner.forms[0]); }
    }).catch(e => setError(e.message));
    let alive = true;
    async function poll() {
      try { const data = await request('/progress'); if (alive) setProgress(data); }
      catch (e: any) { if (alive) setError('Progress connection lost. ' + e.message); }
    }
    poll(); const timer = window.setInterval(poll, 1800);
    return () => { alive = false; window.clearInterval(timer); };
  }, []);

  useEffect(() => {
    const current = ++revision.current;
    setDetail(null); setSettings(null); setMoves([]); setError(''); setPlaying(false);
    request('/moves/' + encodeURIComponent(form)).then(data => {
      if (current !== revision.current) return;
      setMoves(data.moves);
      const chosen = data.moves.find((m: Move) => m.sourceKey === selectedMoves.get(form)) || data.moves.find((m: Move) => m.kind === 'LB' && m.prepared) || data.moves.find((m: Move) => m.prepared) || data.moves[0];
      setKey(chosen?.sourceKey || '');
    }).catch(e => { if (current === revision.current) setError(e.message); });
  }, [form]);

  useEffect(() => {
    if (!key) return;
    let alive = true;
    setDetail(null); setSettings(null); setPlaying(false); setFrame(0); setError('');
    request('/move?' + new URLSearchParams({ form, key })).then(data => {
      if (!alive) return;
      const draft = drafts.get(draftId(form, key));
      setDetail(data); setSettings(draft || data.settings); setDirty(!!draft); setSelectedLayer(0); setMessage('');
      lastForm = form; selectedMoves.set(form, key);
    }).catch(e => { if (alive) setError(e.message); });
    return () => { alive = false; };
  }, [form, key]);

  const total = (detail?.durationFrames || 60) + 120;
  useEffect(() => {
    if (progress?.result !== 'complete' || !key) return;
    let alive = true;
    Promise.all([request('/move?' + new URLSearchParams({ form, key })), request('/moves/' + encodeURIComponent(form))])
      .then(([prepared, available]) => { if (alive) { setDetail(prepared); setMoves(available.moves); } })
      .catch(e => { if (alive) setError(e.message); });
    return () => { alive = false; };
  }, [progress?.ended, form, key]);
  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => setFrame(f => (f + 12) % total), 200);
    return () => window.clearInterval(timer);
  }, [playing, total]);

  const visibleVisions = (catalog?.units || []).filter((u: any) => (u.name + ' ' + u.id).toLowerCase().includes(query.toLowerCase()));
  const owner = catalog?.units.find((u: any) => u.id === vision);
  const visibleMoves = moves.filter(m => (m.name + ' ' + m.kind).toLowerCase().includes(moveQuery.toLowerCase()));
  const layer = detail?.layers[selectedLayer];
  const layerSettings = settings && layer ? settings.layers[layer.id] || {} : {};
  const busy = pending || progress?.running;
  const stage = frame < 12 ? 0 : frame < 60 ? 1 : frame < 72 ? 2 : frame < total - 48 ? 3 : 4;

  function update(name: string, value: any) {
    setSettings(s => { if (!s) return s; const next = { ...s, [name]: value }; drafts.set(draftId(form, key), next); return next; }); setDirty(true); setMessage('');
  }
  function updateLayer(name: string, value: any) {
    if (!layer) return;
    setSettings(s => { if (!s) return s; const next = { ...s, layers: { ...s.layers, [layer.id]: { ...s.layers[layer.id], [name]: value } } }; drafts.set(draftId(form, key), next); return next; });
    setDirty(true); setMessage('');
  }
  async function save(scope = 'move') {
    await request('/settings', { scope, form, key, settings }, 'PUT');
    if (scope === 'move') { setDirty(false); drafts.delete(draftId(form, key)); }
    setMessage(scope === 'defaults' ? 'Saved as defaults for every ability. Per-move overrides take priority.' : 'Move settings saved.');
  }
  async function action(work: () => Promise<void>) {
    setPending(true); setError('');
    try { await work(); } catch (e: any) { setError(e.message); }
    finally { setPending(false); }
  }
  async function build(scope: string, install: boolean) {
    if (!await onBeforeBuild()) return;
    if (dirty) await save();
    await request('/build', { scope, form, key, install });
    setProgress(await request('/progress'));
  }
  async function reset() {
    await request('/settings', { scope: 'reset', form, key }, 'PUT');
    drafts.delete(draftId(form, key));
    const data = await request('/move?' + new URLSearchParams({ form, key }));
    setSettings(data.settings); setDetail(data); setDirty(false); setMessage('Using shared defaults.');
  }
  function canLeave() {
    if (!dirty) return true;
    if (!window.confirm('Discard unsaved attack settings for this move?')) return false;
    drafts.delete(draftId(form, key)); return true;
  }

  return <section className="attack-lab" aria-labelledby="attack-lab-title">
    <header className="al-header">
      <div><h2 id="attack-lab-title">Attack Lab</h2><p>Shape the cast, frame the hit, restore the battlefield.</p></div>
      <span className="al-save-state" role="status">{dirty ? 'Unsaved settings' : message || 'Settings saved locally'}</span>
    </header>
    {error && <div className="al-error" role="alert">{error}<button onClick={() => setError('')}>Dismiss</button></div>}
    <div className="al-selection">
      <div><label htmlFor="al-search-visions">Find a vision</label><input id="al-search-visions" type="search" placeholder="Name or ID" value={query} onChange={e => setQuery(e.target.value)} />
        <select aria-label="Vision" value={vision} onChange={e => {
          if (!canLeave()) return;
          setVision(e.target.value); const row = catalog.units.find((u: any) => u.id === e.target.value);
          setForm(row.forms[row.forms.length - 1]); setDirty(false);
        }}>
          {!visibleVisions.some((u: any) => u.id === vision) && owner && <option value={vision}>{owner.name}</option>}
          {visibleVisions.map((u: any) => <option key={u.id} value={u.id}>{u.name}</option>)}
        </select></div>
      <div><label htmlFor="al-form">Form</label><select id="al-form" value={form} onChange={e => { if (canLeave()) { setForm(e.target.value); setDirty(false); } }}>
        {(owner?.forms || [form]).map((f: string) => <option key={f} value={f}>{f}{catalog?.imported[f] ? ' · In your mod' : ''}</option>)}</select>
        <p>{catalog ? `${catalog.units.length.toLocaleString()} visions · Every active move` : 'Loading vision catalog…'}</p></div>
      <div><label htmlFor="al-search-moves">Find a move</label><input id="al-search-moves" type="search" placeholder="Ability, magic or LB" value={moveQuery} onChange={e => setMoveQuery(e.target.value)} />
        <select aria-label="Move" value={key} onChange={e => { if (canLeave()) { setKey(e.target.value); setDirty(false); } }}>
          {!visibleMoves.some(m => m.sourceKey === key) && moves.find(m => m.sourceKey === key) && <option value={key}>{moves.find(m => m.sourceKey === key)?.name}</option>}
          {visibleMoves.map(m => <option key={m.sourceKey} value={m.sourceKey}>{m.name} · {m.kind}{m.status !== 'ready' ? ' · Held' : m.prepared ? '' : ' · Needs preparation'}</option>)}
        </select></div>
    </div>
    {!detail || !settings ? <div className="al-empty" role="status">{error ? 'Choose another form or move to continue.' : 'Loading the selected attack…'}</div> : <>
      <div className="al-workbench">
        <div className="al-viewer">
          <div className="al-move-title"><h3>{detail.name}</h3><span>{detail.kind} · {detail.moving ? 'Moves toward target' : 'Stationary cast'} · {detail.sounds} sound cues</span></div>
          <Composition detail={detail} settings={settings} frame={frame} stage={stage} onError={setError} />
          <div className="al-playback"><button onClick={() => setPlaying(p => !p)} disabled={!detail.prepared}>{playing ? 'Pause' : 'Play'}</button>
            <button onClick={() => { setFrame(0); setPlaying(false); }}>Restart</button>
            <input aria-label="Attack timeline" type="range" min="0" max={total - 1} step="1" value={frame} onChange={e => { setFrame(+e.target.value); setPlaying(false); }} />
            <output>{(frame / 60).toFixed(1)} / {(total / 60).toFixed(1)} s</output></div>
          <ol className="al-stages">{STAGES.map((name, i) => <li key={name}><button aria-current={stage === i ? 'step' : undefined} onClick={() => { setPlaying(false); setFrame([0, 24, 60, 84, total - 40][i]); }}><span>{i + 1}</span>{name}</button></li>)}</ol>
          <p className="al-preview-note">Composition preview uses prepared particles and the vision’s sprite. Camera, enemy size and playback here are approximations; sound plays in the game.</p>
          {!detail.prepared && <p className="al-notice">This move has no prepared effects yet. Building it will run the offline converter first.</p>}
          {detail.issues.length > 0 && <details className="al-issues"><summary>Source limitations ({detail.issues.length})</summary><ul>{detail.issues.map((issue, i) => <li key={i}>{issue}</li>)}</ul></details>}
        </div>
        <div className="al-inspector">
          <div className="al-tabs" role="tablist" aria-label="Attack controls">{['Camera', 'Layers', 'Behavior'].map(name => <button role="tab" aria-selected={tab === name} key={name} onClick={() => setTab(name)}>{name}</button>)}</div>
          {tab === 'Camera' && <div role="tabpanel" aria-label="Camera settings">
            <h3>Cast close-up</h3><p>For moving attacks, focus on the destination before the vision arrives.</p>
            <NumberControl label="Cast zoom" value={settings.castZoom} min={.5} max={3} suffix="×" onChange={n => update('castZoom', n)} />
            <NumberControl label="Cast horizontal position" value={settings.castX} min={.15} max={.85} onChange={n => update('castX', n)} />
            <NumberControl label="Cast vertical position" value={settings.castY} min={.2} max={.8} onChange={n => update('castY', n)} />
            <h3>Action framing</h3><p>Moving attacks frame the vision and selected targets. Stationary attacks return to the normal view.</p>
            <NumberControl label="Action zoom" value={settings.actionZoom} min={.5} max={3} suffix="×" onChange={n => update('actionZoom', n)} />
            <NumberControl label="Action horizontal position" value={settings.actionX} min={.15} max={.85} onChange={n => update('actionX', n)} />
            <NumberControl label="Action vertical position" value={settings.actionY} min={.2} max={.8} onChange={n => update('actionY', n)} />
            <NumberControl label="Participant height allowance" value={settings.frameHeight} min={.1} max={.75} onChange={n => update('frameHeight', n)} />
            <NumberControl label="Pan duration" value={settings.panFrames} min={1} max={120} step={1} suffix="frames" onChange={n => update('panFrames', n)} />
            <NumberControl label="Restore duration" value={settings.restoreFrames} min={1} max={120} step={1} suffix="frames" onChange={n => update('restoreFrames', n)} />
            <p>1× is the normal game lens. Higher values zoom in. Groups may widen to keep participants visible. Camera frames run at 30 per second.</p>
          </div>}
          {tab === 'Layers' && <div role="tabpanel" aria-label="Layer settings">
            <h3>Whole effect</h3>
            <NumberControl label="Effect size" value={settings.scale} min={.05} max={8} suffix="×" onChange={n => update('scale', n)} />
            <NumberControl label="Effect left or right" value={settings.offsetX} min={-2000} max={2000} step={1} onChange={n => update('offsetX', n)} />
            <NumberControl label="Effect up or down" value={settings.offsetY} min={-2000} max={2000} step={1} onChange={n => update('offsetY', n)} />
            <label className="al-select-label" htmlFor="al-background">Background layers</label><select id="al-background" value={settings.backgroundMode} onChange={e => update('backgroundMode', e.target.value)}><option value="target">Behind targets, on the battlefield</option><option value="screen">Cover the screen behind participants</option><option value="hidden">Hide background layers</option></select>
            <NumberControl label="Background depth" value={settings.backDepth} min={1} max={1000} step={1} onChange={n => update('backDepth', n)} />
            <NumberControl label="Attack depth" value={settings.frontDepth} min={-1000} max={-1} step={1} onChange={n => update('frontDepth', n)} />
            <h3>Individual layer</h3>
            {detail.layers.length ? <><select aria-label="Layer to edit" value={selectedLayer} onChange={e => setSelectedLayer(+e.target.value)}>{detail.layers.map((l, i) => <option key={l.id + i} value={i}>{i + 1}. {l.phase} · {l.anchor} · {l.order}</option>)}</select>
              <label className="al-check"><input type="checkbox" checked={layerSettings.enabled !== false} onChange={e => updateLayer('enabled', e.target.checked)} />Show this layer</label>
              <label className="al-select-label" htmlFor="al-layer-anchor">Attach to</label><select id="al-layer-anchor" value={layerSettings.anchor || 'source'} onChange={e => updateLayer('anchor', e.target.value)}><option value="source">Source attachment ({layer?.anchor})</option><option value="caster">Vision</option><option value="target">Target</option><option value="screen">Screen</option></select>
              <label className="al-select-label" htmlFor="al-layer-order">Draw position</label><select id="al-layer-order" value={layerSettings.order || 'source'} onChange={e => updateLayer('order', e.target.value)}><option value="source">Source order ({layer?.order})</option><option value="back">Behind target</option><option value="front">In front of target</option></select>
              <NumberControl label="Layer size" value={layerSettings.scale ?? 1} min={.05} max={8} suffix="×" onChange={n => updateLayer('scale', n)} />
              <NumberControl label="Layer left or right" value={layerSettings.offsetX ?? 0} min={-2000} max={2000} step={1} onChange={n => updateLayer('offsetX', n)} />
              <NumberControl label="Layer up or down" value={layerSettings.offsetY ?? 0} min={-2000} max={2000} step={1} onChange={n => updateLayer('offsetY', n)} />
              <NumberControl label="Layer depth" value={layerSettings.depth ?? ((layerSettings.order || layer?.order) === 'back' ? settings.backDepth : settings.frontDepth)} min={-1000} max={1000} step={1} onChange={n => updateLayer('depth', n)} />
              <button onClick={() => { const next = { ...settings.layers }; delete next[layer!.id]; update('layers', next); }}>Reset this layer</button>
            </> : <p>No prepared particle layers for this move.</p>}
            <p>Offsets are SpriteStudio units: positive horizontal goes right; positive vertical goes up. Size and offset changes leave the source timing intact.</p>
          </div>}
          {tab === 'Behavior' && <div role="tabpanel" aria-label="Attack behavior">
            <h3>Five-stage playback</h3>
            <label className="al-check"><input type="checkbox" checked={settings.camera} onChange={e => update('camera', e.target.checked)} />Enable cast and action camera</label>
            <label className="al-check"><input type="checkbox" checked={settings.hideMovingAura} onChange={e => update('hideMovingAura', e.target.checked)} />Hide blue aura while the vision moves</label>
            <label className="al-check"><input type="checkbox" checked={settings.hideLbNonParticipants} onChange={e => update('hideLbNonParticipants', e.target.checked)} />Hide nonparticipants during LBs</label>
            <p>Single-target LBs retain the chosen target. AoE LBs retain every selected target. Ordinary abilities retain the rest of the battlefield.</p>
            <p>Movement stays on the ground. Jumps come from the vision’s own animation. Effects finish before the vision returns and visibility restores.</p>
            <p>Full-screen background replacement is disabled. The background controls place its artwork within the current battlefield.</p>
          </div>}
        </div>
      </div>
      <footer className="al-actions">
        <div><button disabled={pending || !dirty} onClick={() => action(() => save())}>Save this move</button><button disabled={pending} onClick={() => action(() => save('defaults'))}>Use as all-unit defaults</button><button disabled={pending} onClick={() => action(reset)}>Reset move to defaults</button></div>
        <div><button disabled={busy || moves.find(m => m.sourceKey === key)?.status !== 'ready'} onClick={() => action(() => build('move', false))}>Build selected</button>
          <button className="al-install" disabled={busy || progress?.gameRunning || moves.find(m => m.sourceKey === key)?.status !== 'ready'} onClick={() => action(() => build('move', true))}>Build & install selected</button>
          <button disabled={busy || !catalog?.bulkAvailable} onClick={() => action(() => build('all', false))}>Build all units</button></div>
        <p>{progress?.gameRunning ? 'Close the game to install. You can keep editing.' : 'Selected builds include your existing mod and the chosen move. All-unit builds create portable bundles for every eligible ability, magic spell and LB.'}</p>
      </footer>
    </>}
    {progress && (progress.running || progress.result) && <section className="al-progress" aria-label="Build progress">
      <div><h3>{progress.stage}</h3><span role="status">{progress.running ? 'Running' : progress.result === 'complete' ? 'Complete' : 'Needs attention'}</span></div>
      {progress.counts && <><progress max={progress.counts.selectedForms || 1} value={progress.counts.processedForms || 0} /><p>{progress.counts.processedForms?.toLocaleString()} / {progress.counts.selectedForms?.toLocaleString()} forms processed · {progress.counts.bundledForms || 0} bundled · {progress.counts.failedForms || 0} failed</p></>}
      <p>{progress.message}</p><details open={progress.result === 'failed'}><summary>Build log</summary><pre>{progress.log?.slice(-60).join('\n')}</pre></details>
    </section>}
  </section>;
}

function Composition({ detail, settings, frame, stage, onError }: { detail: Detail; settings: Settings; frame: number; stage: number; onError: (error: string) => void }) {
  const moved = detail.moving && stage > 0 && stage < 4;
  const cast = stage === 1;
  const zoom = !settings.camera || stage === 0 || stage === 4 || (!detail.moving && stage >= 2) ? 1 : cast ? settings.castZoom : settings.actionZoom;
  const casterX = moved ? 56 : 79;
  const targetX = 30;
  const focusX = cast ? casterX : (casterX + targetX) / 2;
  const centerX = cast ? settings.castX * 100 : settings.actionX * 100;
  const centerY = cast ? settings.castY * 100 : settings.actionY * 100;
  const panX = zoom === 1 ? 0 : centerX - focusX;
  const panY = zoom === 1 ? 0 : centerY - 53;
  const actionFrame = frame - 60;
  const ordered = useMemo(() => detail.layers.map((layer, index) => ({ layer, index })).sort((a, b) => {
    const depth = (l: Layer) => settings.layers[l.id]?.depth ?? ((settings.layers[l.id]?.order || l.order) === 'back' ? settings.backDepth : settings.frontDepth);
    return depth(b.layer) - depth(a.layer);
  }), [detail, settings]);
  return <div className="al-scene" aria-label="Approximate attack composition">
    <div className="al-world" style={{ transform: `translate(${panX}%, ${panY}%) scale(${zoom})`, transformOrigin: `${focusX}% 53%` }}>
      <div className="al-ground" />
      {!((detail.kind === 'LB') && settings.hideLbNonParticipants && stage > 0 && stage < 4) && <div className="al-party">Other units</div>}
      <div className="al-target" style={{ left: targetX + '%' }}><span>Target</span></div>
      {!(detail.moving && settings.hideMovingAura && stage > 0 && stage < 4) && <div className="al-aura" style={{ left: casterX + '%' }}>Aura</div>}
      <img className="al-vision" style={{ left: casterX + '%' }} alt={detail.name + ' vision sprite'} src={`/api/ffbe/anim/${detail.form}/${stage < 2 || stage === 4 ? 'idle' : detail.kind === 'LB' ? 'limitatk' : 'magicatk'}.webp`} />
      {ordered.map(({ layer, index }) => {
        const local = settings.layers[layer.id] || {};
        const order = local.order && local.order !== 'source' ? local.order : layer.order;
        if (local.enabled === false || (layer.anchor === 'screen' && order === 'back' && settings.backgroundMode === 'hidden')) return null;
        const sample = (layer.phase === 'cast' ? frame - 12 : actionFrame) - layer.frame;
        if (sample < 0 || sample >= layer.frames || stage === 4) return null;
        let anchor = local.anchor && local.anchor !== 'source' ? local.anchor : layer.anchor;
        if (anchor === 'screen' && order === 'back' && settings.backgroundMode === 'target') anchor = 'target';
        const x = anchor === 'screen' ? 50 : anchor === 'caster' ? casterX : targetX;
        const y = anchor === 'screen' ? 50 : 66;
        const offsetX = settings.offsetX + (local.offsetX || 0);
        const offsetY = settings.offsetY + (local.offsetY || 0);
        const scale = settings.scale * (local.scale ?? 1);
        const depth = local.depth ?? (order === 'back' ? settings.backDepth : settings.frontDepth);
        return <img key={layer.id + index} className="al-effect" alt="" aria-hidden="true" style={{ left: `calc(${x}% + ${offsetX * .32}px)`, top: `calc(${y}% - ${offsetY * .32}px)`, width: 800 * scale, zIndex: depth > 0 ? 1 : 4, transform: 'translate(-50%, -50%)' }}
          src={'/api/attack-lab/layer?' + new URLSearchParams({ form: detail.form, key: detail.key, index: String(index), frame: String(sample) })}
          onError={() => onError('A prepared layer could not be previewed. Its game build may still be available; check the source limitations and build log.')} />;
      })}
    </div>
    <span className="al-preview-label">{STAGES[stage]} · {zoom.toFixed(2)}×</span>
  </div>;
}
