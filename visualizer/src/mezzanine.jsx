import React, {useEffect, useRef, useState} from 'react';
import {Plus, MousePointer2, Move, Maximize, Minus, Trash2, Grid3X3, Ruler, ArrowRight, Download} from 'lucide-react';

const sum = values => values.reduce((s, v) => s + Number(v || 0), 0);
const num = (v, digits=2) => Number(v || 0).toLocaleString('en-US', {maximumFractionDigits:digits});
const clamp = (v, low, high) => Math.max(low, Math.min(high, v));
const positions = (spans, start=0) => spans.reduce((out, v) => [...out, out.at(-1)+Number(v)], [start]);
const letter = i => String.fromCharCode(65+i);

// Draw the draft panels; the engine validates the supplied bay widths.
export function fitPanels(total, values=[]) {
  const source = typeof values==='string' ? values.split(',').map(Number) : values;
  const out=[]; let remaining=total;
  for (const value of source) {
    if (remaining<.001) break;
    if (!(value>0)) continue;
    const span=Math.min(Number(value), remaining); out.push(span); remaining-=span;
  }
  if (remaining>.001) {
    if(remaining<.25&&out.length)out[out.length-1]+=remaining;
    else out.push(remaining);
  }
  return out;
}

export function zoneRectangle(zone, xs, ys) {
  const coord=(axis, end, lines) => zone[`${axis}_${end}_ft`] ?? lines[Number(zone[`${axis}_${end}_line_index`] ?? zone[`${axis}_${end}_line`] ?? (end==='start'?1:2))-1] ?? 0;
  const xa=Number(coord('x','start',xs)), xb=Number(coord('x','end',xs));
  const ya=Number(coord('y','start',ys)), yb=Number(coord('y','end',ys));
  return {x_start_ft:Math.min(xa,xb),x_end_ft:Math.max(xa,xb),y_start_ft:Math.min(ya,yb),y_end_ft:Math.max(ya,yb)};
}

function NumberField({label, value, onChange, min=0, max, step='any'}) {
  return <label className="field"><span>{label}</span><input aria-label={label} type="number" min={min} max={max} step={step} value={value??''} onChange={e=>onChange(e.target.value===''?'':Number(e.target.value))}/></label>;
}

function SpacingField({axis, value, onChange}) {
  const serialized=(value||[]).join(', ');
  const [text,setText]=useState(serialized);
  useEffect(()=>setText(serialized),[serialized]);
  return <label className="field"><span>{axis} bay widths (ft)</span><input aria-label={`Mezzanine ${axis} bay widths (ft)`} value={text} placeholder="e.g. 20, 20, 15" onChange={e=>setText(e.target.value)} onBlur={()=>onChange(text.split(',').map(v=>v.trim()).filter(Boolean).map(Number))} onKeyDown={e=>{if(e.key==='Enter')e.currentTarget.blur();}}/><small>Comma-separated. Any remainder becomes the last bay.</small></label>;
}

