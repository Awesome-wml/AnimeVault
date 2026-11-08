(function(){
var PAPER='#FDFCFA',reduce=matchMedia('(prefers-reduced-motion: reduce)').matches;
function seeded(s){return function(){s=(s*16807)%2147483647;return (s-1)/2147483646}}
function painting(){var W=1600,H=900,cv=document.createElement('canvas');cv.width=W;cv.height=H;var x=cv.getContext('2d'),rnd=seeded(20261108);x.fillStyle=PAPER;x.fillRect(0,0,W,H);
 function ridge(base,amp,col,blur,seed,fadeTop,fadeBot){var c=document.createElement('canvas');c.width=W;c.height=H;var g=c.getContext('2d');g.filter='blur('+blur+'px)';g.fillStyle=col;g.beginPath();g.moveTo(-30,H+30);
  for(var i=-30;i<=W+30;i+=5){var k=Math.pow(Math.max(0,i/W),1.35);var y=base-amp*k*(.62+.5*Math.sin(i*.0042+seed)+.22*Math.sin(i*.0125+seed*1.7)+.08*Math.sin(i*.041+seed*2.3)+.03*Math.sin(i*.11+seed));g.lineTo(i,y)}
  g.lineTo(W+30,H+30);g.closePath();g.fill();g.filter='none';g.globalCompositeOperation='destination-out';
  var a=g.createLinearGradient(0,fadeTop,0,fadeBot);a.addColorStop(0,'rgba(0,0,0,0)');a.addColorStop(1,'rgba(0,0,0,1)');g.fillStyle=a;g.fillRect(0,0,W,H);
  var b=g.createLinearGradient(0,0,W*.62,0);b.addColorStop(0,'rgba(0,0,0,1)');b.addColorStop(.55,'rgba(0,0,0,.72)');b.addColorStop(1,'rgba(0,0,0,0)');g.fillStyle=b;g.fillRect(0,0,W,H);x.drawImage(c,0,0)}
 ridge(470,430,'rgba(120,124,122,.34)',9,1.1,300,640);
 ridge(590,420,'rgba(84,88,86,.5)',5,2.7,430,760);
 ridge(700,330,'rgba(48,50,48,.7)',2.5,4.3,560,860);
 ridge(800,170,'rgba(32,33,31,.8)',1.4,6.2,700,900);
 // 枯笔皴擦，从左到右渐显
 x.globalCompositeOperation='multiply';for(var i=0;i<760;i++){var a=W*(.42+.58*Math.sqrt(rnd())),b=210+rnd()*500,l=7+rnd()*20,k=Math.max(0,(a/W-.42)/.58);x.strokeStyle='rgba(40,42,40,'+((.01+rnd()*.04)*k)+')';x.lineWidth=.5+rnd()*.9;x.beginPath();x.moveTo(a,b);x.lineTo(a-l*.3,b+l);x.stroke()}x.globalCompositeOperation='source-over';
 // 一叶孤舟，极小
 var fx=W*.56,fy=H*.70;x.fillStyle='rgba(38,36,31,.88)';x.beginPath();x.moveTo(fx-27,fy-4);x.quadraticCurveTo(fx,fy+6,fx+29,fy-6);x.quadraticCurveTo(fx,fy-.5,fx-27,fy-4);x.fill();x.fillRect(fx-2.2,fy-13,4.4,11);x.beginPath();x.arc(fx,fy-15.5,2.6,0,7);x.fill();
 x.strokeStyle='rgba(38,36,31,.13)';x.lineWidth=1;x.beginPath();x.moveTo(fx-52,fy+8);x.lineTo(fx+60,fy+8);x.stroke();x.beginPath();x.moveTo(fx-24,fy+13);x.lineTo(fx+30,fy+13);x.stroke();
 return cv}
var VS='varying vec2 vUv;void main(){vUv=uv;gl_Position=vec4(position.xy,0.,1.);}';
var FS='precision highp float;varying vec2 vUv;uniform sampler2D tex;uniform float t;uniform float aspect;uniform vec2 sc;uniform float ax;uniform vec3 paper;'+
'float h(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}'+
'float n(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);return mix(mix(h(i),h(i+vec2(1.,0.)),f.x),mix(h(i+vec2(0.,1.)),h(i+vec2(1.,1.)),f.x),f.y);}'+
'float fbm(vec2 p){float v=0.,a=.5;for(int i=0;i<5;i++){v+=a*n(p);p=p*2.03+vec2(7.,3.);a*=.5;}return v;}'+
'void main(){vec2 q=vec2(vUv.x*aspect,vUv.y);vec2 u=vec2(ax,0.)+(vUv-vec2(ax,0.))*sc;'+
'float x=clamp(t/9.,0.,1.);float prog=1.-pow(1.-x,2.2);'+
'float th=fbm(q*2.4+1.7)*.62+(1.-vUv.y)*.14;'+
'float rv=smoothstep(th-.2,th+.2,prog*1.25-.18);'+
'vec3 c=texture2D(tex,u).rgb;vec3 col=mix(paper,c,rv);'+
'float m=fbm(vec2(q.x*1.25-t*.009,q.y*4.2+sin(t*.021)*.25));'+
'float band=smoothstep(.2,.0,abs(vUv.y-.34))+.7*smoothstep(.13,.0,abs(vUv.y-.58));'+
'col=mix(col,paper,clamp(band,0.,1.)*smoothstep(.38,.7,m)*.62*prog);'+
'gl_FragColor=vec4(col,1.);}';
function hex(c){var v=parseInt(c.slice(1),16);return new THREE.Vector3((v>>16&255)/255,(v>>8&255)/255,(v&255)/255)}
function Stage(canvas,ax){var r;try{r=new THREE.WebGLRenderer({canvas:canvas,antialias:false})}catch(e){return null}
 r.setPixelRatio(Math.min(devicePixelRatio||1,1.5));var tx=new THREE.CanvasTexture(painting());tx.minFilter=THREE.LinearFilter;
 var U={tex:{value:tx},t:{value:0},aspect:{value:1},sc:{value:new THREE.Vector2(1,1)},ax:{value:ax},paper:{value:hex(PAPER)}};
 var scene=new THREE.Scene(),cam=new THREE.Camera();scene.add(new THREE.Mesh(new THREE.PlaneGeometry(2,2),new THREE.ShaderMaterial({uniforms:U,vertexShader:VS,fragmentShader:FS,depthTest:false})));
 function size(){var b=canvas.getBoundingClientRect();if(!b.width||!b.height)return;r.setSize(b.width,b.height,false);var a=b.width/b.height,ta=16/9;U.aspect.value=a;if(a>ta)U.sc.value.set(1,ta/a);else U.sc.value.set(a/ta,1)}
 size();var t0=0,on=false,raf=0,last=0;
 function draw(s){U.t.value=s;r.render(scene,cam)}
 function loop(n){if(!on)return;raf=requestAnimationFrame(loop);if(n-last<33)return;last=n;draw((n-t0)/1000)}
 return{start:function(){size();if(reduce){draw(30);return}if(!on){on=true;if(!t0)t0=performance.now();raf=requestAnimationFrame(loop)}},stop:function(){on=false;cancelAnimationFrame(raf)},size:size,draw:draw}}
var stages={};
function ensure(id){if(stages[id]!==undefined)return stages[id];var host=document.querySelector('#'+id+' [data-ink]');if(!host){stages[id]=null;return null}
 var c=document.createElement('canvas');c.className='ink';c.setAttribute('aria-hidden','true');host.insertBefore(c,host.firstChild);var st=window.THREE?Stage(c,id==='landing'?1:.62):null;
 if(!st){c.remove();var p=painting();p.className='ink';p.setAttribute('aria-hidden','true');host.insertBefore(p,host.firstChild)}
 stages[id]=st;return st}
function sync(id){Object.keys(stages).forEach(function(k){if(stages[k]&&k!==id)stages[k].stop()});if(id==='landing'||id==='login'||id==='register'){var s=ensure(id);if(s)s.start()}}
addEventListener('resize',function(){Object.keys(stages).forEach(function(k){if(stages[k])stages[k].size()})});
document.addEventListener('visibilitychange',function(){var cur=document.querySelector('body>section:not([hidden])');if(document.hidden)Object.keys(stages).forEach(function(k){if(stages[k])stages[k].stop()});else if(cur)sync(cur.id)});
var old=window.go;window.go=function(id){old(id);sync(id)};window.__stages=stages;
document.addEventListener('click',function(e){var t=e.target.closest('[data-go]');if(t)sync(t.getAttribute('data-go'))});
sync(document.querySelector('body>section:not([hidden])').id);
})();
