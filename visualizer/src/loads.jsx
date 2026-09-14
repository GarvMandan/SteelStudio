/* Snow lookup and additional load layer editing.
 *
 * Both restore desktop capability the web app had lost: the desktop could
 * look up a published ground snow load from city/state, and could name,
 * colour, delete and per-bay paint additional load layers. The web app
 * previously offered a bare number field and a single "add to all bays"
 * button.
 */
import React, {useState} from 'react';
import {Search, Plus, Trash2, LoaderCircle, ExternalLink, Info} from 'lucide-react';

const letter = i => { let s = ''; for (i++; i; i = Math.floor((i - 1) / 26)) s = String.fromCharCode(65 + (i - 1) % 26) + s; return s; };
const sameBay = (b, x, y) => Number(b.x_bay) === x + 1 && b.y_bay === letter(y);

/** City/state lookup against the ASCE hazard services, with a paste fallback. */
export function SnowLookup({draft, loadUpdate, update, notify}) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [problem, setProblem] = useState('');
  const [paste, setPaste] = useState('');
  const [showPaste, setShowPaste] = useState(false);
  const city = draft.location_city || '';
  const state = draft.location_state || '';

  const call = async body => {
    setBusy(true); setProblem(''); setResult(null);
    try {
      const response = await fetch('/api/snow-lookup', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
      });
      const value = await response.json();
      if (!response.ok) throw new Error(value.error || 'The lookup could not be completed.');
      loadUpdate('snow_load_psf', value.ground_snow_load_psf);
      setResult(value);
      notify(`Ground snow load set to ${value.ground_snow_load_psf} psf.`);
    } catch (err) {
      setProblem(err.message || 'The lookup could not be completed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="snow-lookup">
      <div className="snow-fields">
        <label className="field"><span>City</span>
          <input aria-label="City" value={city} placeholder="Denver"
            onChange={e => update('location_city', e.target.value)}/>
        </label>
        <label className="field"><span>State</span>
          <input aria-label="State" value={state} placeholder="CO" maxLength={20}
            onChange={e => update('location_state', e.target.value)}/>
        </label>
      </div>
      <button type="button" className="button full" disabled={busy || (!city && !state)}
        onClick={() => call({city, state, snow_code: draft.load_inputs_psf.snow_code || 'ASCE 7-16'})}>
        {busy ? <LoaderCircle size={16} className="spin"/> : <Search size={16}/>}
        <span>{busy ? 'Looking up…' : 'Look up ground snow load'}</span>
      </button>

      {result && (
        <p className="snow-result">
          <strong>{result.ground_snow_load_psf} psf</strong> · {result.source}
          <small>{result.location}</small>
        </p>
      )}
      {problem && (
        <p className="snow-problem" role="alert"><Info size={15}/><span>{problem}</span></p>
      )}

      <div className="snow-manual">
        <a href="https://ascehazardtool.org/" target="_blank" rel="noreferrer noopener">
          Open the ASCE Hazard Tool <ExternalLink size={13}/>
        </a>
        <button type="button" className="link-button" onClick={() => setShowPaste(v => !v)}>
          {showPaste ? 'Hide paste' : 'Paste its output instead'}
        </button>
      </div>
      {showPaste && (
        <div className="snow-paste">
          <textarea aria-label="Paste ASCE output" rows={3} value={paste}
            placeholder="Paste the ASCE result text containing Ground Snow Load or pg…"
            onChange={e => setPaste(e.target.value)}/>
          <button type="button" className="button subtle full" disabled={busy || !paste.trim()}
            onClick={() => call({paste})}>Read snow load from text</button>
        </div>
      )}
      <p className="hint">
        Values are published ground snow loads (pg) for the located point, not a
        site-specific determination. Confirm against the governing code.
      </p>
    </div>
  );
}

