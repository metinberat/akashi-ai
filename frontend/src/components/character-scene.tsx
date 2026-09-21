"use client";

import { useEffect, useRef, useState } from "react";
import type { VoiceState } from "@/lib/voice";

// A shallow illustrated scene, not a reconstructed/rigged 3D body. Every ring
// and lighting mask uses the same artwork coordinates as the character.
const vertex = `attribute vec2 a; varying vec2 uv;
void main(){uv=a*.5+.5;gl_Position=vec4(a,0.,1.);}`;
const fragment = `precision highp float;
varying vec2 uv;
uniform sampler2D art;
uniform vec2 resolution, pointer;
uniform float energy, time, voice;
float ellipse(vec2 p, vec2 c, vec2 r){return 1.-smoothstep(.75,1.08,length((p-c)/r));}
float arc(vec2 p,float r,float phase,float span){
 float angle=atan(p.y,p.x); float gate=smoothstep(.05,.16,sin(angle*span+phase));
 return exp(-abs(length(p)-r)*440.)*gate;
}
float hash(float p){return fract(sin(p*127.1)*43758.5453);}
void main(){
 vec2 st=vec2(uv.x,1.-uv.y);
 float ratio=resolution.x/resolution.y;
 vec2 crop=ratio>1.777?vec2(1.,1.777/ratio):vec2(ratio/1.777,1.);
 vec2 q=(st-.5)*crop/1.28+vec2(.52,.46);
 float head=ellipse(q,vec2(.53,.27),vec2(.15,.26));
 float body=ellipse(q,vec2(.51,.67),vec2(.30,.43));
 float hand=ellipse(q,vec2(.29,.60),vec2(.19,.29));
 float depth=max(head,max(body*.7,hand));
 q+=pointer*mix(.001,.003,depth);
 vec3 col=texture2D(art,q).rgb;
 float lum=dot(col,vec3(.2126,.7152,.0722));
 col=mix(vec3(lum),col,.20+energy*.76)*(.68+energy*.28);
 // Artwork-local luminous contours: no full-frame red tint.
 float red=max(0.,texture2D(art,q).r-max(texture2D(art,q).g,texture2D(art,q).b));
 vec2 texel=vec2(1./1672.,1./941.);
 float edge=length(texture2D(art,q+texel).rgb-texture2D(art,q-texel).rgb);
 float rim=smoothstep(.23,.85,energy)*red*(.16+edge*.9);
 col+=vec3(1.,.045,.065)*rim;
 float eyes=ellipse(q,vec2(.512,.232),vec2(.024,.010))+ellipse(q,vec2(.565,.255),vec2(.024,.01));
 col+=vec3(1.,.035,.025)*eyes*smoothstep(.70,1.,energy)*red*.85;
 vec2 p=(q-vec2(.52,.35))*vec2(1.777,1.);
 float occlusion=1.-clamp(max(head,body),0.,1.);
 float wake=smoothstep(.08,.55,energy);
 float flow=time*(.035+energy*.07);
 float rings=arc(p,.335,flow,3.)+arc(p,.365,-flow*.7,7.)*.7+arc(p,.400,flow*.43,5.)*.48;
 float halo=exp(-abs(length(p)-.36)*40.)*(.12+voice*.05*(.5+.5*sin(time*2.)));
 col+=mix(vec3(.55,.57,.60),vec3(1.,.035,.055),smoothstep(.28,.95,energy))*(rings+halo)*wake*(.06+occlusion*.88);
 float grit=0.;
 for(int i=0;i<40;i++){
   float id=float(i); float angle=hash(id+1.)*6.283+flow*(.2+hash(id+15.));
   float radius=.29+hash(id+6.)*.40;
   vec2 node=vec2(cos(angle),sin(angle)) * radius;
   float d=length(p-node);
   float strength=smoothstep(hash(id+9.)*.8,.3+hash(id+9.)*.8,energy);
   grit+=exp(-d*800.)*strength*(.55+.45*sin(time*.8+id));
 }
 col+=vec3(1.,.05,.065)*grit*(.25+occlusion*.75);
 float vignette=smoothstep(.02,.18,st.x)*(1.-smoothstep(.80,1.,st.x));
 float bottom=1.-smoothstep(.70,1.05,st.y)*.85;
 col*=vignette*bottom;
 gl_FragColor=vec4(col,1.);
}`;

