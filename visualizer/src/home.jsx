/* The estimator home page: projects, their buildings, and the guided
 * setup for creating a new one.
 *
 * Before this, the application opened straight into a fixed example grid
 * with no notion of a job. A project is a job; a building belongs to a
 * project and carries its trades. Steel is designed today; the other
 * trades are shown as not started so the real state of a job is visible.
 */
import React, {useEffect, useMemo, useRef, useState} from 'react';
import {Building2, Plus, Trash2, Copy, ChevronRight, FolderOpen, LoaderCircle, Check, Circle, Clock} from 'lucide-react';

const TRADES = [
  ['steel', 'Structural steel'],
  ['concrete', 'Concrete'],
  ['hvac', 'HVAC'],
  ['electrical', 'Electrical'],
  ['plumbing', 'Plumbing'],
];

const num = (n, d = 0) => Number(n || 0).toLocaleString('en-US', {maximumFractionDigits: d});

async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
  });
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || 'That action could not be completed.');
  return value;
}

function TradeChip({status, label}) {
  const Icon = status === 'complete' ? Check : status === 'in_progress' ? Clock : Circle;
  return (
    <span className={`trade-chip ${status}`}>
      <Icon size={12}/><span>{label}</span>
    </span>
  );
}

/* Guided setup. Building size and bay spacing in plain terms, with the
 * grid drawn live as you type, rather than a blank canvas to fill in. */
function NewBuilding({onCancel, onCreate, busy}) {
  const [name, setName] = useState('');
  const [width, setWidth] = useState(240);   // east-west, ft
  const [length, setLength] = useState(160); // north-south, ft
  const [bayX, setBayX] = useState(40);
  const [bayY, setBayY] = useState(40);
  const [height, setHeight] = useState(30);
  const nameRef = useRef();
  useEffect(() => { nameRef.current?.focus(); }, []);

  // Fit whole bays across the building, then distribute the remainder so
  // the total always equals the size the user actually asked for.
  const grid = useMemo(() => {
    const spans = (total, bay) => {
      const t = Math.max(1, Number(total) || 0), b = Math.max(1, Number(bay) || 1);
      const n = Math.max(1, Math.round(t / b));
      const each = Math.round((t / n) * 100) / 100;
      const out = Array(n).fill(each);
      // Push any rounding drift into the last bay.
      out[n - 1] = Math.round((t - each * (n - 1)) * 100) / 100;
      return out;
    };
    return {x: spans(width, bayX), y: spans(length, bayY)};
  }, [width, length, bayX, bayY]);

  const area = grid.x.reduce((a, b) => a + b, 0) * grid.y.reduce((a, b) => a + b, 0);
  const valid = name.trim() && grid.x.length <= 24 && grid.y.length <= 24 && area > 0;
  const tooMany = grid.x.length > 24 || grid.y.length > 24;

  const submit = e => {
    e.preventDefault();
    if (!valid || busy) return;
    onCreate({
      name: name.trim(),
      x_spans_ft: grid.x,
      y_spans_ft: grid.y,
      clear_height_ft: Number(height) || 30,
      roof_height_ft: Number(height) || 30,
    });
  };

  // Scale the preview to fit its box while keeping the plan's proportions.
  const W = grid.x.reduce((a, b) => a + b, 0), L = grid.y.reduce((a, b) => a + b, 0);
  const scale = Math.min(300 / (W || 1), 190 / (L || 1));

  return (
    <form className="new-building" onSubmit={submit}>
      <h2>New building</h2>
      <p className="hint">Enter the overall size and the bay spacing you want. The grid updates as you type.</p>

      <label className="field"><span>Building name</span>
        <input ref={nameRef} aria-label="Building name" value={name} placeholder="Warehouse A"
          onChange={e => setName(e.target.value)}/>
      </label>

      <div className="setup-grid">
        <label className="field"><span>Width (east–west)</span>
          <div className="input-wrap">
            <input aria-label="Building width" type="number" min={1} max={2000} value={width}
              onChange={e => setWidth(e.target.value)}/><em>ft</em>
          </div>
        </label>
        <label className="field"><span>Length (north–south)</span>
          <div className="input-wrap">
            <input aria-label="Building length" type="number" min={1} max={2000} value={length}
              onChange={e => setLength(e.target.value)}/><em>ft</em>
          </div>
        </label>
        <label className="field"><span>Bay spacing across</span>
          <div className="input-wrap">
            <input aria-label="Bay spacing across" type="number" min={1} max={200} value={bayX}
              onChange={e => setBayX(e.target.value)}/><em>ft</em>
          </div>
        </label>
        <label className="field"><span>Bay spacing along</span>
          <div className="input-wrap">
            <input aria-label="Bay spacing along" type="number" min={1} max={200} value={bayY}
              onChange={e => setBayY(e.target.value)}/><em>ft</em>
          </div>
        </label>
        <label className="field"><span>Clear height</span>
          <div className="input-wrap">
            <input aria-label="Clear height" type="number" min={8} max={200} value={height}
              onChange={e => setHeight(e.target.value)}/><em>ft</em>
          </div>
        </label>
      </div>

      <div className="setup-preview">
        <svg viewBox={`-14 -14 ${W * scale + 28} ${L * scale + 28}`} role="img"
             aria-label={`Preview: ${grid.x.length} by ${grid.y.length} bays`}>
          <rect x={0} y={0} width={W * scale} height={L * scale} className="preview-slab"/>
          {grid.x.reduce((acc, s) => [...acc, acc[acc.length - 1] + s], [0]).map((x, i) => (
            <line key={`x${i}`} x1={x * scale} y1={0} x2={x * scale} y2={L * scale} className="preview-line"/>
          ))}
          {grid.y.reduce((acc, s) => [...acc, acc[acc.length - 1] + s], [0]).map((y, i) => (
            <line key={`y${i}`} x1={0} y1={y * scale} x2={W * scale} y2={y * scale} className="preview-line"/>
          ))}
        </svg>
        <p className="preview-caption">
          <strong>{grid.x.length} × {grid.y.length} bays</strong>
          <span>{num(grid.x[0], 2)} ft × {num(grid.y[0], 2)} ft typical · {num(area)} sf</span>
        </p>
      </div>

      {tooMany && <p className="snow-problem" role="alert">
        <span>That is more than 24 bays on one axis. Increase the bay spacing or reduce the building size.</span>
      </p>}

      <div className="setup-actions">
        <button type="button" className="button subtle" onClick={onCancel}>Cancel</button>
        <button type="submit" className="button" disabled={!valid || busy}>
          {busy ? <LoaderCircle size={16} className="spin"/> : <Plus size={16}/>}
          <span>Create building</span>
        </button>
      </div>
    </form>
  );
}