/** Full CRUD plus per-bay painting for additional load layers. */
export function LoadLayers({draft, update}) {
  const layers = draft.additional_load_layers || [];
  const [active, setActive] = useState(0);
  const nx = draft.x_spans_ft.length, ny = draft.y_spans_ft.length;

  const setLayers = next => update('additional_load_layers', next);
  const patch = (i, fields) => setLayers(layers.map((l, j) => j === i ? {...l, ...fields} : l));

  const add = () => {
    // Start empty so bays are chosen deliberately; the old button silently
    // applied a new layer to every bay in the building.
    const palette = ['#b8d56c', '#e2a05a', '#7fb3d5', '#c98bb9', '#e0cc6a'];
    setLayers([...layers, {
      name: `Additional load ${layers.length + 1}`,
      psf: 5,
      color: palette[layers.length % palette.length],
      bays: [],
    }]);
    setActive(layers.length);
  };

  const toggleBay = (x, y) => {
    const layer = layers[active];
    if (!layer) return;
    const bays = layer.bays || [];
    const has = bays.some(b => sameBay(b, x, y));
    patch(active, {
      bays: has ? bays.filter(b => !sameBay(b, x, y))
                : [...bays, {x_bay: x + 1, y_bay: letter(y)}],
    });
  };

  const everyBay = () => Array.from({length: ny}, (_, y) =>
    Array.from({length: nx}, (_, x) => ({x_bay: x + 1, y_bay: letter(y)}))).flat();

  const layer = layers[active];
  return (
    <div className="load-layers">
      {layers.length === 0 && <p className="hint">No additional load layers. Add one to apply extra psf over selected bays.</p>}

      {layers.length > 0 && (
        <div className="layer-tabs" role="tablist">
          {layers.map((l, i) => (
            <button key={i} role="tab" aria-selected={i === active}
              className={i === active ? 'active' : ''} onClick={() => setActive(i)}>
              <i style={{background: l.color || '#b8d56c'}}/>
              <span>{l.name || `Layer ${i + 1}`}</span>
              <small>{(l.bays || []).length}</small>
            </button>
          ))}
        </div>
      )}

      {layer && (
        <div className="layer-editor">
          <div className="layer-row">
            <label className="field grow"><span>Layer name</span>
              <input aria-label="Layer name" value={layer.name || ''}
                onChange={e => patch(active, {name: e.target.value})}/>
            </label>
            <label className="field narrow"><span>Load</span>
              <div className="input-wrap">
                <input aria-label="Layer load" type="number" min={0} step="any" value={layer.psf ?? ''}
                  onChange={e => patch(active, {psf: e.target.value === '' ? '' : Number(e.target.value)})}/>
                <em>psf</em>
              </div>
            </label>
            <label className="field color"><span>Colour</span>
              <input aria-label="Layer colour" type="color" value={layer.color || '#b8d56c'}
                onChange={e => patch(active, {color: e.target.value})}/>
            </label>
          </div>

          <p className="hint">Click bays to add or remove them from this layer.</p>
          <div className="bay-map" style={{gridTemplateColumns: `repeat(${nx},1fr)`}}>
            {Array.from({length: ny}, (_, y) => Array.from({length: nx}, (_, x) => {
              const on = (layer.bays || []).some(b => sameBay(b, x, y));
              return (
                <button key={`${x}-${y}`} className={on ? '' : 'void'} aria-pressed={on}
                  style={on ? {background: layer.color || '#b8d56c', borderColor: layer.color || '#b8d56c'} : undefined}
                  onClick={() => toggleBay(x, y)}>{letter(y)}{x + 1}</button>
              );
            }))}
          </div>

          <div className="layer-actions">
            <button type="button" className="button subtle"
              onClick={() => patch(active, {bays: everyBay()})}>Select all bays</button>
            <button type="button" className="button subtle" disabled={!(layer.bays || []).length}
              onClick={() => patch(active, {bays: []})}>Clear bays</button>
            <button type="button" className="button danger"
              onClick={() => { setLayers(layers.filter((_, j) => j !== active)); setActive(i => Math.max(0, i - 1)); }}>
              <Trash2 size={15}/><span>Delete layer</span>
            </button>
          </div>
        </div>
      )}

      <button type="button" className="button full subtle" onClick={add}>
        <Plus size={16}/><span>Add load layer</span>
      </button>
    </div>
  );
}