export function CharacterScene({ energy, voiceState }: { energy: number; voiceState: VoiceState }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const target = useRef(energy);
  const voice = useRef(voiceState);
  const redraw = useRef<() => void>(() => {});
  const [status, setStatus] = useState("loading");
  useEffect(() => { target.current = energy; voice.current = voiceState; redraw.current(); }, [energy, voiceState]);
  useEffect(() => {
    const canvas = ref.current;
    const gl = canvas?.getContext("webgl", { alpha: false, antialias: false, powerPreference: "low-power" });
    if (!canvas || !gl) { requestAnimationFrame(() => setStatus("fallback")); return; }
    let disposed = false, frame = 0, ready = false, t = 0, previous = 0;
    let current = target.current, start = current, goal = current, elapsed = 0, duration = 5.2;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    const position = { x: 0, y: 0 };
    const compile = (type: number, source: string) => {
      const shader = gl.createShader(type)!; gl.shaderSource(shader, source); gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) { gl.deleteShader(shader); throw new Error("Scene shader unavailable"); }
      return shader;
    };
    let program: WebGLProgram; let vs: WebGLShader; let fs: WebGLShader;
    try {
      vs = compile(gl.VERTEX_SHADER, vertex); fs = compile(gl.FRAGMENT_SHADER, fragment);
      program = gl.createProgram()!; gl.attachShader(program, vs); gl.attachShader(program, fs); gl.linkProgram(program);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error("Scene linking unavailable");
    } catch { requestAnimationFrame(() => setStatus("fallback")); return; }
    gl.useProgram(program);
    const buffer = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 1,-1, -1,1, -1,1, 1,-1, 1,1]), gl.STATIC_DRAW);
    const attribute = gl.getAttribLocation(program, "a"); gl.enableVertexAttribArray(attribute); gl.vertexAttribPointer(attribute, 2, gl.FLOAT, false, 0, 0);
    const texture = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    const u = Object.fromEntries(["resolution", "pointer", "energy", "time", "voice"].map(key => [key, gl.getUniformLocation(program, key)]));
    const resize = () => {
      // Bounded drawing buffer; DOM text remains native-resolution and crisp.
      const r = canvas.getBoundingClientRect(); const scale = Math.min(devicePixelRatio, 1.25, 2560 / Math.max(r.width, 1));
      canvas.width = Math.round(r.width * scale); canvas.height = Math.round(r.height * scale);
      gl.viewport(0, 0, canvas.width, canvas.height);
    };
    const draw = (now: number) => {
      if (disposed || document.hidden || !ready || gl.isContextLost()) return;
      if (!reduced.matches && now - previous < 1000 / 60) { frame = requestAnimationFrame(draw); return; }
      const dt = Math.min((now - previous) / 1000, .05); previous = now;
      if (goal !== target.current) { start = current; goal = target.current; elapsed = 0; duration = goal > start ? 5.2 : 4.2; }
      elapsed += dt;
      const progress = reduced.matches ? 1 : Math.min(elapsed / duration, 1);
      current = start + (goal - start) * (progress * progress * (3 - 2 * progress));
      if (!reduced.matches) t += dt;
      gl.uniform2f(u.resolution, canvas.width, canvas.height); gl.uniform2f(u.pointer, reduced.matches ? 0 : position.x, reduced.matches ? 0 : position.y);
      gl.uniform1f(u.energy, current); gl.uniform1f(u.time, t); gl.uniform1f(u.voice, voice.current === "idle" ? 0 : 1);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
      canvas.dataset.energy = current.toFixed(3);
      canvas.dataset.frames = String(Number(canvas.dataset.frames || 0) + 1);
      if (!reduced.matches) frame = requestAnimationFrame(draw);
    };
    const image = new Image(); image.onload = () => {
      if (disposed) return;
      gl.bindTexture(gl.TEXTURE_2D, texture); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
      resize(); ready = true; setStatus("ready"); frame = requestAnimationFrame(draw);
    };
    image.onerror = () => { if (!disposed) setStatus("fallback"); };
    image.src = "./desktop/akashi-core-wide.png";
    const observer = new ResizeObserver(() => { resize(); redraw.current(); }); observer.observe(canvas);
    const move = (event: PointerEvent) => { position.x = event.clientX / innerWidth - .5; position.y = event.clientY / innerHeight - .5; };
    const visibility = () => { cancelAnimationFrame(frame); previous = performance.now(); if (!document.hidden) frame = requestAnimationFrame(draw); };
    redraw.current = visibility;
    reduced.addEventListener("change", visibility);
    const lost = (event: Event) => { event.preventDefault(); cancelAnimationFrame(frame); setStatus("fallback"); };
    window.addEventListener("pointermove", move, { passive: true }); document.addEventListener("visibilitychange", visibility); canvas.addEventListener("webglcontextlost", lost);
    return () => { disposed = true; redraw.current = () => {}; reduced.removeEventListener("change", visibility); cancelAnimationFrame(frame); observer.disconnect(); window.removeEventListener("pointermove", move); document.removeEventListener("visibilitychange", visibility); canvas.removeEventListener("webglcontextlost", lost); gl.deleteTexture(texture); gl.deleteBuffer(buffer); gl.deleteProgram(program); gl.deleteShader(vs); gl.deleteShader(fs); };
  }, []);
  return <div className="character-scene" data-renderer={status} aria-hidden="true"><canvas ref={ref} className="character-canvas" /></div>;
}
