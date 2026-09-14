import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { CSS2DRenderer, CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';

const COLORS = { joist: '#52bcb5', girder: '#6385bd', column: '#ca946b' };
// Plan coordinates are X east, Y south, Z elevation. Three.js uses Y up.
// Positive world Z must stay south so the north-up view matches the layout.
export const modelToWorld = p => new THREE.Vector3(p[0], p[2], p[1]);
const vec = modelToWorld;
const ft = n => `${Number(n.toFixed(2))}′`;
function segment(a, b, width, depth = width) {
  const direction = b.clone().sub(a);
  const geometry = new THREE.BoxGeometry(width, direction.length(), depth);
  const longitudinal = direction.normalize();
  const across = new THREE.Vector3().crossVectors(longitudinal, new THREE.Vector3(0,1,0));
  if(across.lengthSq()<1e-8)across.set(1,0,0);else across.normalize();
  const vertical = new THREE.Vector3().crossVectors(across,longitudinal).normalize();
  geometry.applyMatrix4(new THREE.Matrix4().makeBasis(across,longitudinal,vertical));
  geometry.translate(...a.clone().add(b).multiplyScalar(.5).toArray());
  return geometry;
}
function memberGeometry(member) {
  const a = vec(member.start), b = vec(member.end);
  const depth = (member.section?.depth_in || (member.type === 'joist' ? 28 : member.type === 'girder' ? 44 : 12)) / 12;
  const width = (member.section?.width_in || (member.type === 'column' ? 12 : 7)) / 12;
  const pieces = [];
  if (member.type === 'column' && member.section?.profile === 'wide_flange') {
    const t=Math.min(depth/12,.09);
    for(const offset of [-depth/2+t/2,depth/2-t/2])pieces.push(segment(a.clone().add(new THREE.Vector3(0,0,offset)),b.clone().add(new THREE.Vector3(0,0,offset)),width,t));
    pieces.push(segment(a,b,t,depth-2*t));
  } else if (member.type === 'column' && member.section?.profile === 'hss_round') {
    const shape=new THREE.Shape(),hole=new THREE.Path(),r=depth/2;
    shape.absarc(0,0,r,0,Math.PI*2,false);hole.absarc(0,0,Math.max(r-.06,r*.8),0,Math.PI*2,true);shape.holes.push(hole);
    const tube=new THREE.ExtrudeGeometry(shape,{depth:a.distanceTo(b),bevelEnabled:false,curveSegments:16});
    tube.rotateX(-Math.PI/2);tube.translate(a.x,a.y,a.z);return tube;
  } else if (member.type === 'column') {
    // Four walls keep HSS visibly hollow at its ends. Dimensions are schematic unless catalog-supplied.
    const t = Math.min(width / 7, .07);
    for (const [dx, dz, w, d] of [[width/2-t/2,0,t,depth],[-width/2+t/2,0,t,depth],[0,depth/2-t/2,width-2*t,t],[0,-depth/2+t/2,width-2*t,t]]) {
      pieces.push(segment(a.clone().add(new THREE.Vector3(dx,0,dz)), b.clone().add(new THREE.Vector3(dx,0,dz)), w, d));
    }
  } else if (member.section?.profile === 'wide_flange') {
    const downward = new THREE.Vector3(0, -depth, 0);
    pieces.push(segment(a,b,width,.09));
    pieces.push(segment(a.clone().add(downward),b.clone().add(downward),width,.09));
    pieces.push(segment(a.clone().addScaledVector(downward,.5),b.clone().addScaledVector(downward,.5),.07,depth));
  } else {
    const down = new THREE.Vector3(0, -depth, 0);
    const bottomA = a.clone().add(down), bottomB = b.clone().add(down);
    pieces.push(segment(a,b,width,.10),segment(bottomA,bottomB,width*.7,.10));
    const n = Math.min(28, Math.max(6, Math.round(a.distanceTo(b)/3)));
    let prev = a;
    for (let i=1;i<=n;i++) {
      const next = a.clone().lerp(b,i/n).addScaledVector(down,i%2 ? 1 : 0);
      pieces.push(segment(prev,next,.07,.07)); prev=next;
    }
    pieces.push(segment(a,bottomA,.09,.09),segment(b,bottomB,.09,.09));
  }
  const merged=mergeGeometries(pieces); pieces.forEach(g=>g.dispose()); return merged;
}

export class SteelScene {
  static reportImage(data){
    const host=document.createElement('div');
    host.style.cssText='position:fixed;left:-12000px;top:0;width:2200px;height:1200px;pointer-events:none';
    document.body.appendChild(host);let studio;
    try{
      const noop=()=>{};
      studio=new SteelScene(host,{select:noop,hover:noop,dimension:noop,measure:noop});
      cancelAnimationFrame(studio.frame);
      studio.renderer.setPixelRatio(1);studio.renderer.setSize(2200,1200);
      studio.camera.aspect=2200/1200;studio.camera.updateProjectionMatrix();
      studio.setModel(data);studio.setSettings({dimensions:false,grid:false,walls:false,cut:100});
      studio.floor.visible=false;studio.annotation.visible=false;
      studio.scene.background=new THREE.Color('#ffffff');
      // Softer lighting and darker inks retain thin framing when printed on white.
      studio.scene.traverse(object=>{if(object.isLight)object.intensity*=.38;});
      const printColors={joist:'#367f89',girder:'#597caa',column:'#b68853'};
      for(const mesh of studio.meshes){mesh.material.color.set(printColors[mesh.userData.member.type]);mesh.material.metalness=.12;mesh.material.roughness=.7;}
      studio.view('3d',false);studio.controls.update();
      studio.renderer.render(studio.scene,studio.camera);
      // Frame the actual steel, including mezzanines, without empty floor margins.
      let left=2200,right=0,top=1200,bottom=0;
      for(const mesh of studio.meshes){
        mesh.geometry.computeBoundingBox();const box=mesh.geometry.boundingBox;
        for(const x of [box.min.x,box.max.x])for(const y of [box.min.y,box.max.y])for(const z of [box.min.z,box.max.z]){
          const p=new THREE.Vector3(x,y,z).applyMatrix4(mesh.matrixWorld).project(studio.camera),px=(p.x+1)*1100,py=(1-p.y)*600;
          left=Math.min(left,px);right=Math.max(right,px);top=Math.min(top,py);bottom=Math.max(bottom,py);
        }
      }
      const output=document.createElement('canvas');output.width=2200;output.height=1200;
      const ctx=output.getContext('2d');ctx.fillStyle='#ffffff';ctx.fillRect(0,0,2200,1200);
      left=Math.max(0,left-24);top=Math.max(0,top-24);right=Math.min(2200,right+24);bottom=Math.min(1200,bottom+24);
      const sw=right-left,sh=bottom-top,scale=Math.min(2040/sw,1040/sh),dw=sw*scale,dh=sh*scale;
      ctx.drawImage(studio.renderer.domElement,left,top,sw,sh,(2200-dw)/2,(1200-dh)/2,dw,dh);
      // North is drawn from the camera's projection, so it stays true to the model.
      const center=studio.controls.target.clone(),a=center.clone().project(studio.camera),b=center.clone().add(new THREE.Vector3(0,0,-20)).project(studio.camera);
      const angle=Math.atan2(-(b.y-a.y)*1200,(b.x-a.x)*2200),ox=2090,oy=102;
      ctx.save();ctx.translate(ox,oy);ctx.rotate(angle);ctx.strokeStyle='#526f81';ctx.fillStyle='#526f81';ctx.lineWidth=3;
      ctx.beginPath();ctx.moveTo(-26,0);ctx.lineTo(26,0);ctx.stroke();ctx.beginPath();ctx.moveTo(32,0);ctx.lineTo(16,-7);ctx.lineTo(16,7);ctx.closePath();ctx.fill();ctx.restore();
      ctx.font='600 24px Segoe UI, sans-serif';ctx.textAlign='center';ctx.fillStyle='#526f81';ctx.fillText('N',ox,oy+57);
      return output.toDataURL('image/png');
    }finally{studio?.dispose();host.remove();}
  }
  constructor(container, callbacks) {
    this.container=container; this.callbacks=callbacks; this.meshes=[]; this.selected=null; this.settings={dimensions:true,grid:true,walls:true,joist:true,girder:true,column:true,roof:true,mezzanine:true,color:'type',cut:100};
    this.scene=new THREE.Scene(); this.scene.background=new THREE.Color('#e5eaf0');
    this.camera=new THREE.PerspectiveCamera(38,1,.05,20000);
    this.renderer=new THREE.WebGLRenderer({antialias:true,preserveDrawingBuffer:true});
    this.renderer.setPixelRatio(Math.min(devicePixelRatio,2)); this.renderer.localClippingEnabled=true;
    this.renderer.outputColorSpace=THREE.SRGBColorSpace; this.renderer.setClearColor('#e5eaf0');
    this.renderer.domElement.setAttribute('aria-label','Interactive 3D steel model. Drag to orbit, scroll to zoom, click to select a member.');
    this.renderer.domElement.tabIndex=0; container.appendChild(this.renderer.domElement);
    this.labels=new CSS2DRenderer(); this.labels.domElement.className='scene-labels'; container.appendChild(this.labels.domElement);
    this.controls=new OrbitControls(this.camera,this.renderer.domElement); this.controls.enableDamping=true; this.controls.dampingFactor=.1; this.controls.maxPolarAngle=Math.PI*.495; this.controls.minDistance=.5; this.controls.maxDistance=10000;
    this.scene.add(new THREE.HemisphereLight(0xffffff,0x60738c,2.5));
    const sun=new THREE.DirectionalLight(0xffffff,3.2); sun.position.set(80,160,60); this.scene.add(sun);
    const fill=new THREE.DirectionalLight(0x9fcae2,2); fill.position.set(-100,40,-40); this.scene.add(fill);
    this.group=new THREE.Group(); this.annotation=new THREE.Group(); this.dimensionGroup=new THREE.Group(); this.supportGroup=new THREE.Group();
    this.scene.add(this.group,this.annotation,this.dimensionGroup,this.supportGroup);
    this.ray=new THREE.Raycaster(); this.mouse=new THREE.Vector2();
    this.clip=new THREE.Plane(new THREE.Vector3(-1,0,0),1e8);
    this.resizeObserver=new ResizeObserver(()=>this.resize()); this.resizeObserver.observe(container);
    this.down=e=>{this.pointerStart=[e.clientX,e.clientY];};
    this.up=e=>{if(!this.pointerStart||Math.hypot(e.clientX-this.pointerStart[0],e.clientY-this.pointerStart[1])>5||e.button!==0)return;const hit=this.pick(e);if(this.measuring&&hit){this.measurePoint(hit);return;}callbacks.select(hit?.object.userData.member.id||null);};
    this.move=e=>{const hit=this.pick(e);this.renderer.domElement.style.cursor=hit?'pointer':this.measuring?'crosshair':'grab'; callbacks.hover(hit?.object.userData.member||null, e.clientX,e.clientY);};
    this.double=e=>{const hit=this.pick(e);if(hit)this.focus(hit.object.userData.member.id);};
    this.renderer.domElement.addEventListener('pointerdown',this.down);this.renderer.domElement.addEventListener('pointerup',this.up);this.renderer.domElement.addEventListener('pointermove',this.move);this.renderer.domElement.addEventListener('dblclick',this.double);
    this.renderer.domElement.addEventListener('pointerleave',()=>callbacks.hover(null));
    this.animate=()=>{if(this.disposed)return;this.frame=requestAnimationFrame(this.animate);if(this.tween){const t=Math.min(1,(performance.now()-this.tween.time)/500),e=1-(1-t)**3;this.camera.position.lerpVectors(this.tween.from,this.tween.to,e);this.controls.target.lerpVectors(this.tween.targetFrom,this.tween.targetTo,e);if(t===1)this.tween=null;}this.controls.update();this.renderer.render(this.scene,this.camera);this.labels.render(this.scene,this.camera);};
    this.animate(); this.resize();
  }
  resize(){const {clientWidth:w,clientHeight:h}=this.container;if(!w||!h)return;const widthChanged=this.previousWidth&&Math.abs(w-this.previousWidth)>10;this.previousWidth=w;this.camera.aspect=w/h;this.camera.updateProjectionMatrix();this.renderer.setSize(w,h);this.labels.setSize(w,h);if(widthChanged&&this.bounds)this.view(this.lastView||'3d',false);}
  clear(group){while(group.children.length){const obj=group.children[0];obj.traverse(n=>{n.geometry?.dispose();if(n.material){for(const m of Array.isArray(n.material)?n.material:[n.material])m.dispose();}if(n.element)n.element.remove();});group.remove(obj);}}
  label(text,p,className='dimension-label',click){const el=document.createElement(click?'button':'div');el.className=className;el.textContent=text;if(click){el.onclick=click;el.title='Edit this bay dimension';}const obj=new CSS2DObject(el);obj.position.copy(p);this.dimensionGroup.add(obj);return obj;}
  line(points,group=this.dimensionGroup,color='#8999aa'){const line=new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),new THREE.LineBasicMaterial({color,transparent:true,opacity:.7}));group.add(line);return line;}
  setModel(data){
    const first=!this.data;this.data=data;this.clear(this.group);this.clear(this.dimensionGroup);this.clear(this.supportGroup);this.clear(this.annotation);this.meshes=[];
    for(const member of data.members){const mesh=new THREE.Mesh(memberGeometry(member),new THREE.MeshStandardMaterial({color:COLORS[member.type],metalness:.45,roughness:.44}));mesh.userData.member=member;this.group.add(mesh);this.meshes.push(mesh);}
    const grid=data.grid,x=grid.x_lines_ft||grid.x_lines,y=grid.y_lines_ft||grid.y_lines,w=x.at(-1),l=y.at(-1);
    this.bounds=new THREE.Box3(new THREE.Vector3(-2,0,-2),new THREE.Vector3(w+2,Math.max(...data.members.map(m=>Math.max(m.start[2],m.end[2])),24),l+2));
    if(this.floor){this.scene.remove(this.floor);this.floor.geometry.dispose();this.floor.material.dispose();}
    this.floor=new THREE.Mesh(new THREE.PlaneGeometry(w+28,l+28),new THREE.MeshBasicMaterial({color:'#dce3e9'}));this.floor.rotation.x=-Math.PI/2;this.floor.position.set(w/2,-.17,l/2);this.scene.add(this.floor);
    if(this.gridHelper){this.scene.remove(this.gridHelper);this.gridHelper.geometry.dispose();this.gridHelper.material.dispose();}
    const size=Math.max(w,l)+160;this.gridHelper=new THREE.GridHelper(size,Math.ceil(size/5),0xb5c1ce,0xcbd4dc);this.gridHelper.position.set(w/2,-.2,l/2);this.scene.add(this.gridHelper);
    for(let i=0;i<x.length;i++){this.line([new THREE.Vector3(x[i],0,-5),new THREE.Vector3(x[i],0,l+3)]);this.label(String(i+1),new THREE.Vector3(x[i],0,-10),'axis-label');}
    for(let i=0;i<y.length;i++){this.line([new THREE.Vector3(-5,0,y[i]),new THREE.Vector3(w+3,0,y[i])]);this.label(this.letter(i),new THREE.Vector3(-10,0,y[i]),'axis-label');}
    for(let i=0;i<x.length-1;i++){this.line([new THREE.Vector3(x[i],0,-6),new THREE.Vector3(x[i+1],0,-6)]);this.label(ft(x[i+1]-x[i]),new THREE.Vector3((x[i]+x[i+1])/2,0,-6),'dimension-label',()=>this.callbacks.dimension('x',i));}
    for(let i=0;i<y.length-1;i++){this.line([new THREE.Vector3(-6,0,y[i]),new THREE.Vector3(-6,0,y[i+1])]);this.label(ft(y[i+1]-y[i]),new THREE.Vector3(-6,0,(y[i]+y[i+1])/2),'dimension-label',()=>this.callbacks.dimension('y',i));}
    this.label('N - row A',new THREE.Vector3(w/2,0,-18),'north-label');
    const walls=data.walls||[];
    for(const wall of walls){if(!wall.start||!wall.end)continue;const a=vec(wall.start),b=vec(wall.end),a0=a.clone(),b0=b.clone();a0.y=0;b0.y=0;const geom=new THREE.BufferGeometry().setFromPoints([a0,b0,b,a0,b,a]);geom.computeVertexNormals();const mesh=new THREE.Mesh(geom,new THREE.MeshStandardMaterial({color:'#9daebb',side:THREE.DoubleSide,transparent:true,opacity:.3,depthWrite:false}));this.supportGroup.add(mesh);}
    this.setSettings(this.settings);this.select(this.selected);if(first)this.view('3d',false);
  }
  letter(i){let s='';for(i++;i;i=Math.floor((i-1)/26))s=String.fromCharCode(65+(i-1)%26)+s;return s;}
  pick(e){const r=this.renderer.domElement.getBoundingClientRect();this.mouse.set((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1);this.ray.setFromCamera(this.mouse,this.camera);return this.ray.intersectObjects(this.meshes.filter(m=>m.visible)).find(h=>this.settings.cut>=100||h.point.x<=this.clip.constant);}
  setSettings(settings){this.settings={...this.settings,...settings};if(this.gridHelper)this.gridHelper.visible=this.settings.grid;this.dimensionGroup.visible=this.settings.dimensions;this.supportGroup.visible=this.settings.walls;this.clip.constant=(this.data?.grid.width_ft||this.bounds?.max.x||100)*this.settings.cut/100;
    for(const mesh of this.meshes){const m=mesh.userData.member;mesh.visible=this.settings[m.type]&&this.settings[m.level]!==false&&(!this.isolated||m.id===this.selected);mesh.material.clippingPlanes=this.settings.cut<100?[this.clip]:[];mesh.material.needsUpdate=true;this.paint(mesh);}}
  paint(mesh){const m=mesh.userData.member,selected=m.id===this.selected;mesh.material.color.set(selected?'#b4d943':this.settings.color==='steel'?'#8396a5':COLORS[m.type]);mesh.material.emissive.set(selected?'#4e6710':'#000000');mesh.material.emissiveIntensity=selected?.32:0;}
  select(id){this.selected=id;this.clear(this.annotation);this.meshes.forEach(m=>this.paint(m));if(this.isolated)this.setSettings({});const member=this.data?.members.find(m=>m.id===id);if(member){const a=vec(member.start),b=vec(member.end);this.line([a,b],this.annotation,'#678600');const el=document.createElement('div');el.className='selected-label';el.textContent=`${member.id} · ${ft(member.length_ft)}`;const object=new CSS2DObject(el);object.position.copy(a.clone().lerp(b,.5)).add(new THREE.Vector3(0,2,0));this.annotation.add(object);}}
  fly(to,target,animated=true){if(animated)this.tween={from:this.camera.position.clone(),to,targetFrom:this.controls.target.clone(),targetTo:target,time:performance.now()};else{this.tween=null;this.camera.position.copy(to);this.controls.target.copy(target);}}
  view(name,animated=true){
    if(!this.bounds)return;this.lastView=name;
    const center=this.bounds.getCenter(new THREE.Vector3());
    const dirs={'3d':new THREE.Vector3(1.1,.85,1.15),plan:new THREE.Vector3(0,1,.0001),front:new THREE.Vector3(0,.025,1),side:new THREE.Vector3(1,.025,0)};
    const direction=(dirs[name]||dirs['3d']).clone().normalize();
    const right=new THREE.Vector3().crossVectors(new THREE.Vector3(0,1,0),direction).normalize();
    const up=new THREE.Vector3().crossVectors(direction,right).normalize();
    const tanV=Math.tan(THREE.MathUtils.degToRad(this.camera.fov/2)),tanH=tanV*this.camera.aspect;
    let distance=1;
    for(const x of [this.bounds.min.x,this.bounds.max.x])for(const y of [this.bounds.min.y,this.bounds.max.y])for(const z of [this.bounds.min.z,this.bounds.max.z]){
      const offset=new THREE.Vector3(x,y,z).sub(center);
      distance=Math.max(distance,Math.abs(offset.dot(right))/tanH+offset.dot(direction),Math.abs(offset.dot(up))/tanV+offset.dot(direction));
    }
    this.fly(center.clone().addScaledVector(direction,distance*1.18),center,animated);
    this.controls.update();this.camera.updateMatrixWorld();
  }
  focus(id=this.selected){const mesh=this.meshes.find(m=>m.userData.member.id===id);if(!mesh)return;const box=new THREE.Box3().setFromObject(mesh),center=box.getCenter(new THREE.Vector3()),size=box.getSize(new THREE.Vector3()).length();const direction=this.camera.position.clone().sub(this.controls.target).normalize();this.fly(center.clone().add(direction.multiplyScalar(Math.max(size*1.6,10))),center);}
  isolate(value){this.isolated=value;this.setSettings({});}
  zoom(factor){const d=this.camera.position.clone().sub(this.controls.target).multiplyScalar(factor);this.fly(this.controls.target.clone().add(d),this.controls.target.clone());}
  measurePoint(hit){const m=hit.object.userData.member;const a=vec(m.start),b=vec(m.end);const point=a.distanceTo(hit.point)<b.distanceTo(hit.point)?a:b;if(!this.measureStart){this.measureStart=point;this.callbacks.measure('First endpoint selected. Click another member endpoint.');return;}this.clear(this.annotation);this.line([this.measureStart,point],this.annotation,'#8da92b');const el=document.createElement('div');el.className='selected-label';el.textContent=`${ft(this.measureStart.distanceTo(point))} · endpoint to endpoint`;const label=new CSS2DObject(el);label.position.copy(point.clone().lerp(this.measureStart,.5));this.annotation.add(label);this.callbacks.measure(`Measured ${ft(this.measureStart.distanceTo(point))} between endpoints.`);this.measureStart=null;}
  setMeasuring(value){this.measuring=value;this.measureStart=null;if(!value)this.select(this.selected);}
  snapshot(){this.renderer.render(this.scene,this.camera);return this.renderer.domElement.toDataURL('image/png');}
  dispose(){this.disposed=true;cancelAnimationFrame(this.frame);this.resizeObserver.disconnect();this.controls.dispose();this.scene.traverse(o=>{o.geometry?.dispose();if(o.material)for(const m of Array.isArray(o.material)?o.material:[o.material])m.dispose();});this.renderer.dispose();this.container.replaceChildren();}
}