export function Home({onOpenBuilding, notify}) {
  const [projects, setProjects] = useState(null);
  const [openId, setOpenId] = useState(null);
  const [creating, setCreating] = useState(null); // project id awaiting a new building
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');
  const [newProject, setNewProject] = useState('');

  const refresh = async () => {
    try { setProjects((await api('/api/workspace')).projects); }
    catch (err) { setProblem(err.message); setProjects([]); }
  };
  useEffect(() => { refresh(); }, []);

  const guard = async (fn, message) => {
    setBusy(true); setProblem('');
    try { await fn(); await refresh(); if (message) notify(message); }
    catch (err) { setProblem(err.message); }
    finally { setBusy(false); }
  };

  const addProject = e => {
    e.preventDefault();
    const name = newProject.trim();
    if (!name) return;
    guard(async () => {
      const project = await api('/api/workspace', {action: 'create', name});
      setNewProject('');
      setOpenId(project.id);
    }, 'Project created.');
  };

  const addBuilding = (projectId, setup) => guard(async () => {
    const {name, ...geometry} = setup;
    const building = await api(`/api/workspace/${projectId}/buildings`, {name});
    setCreating(null);
    onOpenBuilding({projectId, buildingId: building.id, name, geometry});
  });

  if (projects === null) {
    return <main className="home loading"><LoaderCircle className="spin"/><p>Opening your workspace…</p></main>;
  }

  return (
    <main className="home">
      <header className="home-head">
        <div className="brand-mark"><Building2/></div>
        <div>
          <h1>Building Estimator</h1>
          <p>Design and take off each trade, building by building.</p>
        </div>
      </header>

      {problem && <p className="snow-problem" role="alert"><span>{problem}</span></p>}

      <form className="new-project" onSubmit={addProject}>
        <input aria-label="New project name" value={newProject} placeholder="New project name…"
          onChange={e => setNewProject(e.target.value)}/>
        <button type="submit" className="button" disabled={busy || !newProject.trim()}>
          <Plus size={16}/><span>Add project</span>
        </button>
      </form>

      {projects.length === 0 && (
        <div className="home-empty">
          <FolderOpen size={30}/>
          <h2>No projects yet</h2>
          <p>Create a project above, then add the buildings it contains.</p>
        </div>
      )}

      <div className="project-list">
        {projects.map(project => {
          const open = openId === project.id;
          return (
            <section key={project.id} className={`project-card ${open ? 'open' : ''}`}>
              <button className="project-head" aria-expanded={open}
                onClick={() => { setOpenId(open ? null : project.id); setCreating(null); }}>
                <ChevronRight size={18} className="chev"/>
                <div className="project-title">
                  <h2>{project.name}</h2>
                  <span>{project.number ? `${project.number} · ` : ''}{project.building_count} building{project.building_count === 1 ? '' : 's'}</span>
                </div>
              </button>

              {open && (
                <div className="project-body">
                  {project.buildings.length === 0 && !creating && (
                    <p className="hint">No buildings yet. Add the first one below.</p>
                  )}

                  <div className="building-grid">
                    {project.buildings.map(b => (
                      <article key={b.id} className="building-card">
                        <button className="building-open"
                          onClick={() => onOpenBuilding({projectId: project.id, buildingId: b.id, name: b.name})}>
                          <h3>{b.name}</h3>
                          {b.summary?.member_count ? (
                            <p className="building-stats">
                              {num(b.summary.member_count)} members · {num(b.summary.weight_tons, 2)} tons
                              {b.summary.concrete_total_cy ? ` · ${num(b.summary.concrete_total_cy)} CY concrete` : ''}
                            </p>
                          ) : <p className="building-stats muted">Not yet calculated</p>}
                          <div className="trade-row">
                            {TRADES.map(([key, label]) => (
                              <TradeChip key={key} status={b.trades?.[key] || 'not_started'} label={label}/>
                            ))}
                          </div>
                        </button>
                        <div className="building-actions">
                          <button title="Duplicate building" aria-label={`Duplicate ${b.name}`} disabled={busy}
                            onClick={() => guard(() => api(`/api/workspace/${project.id}/buildings/${b.id}`, {action: 'duplicate'}), 'Building duplicated.')}>
                            <Copy size={15}/>
                          </button>
                          <button title="Delete building" aria-label={`Delete ${b.name}`} disabled={busy}
                            onClick={() => { if (confirm(`Delete "${b.name}"? This cannot be undone.`)) guard(() => api(`/api/workspace/${project.id}/buildings/${b.id}`, {action: 'delete'}), 'Building deleted.'); }}>
                            <Trash2 size={15}/>
                          </button>
                        </div>
                      </article>
                    ))}
                  </div>

                  {creating === project.id ? (
                    <NewBuilding busy={busy} onCancel={() => setCreating(null)}
                      onCreate={setup => addBuilding(project.id, setup)}/>
                  ) : (
                    <div className="project-actions">
                      <button className="button" onClick={() => setCreating(project.id)} disabled={busy}>
                        <Plus size={16}/><span>Add building</span>
                      </button>
                      <button className="button subtle danger" disabled={busy}
                        onClick={() => { if (confirm(`Delete project "${project.name}" and all its buildings?`)) guard(() => api(`/api/workspace/${project.id}`, {action: 'delete'}), 'Project deleted.'); }}>
                        <Trash2 size={15}/><span>Delete project</span>
                      </button>
                    </div>
                  )}
                </div>
              )}
            </section>
          );
        })}
      </div>
    </main>
  );
}
