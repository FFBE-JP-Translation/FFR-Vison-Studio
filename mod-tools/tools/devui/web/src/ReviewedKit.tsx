import {useState} from 'react';
import {api, Unit} from './api';

export default function ReviewedKit({unit, set}: {unit: Unit; set: (u: Unit) => void}) {
  const [query, search] = useState('');
  const [filter, selectFilter] = useState('all');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [replacements, setReplacements] = useState<Record<string,string>>({});
  const entries = unit.ffbeLibrary || [];
  const equipped = (key: string) => [...Object.values(unit.skills || {}), ...Object.values(unit.convertedPassives || {}), unit.lb_custom].some(s => s?.ffbe?.source === key);
  async function use(key: string, remove: boolean) {
    setBusy(true); setError('');
    try { set(await api.kitLoadout(unit, key, replacements[key] || undefined, remove)); setReplacements({}); }
    catch(e: any) {setError(e.message);}
    finally {setBusy(false);}
  }
  const shown = entries.filter(e => `${e.name} ${e.id} ${e.description}`.toLowerCase().includes(query.toLowerCase()) &&
    (filter === 'all' || e.kind === filter || filter === 'held' && e.status !== 'ready' || filter === 'equipped' && equipped(e.sourceKey)));
  return <section>
    <h3>Imported FFBE skills</h3>
    <p>{entries.filter(e => e.status === 'ready').length} available · {entries.filter(e => equipped(e.sourceKey)).length} in test loadout · {entries.filter(e => e.status !== 'ready').length} incompatible</p>
    <p className="hint">{unit.ffbeKit?.source} · Form {unit.ffbe?.id}. Your reviewed mappings are applied. Partial conversions retain compatible effects. All moves stay in this kit when you swap loadout slots.</p>
    <p className="hint">Ten custom command slots; eight grants per awakening tier. Build / Install after choosing your test loadout. Gameplay and complete FFBE effect animations still need testing.</p>
    <div className="row"><input aria-label="Search imported FFBE skills" value={query} onChange={e => search(e.target.value)} placeholder="Search the complete kit"/>
      <select aria-label="Filter imported FFBE skills" value={filter} onChange={e => selectFilter(e.target.value)}>
        {Object.entries({all:'All skills',equipped:'Test loadout',ABILITY:'Abilities',MAGIC:'Magic',PASSIVE:'Passives',LB:'Limit bursts',held:'Incompatible'}).map(([k,v]) => <option key={k} value={k}>{v}</option>)}
      </select></div>
    {error && <p role="alert">{error}</p>}
    {shown.map(e => {
      const isEquipped = equipped(e.sourceKey), lb = e.kind === 'LB';
      const slots = e.kind === 'PASSIVE' ? unit.convertedPassives || {} : unit.skills;
      return <details key={e.sourceKey} className="ffbe-skill">
        <summary>{e.name} · {e.kind} · {isEquipped ? 'in test loadout' : e.status === 'ready' ? e.class === 'partial' ? 'available · partial' : 'available' : 'incompatible'}</summary>
        <p>{e.description}</p>
        {[...(e.issues || []), ...(e.changes || [])].map((s,i) => <p className="hint" key={i}>{s}</p>)}
        <p className="hint">{e.origin} · {e.sourceKey}</p>
        {e.status === 'ready' && <div className="row">
          {!isEquipped && !lb && <select aria-label={`Loadout slot for ${e.name}`} value={replacements[e.sourceKey] || ''} onChange={v => setReplacements({...replacements, [e.sourceKey]:v.target.value})}>
            <option value="">Use an empty loadout slot</option>{Object.entries(slots).map(([id,s]) => <option key={id} value={id}>Replace {s.en || id}</option>)}
          </select>}
          <button disabled={busy || isEquipped && lb} onClick={() => use(e.sourceKey,isEquipped)}>{isEquipped ? lb ? 'Current Resonance' : 'Remove from test loadout' : lb ? 'Use as Resonance' : 'Use in test loadout'}</button>
        </div>}
      </details>;
    })}
  </section>;
}