export function MezzanineWorkspace({draft,setDraft,data,selectedBay,onInspect,dirty,busy}) {
  const zones=draft.mezzanines||[];
  const [selectedId,setSelectedId]=useState(zones[0]?.id??null),[tool,setTool]=useState('select'),[snap,setSnap]=useState('grid'),[zoom,setZoom]=useState(1),[pan,setPan]=useState({x:0,y:0}),[preview,setPreview]=useState(null),[panel,setPanel]=useState(null),[details,setDetails]=useState(false),[framing,setFraming]=useState(true),[localError,setLocalError]=useState('');
  const svg=useRef(),gesture=useRef();
  const xs=positions(draft.x_spans_ft),ys=positions(draft.y_spans_ft),width=xs.at(-1),length=ys.at(-1);
  const zone=zones.find(z=>z.id===selectedId)||zones[0];
  const rect=zone?zoneRectangle(zone,xs,ys):null;
  const pad=Math.max(width,length)*.085,viewW=width+pad*2,viewH=length+pad*2,font=Math.max(width,length)/35/zoom;
  const result=data.results.mezzanine;
  const calculated=result.mezzanine_zones.find(z=>z.zone_id===zone?.id);
  const members=data.members.filter(m=>m.level==='mezzanine'&&m.demand.zone_id===zone?.id);
  const footings=(data.takeoffs.mezzanine_footings?.column_footings||[]).filter(f=>members.some(m=>m.id===f.column_id));
  const internalX=rect?fitPanels(rect.x_end_ft-rect.x_start_ft,zone.internal_x_spacings_ft):[];
  const internalY=rect?fitPanels(rect.y_end_ft-rect.y_start_ft,zone.internal_y_spacings_ft):[];
  useEffect(()=>{if(zone?.id!==selectedId)setSelectedId(zone?.id??null);setPanel(null);},[zone?.id]);
  const patch=(change,id=zone?.id)=>setDraft(p=>({...p,mezzanines:p.mezzanines.map(z=>z.id===id?{...z,...change}:z)}));
  const patchRectangle=(box,id=zone?.id)=>{
    const source=zones.find(z=>z.id===id),before=zoneRectangle(source,xs,ys),change={...box};
    for(const axis of ['x','y']){
      const previous=before[`${axis}_end_ft`]-before[`${axis}_start_ft`],next=box[`${axis}_end_ft`]-box[`${axis}_start_ft`];
      if(previous>0&&next>0&&Math.abs(previous-next)>.001){const key=`internal_${axis}_spacings_ft`;change[key]=(source[key]||[]).map(v=>Number(v)*next/previous);}
    }
    patch(change,id);
  };
  const add=box=>{
    if(zones.length>=20){setLocalError('A project can contain up to 20 mezzanine areas.');return;}
    const id=`MZ-${crypto.randomUUID().slice(0,8)}`;
    const z={id,name:`Mezzanine ${zones.length+1}`,enabled:true,...box,elevation_ft:Math.min(12,(draft.clear_height_ft||draft.roof_height_ft)/2),dead_load_psf:20,live_load_psf:100,joist_spaces_per_bay:6,joist_direction:'vertical',internal_x_spacings_ft:[],internal_y_spacings_ft:[],joist_spaces_overrides:{}};
    setDraft(p=>({...p,mezzanine_enabled:true,mezzanines:[...p.mezzanines,z]}));setSelectedId(id);setTool('select');setLocalError('');
  };
  const addBay=()=>{
    let x=selectedBay?.x||0,y=selectedBay?.y||0;
    const inactive=(x,y)=>draft.inactive_bays.some(b=>Number(b.x_bay)===x+1&&b.y_bay===letter(y));
    if(x>=xs.length-1||y>=ys.length-1||inactive(x,y)) {
      const first=draft.y_spans_ft.flatMap((_,y)=>draft.x_spans_ft.map((_,x)=>({x,y}))).find(b=>!inactive(b.x,b.y));
      if(!first)return;({x,y}=first);
    }
    add({x_start_ft:xs[x],x_end_ft:xs[x+1],y_start_ft:ys[y],y_end_ft:ys[y+1]});
  };
  const point=e=>{const p=svg.current.createSVGPoint();p.x=e.clientX;p.y=e.clientY;return p.matrixTransform(svg.current.getScreenCTM().inverse());};
  const snapValue=(v,axis)=>{
    const lines=axis==='x'?xs:ys,total=lines.at(-1);
    return clamp(snap==='grid'?lines.reduce((a,b)=>Math.abs(v-b)<Math.abs(v-a)?b:a):Math.round(v*2)/2,0,total);
  };
  const start=(e,kind,z=zone,corner=null)=>{
    if(e.button!==0&&e.button!==2)return;
    e.preventDefault();e.stopPropagation();
    const p=point(e);
    if(e.button===2){gesture.current={kind:'pan',clientX:e.clientX,clientY:e.clientY,scale:svg.current.getScreenCTM().a,pan};svg.current.setPointerCapture(e.pointerId);return;}
    if(tool==='draw')kind='draw';
    if(kind==='draw'){gesture.current={kind,start:{x:snapValue(p.x,'x'),y:snapValue(p.y,'y')}};}
    else if(z){setSelectedId(z.id);setPanel(null);gesture.current={kind,corner,id:z.id,p,rect:zoneRectangle(z,xs,ys)};}
    svg.current.setPointerCapture(e.pointerId);
  };
  const move=e=>{
    const g=gesture.current;if(!g)return;const p=point(e);
    if(g.kind==='pan'){setPan({x:g.pan.x-(e.clientX-g.clientX)/g.scale,y:g.pan.y-(e.clientY-g.clientY)/g.scale});return;}
    let box;
    if(g.kind==='draw'){const x=snapValue(p.x,'x'),y=snapValue(p.y,'y');box={x_start_ft:Math.min(g.start.x,x),x_end_ft:Math.max(g.start.x,x),y_start_ft:Math.min(g.start.y,y),y_end_ft:Math.max(g.start.y,y)};}
    else if(g.kind==='resize'){
      box={...g.rect};box[g.corner.includes('w')?'x_start_ft':'x_end_ft']=snapValue(p.x,'x');box[g.corner.includes('n')?'y_start_ft':'y_end_ft']=snapValue(p.y,'y');
      if(box.x_end_ft-box.x_start_ft<1||box.y_end_ft-box.y_start_ft<1)return;
    }else if(g.kind==='move'){
      const w=g.rect.x_end_ft-g.rect.x_start_ft,h=g.rect.y_end_ft-g.rect.y_start_ft;
      const x=clamp(snapValue(g.rect.x_start_ft+p.x-g.p.x,'x'),0,width-w),y=clamp(snapValue(g.rect.y_start_ft+p.y-g.p.y,'y'),0,length-h);
      box={x_start_ft:x,x_end_ft:x+w,y_start_ft:y,y_end_ft:y+h};
    }
    if(box){g.next=box;setPreview({id:g.id,...box});}
  };
  const end=()=>{
    const g=gesture.current;gesture.current=null;setPreview(null);
    if(!g?.next)return;
    const box=g.next;
    if(box.x_end_ft-box.x_start_ft<1||box.y_end_ft-box.y_start_ft<1){setLocalError('Drag across at least one bay, or switch to half-foot snapping.');return;}
    if(g.kind==='draw')add(box);else patchRectangle(box,g.id);
  };
  const sizeChange=(axis,value)=>{const start=rect[`${axis}_start_ft`];patchRectangle({...rect,[`${axis}_end_ft`]:start+Number(value)});};
  const locationChange=(axis,value)=>{const span=rect[`${axis}_end_ft`]-rect[`${axis}_start_ft`];patch({...rect,[`${axis}_start_ft`]:value,[`${axis}_end_ft`]:Number(value)+span});};
  const equalPanels=(axis,count)=>{if(!Number.isInteger(count)||count<1||count>24)return;const total=rect[`${axis}_end_ft`]-rect[`${axis}_start_ft`];patch({[`internal_${axis}_spacings_ft`]:Array(count).fill(total/count),joist_spaces_overrides:{}});setPanel(null);};
  const exportMembers=()=>{
    const rows=[['Member','Type','Section','Takeoff length (ft)','Weight (lb)','Demand (plf or kips or lb)'],...members.map(m=>[m.id,m.type,m.section.designation,m.weight_length_ft,m.weight_lbs??'',m.demand.required_capacity_plf??m.demand.required_capacity_kips??m.demand.required_capacity_lbs])];
    const blob=new Blob([rows.map(r=>r.map(v=>`"${String(v??'').replaceAll('"','""')}"`).join(',')).join('\r\n')],{type:'text/csv'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`${zone?.name||'mezzanine'}-members.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  return <div className="mezz-workspace">
    <div className="workspace-heading"><div><span className="eyebrow">FLOOR PLANNING</span><h1>Mezzanine designer</h1><p>Place an area on the building plan. Set its floor framing and loads below.</p></div><div className="heading-actions">{zone&&<button className="button" onClick={()=>document.querySelector('.mezz-results')?.scrollIntoView({behavior:'smooth',block:'start'})}>Calculations</button>}<button className="button" onClick={addBay}><Plus size={17}/>Add over a building bay</button><button className={`button primary ${tool==='draw'?'active':''}`} onClick={()=>setTool('draw')}><Plus size={17}/>Draw mezzanine</button></div></div>
    <div className="zone-tabs" aria-label="Mezzanine areas">{zones.map(z=><button key={z.id} className={zone?.id===z.id?'active':''} onClick={()=>{setSelectedId(z.id);setPanel(null);}}>{z.name}{(!draft.mezzanine_enabled||z.enabled===false)&&<small>Excluded</small>}</button>)}{zones.length>0&&<label className="simple-check"><input type="checkbox" checked={!!draft.mezzanine_enabled} onChange={e=>setDraft(p=>({...p,mezzanine_enabled:e.target.checked}))}/>Calculate mezzanines</label>}</div>
    <div className="mezz-canvas-card">
      <div className="mezz-tools" role="toolbar" aria-label="Mezzanine drawing tools">{[['select',MousePointer2,'Select / move'],['draw',Plus,'Draw area'],['panels',Grid3X3,'Edit joist panels']].map(([id,Icon,label])=><button key={id} className={tool===id?'active':''} onClick={()=>setTool(id)}><Icon size={16}/>{label}</button>)}<label>Snap to<select aria-label="Mezzanine snapping" value={snap} onChange={e=>setSnap(e.target.value)}><option value="grid">Building grids</option><option value="half">Half-foot increments</option></select></label><label className="simple-check"><input type="checkbox" checked={framing} onChange={e=>setFraming(e.target.checked)}/>Calculated framing</label><span/>{rect&&<button onClick={()=>{const scale=Math.min(width/(rect.x_end_ft-rect.x_start_ft),length/(rect.y_end_ft-rect.y_start_ft));setZoom(Math.min(8,Math.max(1,scale*.8)));setPan({x:(rect.x_start_ft+rect.x_end_ft-width)/2,y:(rect.y_start_ft+rect.y_end_ft-length)/2});}}><Maximize size={16}/>Focus area</button>}<button aria-label="Zoom mezzanine in" onClick={()=>setZoom(v=>Math.min(8,v*1.4))}><Plus size={17}/></button><button aria-label="Zoom mezzanine out" onClick={()=>setZoom(v=>Math.max(.5,v/1.4))}><Minus size={17}/></button><button aria-label="Fit mezzanine plan" onClick={()=>{setZoom(1);setPan({x:0,y:0});}}><Maximize size={17}/></button></div>
      <p className="drawing-help">{tool==='draw'?'Drag between two points to draw a rectangular mezzanine.':tool==='panels'?'Click a framing panel to edit its joist count.':'Drag an area to move it. Drag a corner handle to resize. Right-drag to pan.'} <span>Blue squares: building columns · Brown lines: bearing walls</span></p>
      {localError&&<p className="inline-error" role="alert">{localError}</p>}
      <svg ref={svg} className={`mezz-plan tool-${tool}`} role="img" aria-label="Mezzanine layout designer" viewBox={`${width/2-viewW/zoom/2+pan.x} ${length/2-viewH/zoom/2+pan.y} ${viewW/zoom} ${viewH/zoom}`} onPointerDown={e=>start(e,tool==='draw'?'draw':'background',null)} onPointerMove={move} onPointerUp={end} onPointerCancel={()=>{gesture.current=null;setPreview(null);}} onContextMenu={e=>e.preventDefault()}>
        <rect x="0" y="0" width={width} height={length} fill="#f7fafc" stroke="#9db1c1" strokeWidth=".35"/>
        {draft.y_spans_ft.flatMap((h,y)=>draft.x_spans_ft.map((w,x)=><g key={`${x}:${y}`} pointerEvents="none"><rect x={xs[x]} y={ys[y]} width={w} height={h} fill={draft.inactive_bays.some(b=>Number(b.x_bay)===x+1&&b.y_bay===letter(y))?'#d7dde3':'transparent'} stroke="#d6e0e7" strokeWidth=".2"/><text x={(xs[x]+xs[x+1])/2} y={(ys[y]+ys[y+1])/2} textAnchor="middle" fill="#bbc7d0" fontSize={font}>{letter(y)}{x+1}</text></g>))}
        {xs.map((x,i)=><g key={`x${i}`} pointerEvents="none"><line x1={x} x2={x} y1={-pad*.4} y2={length} stroke="#ccd8e0" strokeWidth=".25"/><text x={x} y={-pad*.55} textAnchor="middle" fontSize={font} fill="#658297">{i+1}</text></g>)}
        {ys.map((y,i)=><g key={`y${i}`} pointerEvents="none"><line x1={-pad*.4} x2={width} y1={y} y2={y} stroke="#ccd8e0" strokeWidth=".25"/><text x={-pad*.6} y={y+font*.3} textAnchor="middle" fontSize={font} fill="#658297">{letter(i)}</text></g>)}
        {(data.walls||[]).map((wall,i)=><line key={i} x1={wall.start[0]} y1={wall.start[1]} x2={wall.end[0]} y2={wall.end[1]} stroke="#a57b4e" strokeWidth={font*.24} pointerEvents="none"/>)}
        {zones.map(z=>{const r=preview?.id===z.id?preview:zoneRectangle(z,xs,ys),w=r.x_end_ft-r.x_start_ft,h=r.y_end_ft-r.y_start_ft,active=z.id===zone?.id;
          const px=positions(fitPanels(w,z.internal_x_spacings_ft),r.x_start_ft),py=positions(fitPanels(h,z.internal_y_spacings_ft),r.y_start_ft);
          return <g key={z.id} className="mezz-area" role="button" tabIndex={0} aria-label={`Select mezzanine ${z.name}`} onPointerDown={e=>start(e,'move',z)} onKeyDown={e=>{if(e.key==='Enter')setSelectedId(z.id);}} opacity={z.enabled===false||!draft.mezzanine_enabled?0.4:1}>
            <rect x={r.x_start_ft} y={r.y_start_ft} width={Math.max(0,w)} height={Math.max(0,h)} fill={active?'#7baecb3b':'#a8bdce30'} stroke={active?'#247d9d':'#8ba8bd'} strokeWidth={font*.2}/>
            {px.slice(0,-1).flatMap((x,ix)=>py.slice(0,-1).map((y,iy)=><g key={`${ix}:${iy}`} onPointerDown={e=>{if(tool==='panels'){e.stopPropagation();setSelectedId(z.id);setPanel({x:ix,y:iy});}}} role={tool==='panels'?'button':undefined} aria-label={`Mezzanine panel ${ix+1},${iy+1}`}><rect x={x} y={y} width={px[ix+1]-x} height={py[iy+1]-y} fill={active&&panel?.x===ix&&panel?.y===iy?'#d8eeb880':'transparent'} stroke="#5895ab" strokeWidth={font*.06}/><text x={(x+px[ix+1])/2} y={(y+py[iy+1])/2} fontSize={Math.min(font*.7,(px[ix+1]-x)/6)} fill="#427e97" textAnchor="middle" pointerEvents="none">P{ix+1}.{iy+1}</text></g>))}
            <text x={r.x_start_ft+font*.5} y={r.y_start_ft+font*1.1} fill="#235f7b" fontSize={Math.min(font,w/9)} fontWeight="600" pointerEvents="none">{z.name}</text>
            <text x={(r.x_start_ft+r.x_end_ft)/2} y={r.y_end_ft+font*1.15} textAnchor="middle" fill="#23718e" fontSize={font*.8} pointerEvents="none">{num(w)} × {num(h)} ft · {num(w*h)} sf</text>
          </g>;
        })}
        {framing&&!dirty&&!preview&&members.filter(m=>m.type!=='column').map(m=><line key={m.id} x1={m.start[0]} y1={m.start[1]} x2={m.end[0]} y2={m.end[1]} stroke={m.type==='girder'?'#476fa5':'#328f97'} strokeWidth={m.type==='girder'?font*.13:font*.045} pointerEvents="none"/>)}
        {data.members.filter(m=>m.type==='column'&&(m.level==='roof'||framing&&m.demand.zone_id===zone?.id)).map(m=><rect key={m.id} x={m.start[0]-font*.18} y={m.start[1]-font*.18} width={font*.36} height={font*.36} fill={m.level==='roof'?'#466b94':'#b08a57'} pointerEvents="none"/>)}
        {rect&&tool==='select'&&['nw','ne','sw','se'].map(c=>{const r=preview?.id===zone.id?preview:rect,x=c.includes('w')?r.x_start_ft:r.x_end_ft,y=c.includes('n')?r.y_start_ft:r.y_end_ft;return <rect key={c} role="button" aria-label={`Resize mezzanine ${c}`} x={x-font*.3} y={y-font*.3} width={font*.6} height={font*.6} fill="#fff" stroke="#267c9d" strokeWidth={font*.1} className={`resize-${c}`} onPointerDown={e=>start(e,'resize',zone,c)}/>;})}
        {preview&&!preview.id&&<rect x={preview.x_start_ft} y={preview.y_start_ft} width={preview.x_end_ft-preview.x_start_ft} height={preview.y_end_ft-preview.y_start_ft} fill="#70a8c544" stroke="#2d829d" strokeDasharray="1 1" pointerEvents="none"/>}
      </svg>
      {!zones.length&&tool!=='draw'&&<div className="mezz-empty"><Grid3X3 size={30}/><strong>Start with a bay or draw your own area</strong><p>Your building grid stays visible. The engine calculates framing and supports when you place a mezzanine.</p><button className="button primary" onClick={addBay}><Plus size={16}/>Add first mezzanine</button></div>}
    </div>
    {zone&&<>
      <section className="mezz-properties">
        <div className="properties-heading"><div><h2>Area dimensions & framing</h2><span>Changes update the plan and calculations automatically.</span></div><label className="simple-check"><input type="checkbox" checked={zone.enabled!==false} onChange={e=>patch({enabled:e.target.checked})}/>Include this area</label><button className="button danger" onClick={()=>{setDraft(p=>({...p,mezzanines:p.mezzanines.filter(z=>z.id!==zone.id)}));setPanel(null);}}><Trash2 size={16}/>Remove area</button></div>
        <div className="wide-fields geometry-fields"><label className="field"><span>Area name</span><input aria-label="Mezzanine name" value={zone.name} onChange={e=>patch({name:e.target.value})}/></label><NumberField label="Mezzanine X position (ft)" value={rect.x_start_ft} onChange={v=>locationChange('x',v)}/><NumberField label="Mezzanine Y position (ft)" value={rect.y_start_ft} onChange={v=>locationChange('y',v)}/><NumberField label="Mezzanine width (ft)" min={1} value={rect.x_end_ft-rect.x_start_ft} onChange={v=>sizeChange('x',v)}/><NumberField label="Mezzanine length (ft)" min={1} value={rect.y_end_ft-rect.y_start_ft} onChange={v=>sizeChange('y',v)}/><NumberField label="Mezzanine elevation (ft)" min={1} value={zone.elevation_ft} onChange={v=>patch({elevation_ft:v})}/></div>
        <div className="wide-fields framing-fields"><NumberField label="Mezzanine dead load (psf)" value={zone.dead_load_psf} onChange={v=>patch({dead_load_psf:v})}/><NumberField label="Mezzanine live load (psf)" value={zone.live_load_psf} onChange={v=>patch({live_load_psf:v})}/><label className="field"><span>Joist span direction</span><select aria-label="Mezzanine joist direction" value={zone.joist_direction||'vertical'} onChange={e=>patch({joist_direction:e.target.value})}><option value="vertical">North–south (Y)</option><option value="horizontal">East–west (X)</option></select></label><NumberField label="Mezzanine joist spaces" min={1} max={40} step={1} value={zone.joist_spaces_per_bay} onChange={v=>patch({joist_spaces_per_bay:v})}/><NumberField label="Mezzanine X bays" min={1} max={24} step={1} value={internalX.length} onChange={v=>equalPanels('x',v)}/><NumberField label="Mezzanine Y bays" min={1} max={24} step={1} value={internalY.length} onChange={v=>equalPanels('y',v)}/></div>
        <details className="internal-bays"><summary>Custom framing bay widths & panel overrides</summary><div className="wide-fields"><SpacingField key={`${zone.id}x`} axis="X" value={zone.internal_x_spacings_ft} onChange={v=>patch({internal_x_spacings_ft:v})}/><SpacingField key={`${zone.id}y`} axis="Y" value={zone.internal_y_spacings_ft} onChange={v=>patch({internal_y_spacings_ft:v})}/><button className="button" onClick={()=>patch({joist_spaces_overrides:{}})}>Use default joist spaces in every panel</button></div></details>
        {panel&&<div className="panel-edit-bar"><strong>Panel {panel.x+1}.{panel.y+1}</strong><NumberField label="Selected panel joist spaces" min={1} max={40} value={zone.joist_spaces_overrides?.[`${panel.x+1},${panel.y+1}`]??zone.joist_spaces_per_bay} onChange={v=>patch({joist_spaces_overrides:{...zone.joist_spaces_overrides,[`${panel.x+1},${panel.y+1}`]:v}})}/><p>{num(internalX[panel.x])} × {num(internalY[panel.y])} ft</p><button className="button" onClick={()=>setPanel(null)}>Done</button></div>}
      </section>
      <section className={`mezz-results ${dirty?'stale':''}`}><div className="properties-heading"><div><h2>Mezzanine calculations</h2><span>{dirty?(busy?'Recalculating your changes…':'Results from the last successful calculation.'):zone.enabled===false||!draft.mezzanine_enabled?'This area is excluded from calculations.':`${num(calculated?.main_support_connections,0)} building-column connections · ${num(calculated?.lb_wall_support_connections,0)} bearing-wall connections`}</span></div><button className="button" disabled={!members.length} onClick={exportMembers}><Download size={16}/>Export mezzanine CSV</button><button className="button" onClick={()=>setDetails(v=>!v)}>{details?'Hide':'Show'} calculation details</button></div>
        <div className="mezz-metrics"><div><small>Floor area</small><strong>{num(calculated?.area_sf)} <em>sf</em></strong><span>{calculated?.panel_count||0} framing panels</span></div>{['joist','girder','column'].map(type=>{const items=members.filter(m=>m.type===type);return <div key={type}><small>{type==='column'?'Additional columns':`${type[0].toUpperCase()+type.slice(1)}s`}</small><strong>{items.length} <em>members</em></strong><span>{num(sum(items.map(m=>m.weight_lbs))/2000)} tons</span></div>;})}<div><small>Additional pad footings</small><strong>{footings.length} <em>pads</em></strong><span>{num(sum(footings.map(f=>f.footing_volume_cy))*1.1)} CY with waste</span></div><div><small>Supported floor load</small><strong>{num(calculated?.estimated_supported_load_kips)} <em>kips</em></strong><span>Dead + live load</span></div></div>
        {members.some(m=>!m.section.assigned)&&<p className="report-note">{members.filter(m=>!m.section.assigned).length} members have no catalog match. Open a member to review its demand and select steel.</p>}
        <p className="support-help">The original engine requires at least two connections to building columns or bearing walls. Snap the perimeter onto those supports. Reused building columns are excluded from additional columns and pads.</p>
        {details&&<div className="table-scroll mezz-member-table"><table><thead><tr>{['Member','Type','Section','Span / height (ft)','Required load','Takeoff weight (lb)',''].map((h,i)=><th key={i}>{h}</th>)}</tr></thead><tbody>{members.map(m=><tr key={m.id} onClick={()=>onInspect(m.id)}><td>{m.id}</td><td>{m.type}</td><td>{m.section.designation||'Unassigned'}</td><td>{num(m.weight_length_ft)}</td><td>{m.demand.required_capacity_plf!==undefined?`${num(m.demand.required_capacity_plf)} plf`:m.demand.required_capacity_kips!==undefined?`${num(m.demand.required_capacity_kips)} kips`:`${num(m.demand.required_capacity_lbs)} lb`}</td><td>{m.weight_lbs===null?'Unassigned':num(m.weight_lbs)}</td><td><ArrowRight size={14}/></td></tr>)}</tbody></table></div>}
      </section>
    </>}
  </div>;
}
