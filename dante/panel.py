"""El panel: ver por los ojos de Dante y hablarle desde el navegador.

Corre DENTRO del mismo proceso que la sesion de voz. Ni la camara ni el puerto
serie se pueden abrir dos veces, asi que el panel no es otro programa: es una
ventana sobre el que ya esta corriendo.

Sirve para tres cosas:
  - ver lo que la camara ve, con las caras marcadas y con nombre
  - hablarle por texto o por microfono desde el navegador
  - seguir la conversacion y las herramientas que usa, en vivo
"""
from __future__ import annotations

import asyncio
import json
import threading
import time

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

from . import ajustes, auth, config, memoria, mensajes as msg

PAGINA = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dante</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* Paleta de perro: madera clara, miel y un verde de paseo.
   Nada de gris de panel de control: esto lo abre una familia, no un operador. */
:root{
  --fondo:#faf6f0; --tarjeta:#fffdfa; --borde:#e9ded0; --hueso:#f2e9dd;
  --tinta:#33281f; --tinta2:#7d6b58; --tinta3:#a89684;
  --miel:#e8952f; --miel-suave:#fdf0dc;
  --paseo:#3f9c73; --paseo-suave:#e3f3ec;
  --hocico:#5b4636; --alerta:#d1614a; --alerta-suave:#fbe8e4;
  --sombra:0 1px 2px rgba(91,70,54,.06), 0 10px 30px -18px rgba(91,70,54,.3);
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --fondo:#1b1712; --tarjeta:#241e18; --borde:#3a3129; --hueso:#2c251e;
  --tinta:#f4ece2; --tinta2:#b8a794; --tinta3:#8a7863;
  --miel:#f0aa4e; --miel-suave:#3a2c18;
  --paseo:#6fc39b; --paseo-suave:#1e3229;
  --hocico:#d9c4ac; --alerta:#eb8570; --alerta-suave:#3a221d;
  --sombra:0 1px 2px rgba(0,0,0,.3), 0 10px 30px -18px rgba(0,0,0,.7);}}
:root[data-theme="dark"]{
  --fondo:#1b1712; --tarjeta:#241e18; --borde:#3a3129; --hueso:#2c251e;
  --tinta:#f4ece2; --tinta2:#b8a794; --tinta3:#8a7863;
  --miel:#f0aa4e; --miel-suave:#3a2c18;
  --paseo:#6fc39b; --paseo-suave:#1e3229;
  --hocico:#d9c4ac; --alerta:#eb8570; --alerta-suave:#3a221d;
  --sombra:0 1px 2px rgba(0,0,0,.3), 0 10px 30px -18px rgba(0,0,0,.7);}
*{box-sizing:border-box}
body{margin:0;background:var(--fondo);color:var(--tinta);
  font:16px/1.6 Nunito,system-ui,sans-serif;-webkit-font-smoothing:antialiased}
.mono{font-family:"IBM Plex Mono",monospace}

/* ---------- cabecera con la carita ---------- */
header{display:flex;align-items:center;gap:16px;padding:16px 22px;
  background:var(--tarjeta);border-bottom:1px solid var(--borde);
  position:sticky;top:0;z-index:20}
.carita{width:64px;height:46px;border-radius:14px;background:var(--hocico);
  display:grid;place-items:center;flex:none;box-shadow:var(--sombra);
  transition:background .4s}
.carita svg{display:block}
.ojo{transition:all .25s cubic-bezier(.34,1.56,.64,1)}
h1{margin:0;font-size:20px;font-weight:800;letter-spacing:-.02em}
.animo{font-size:13px;color:var(--tinta2);font-weight:600;margin-top:-2px}
.tabs{margin-left:auto;display:flex;gap:4px;flex-wrap:wrap}
.tab{background:none;border:none;color:var(--tinta2);padding:9px 15px;
  border-radius:11px;font:600 14px Nunito,sans-serif;cursor:pointer;
  transition:all .15s}
.tab:hover{background:var(--hueso);color:var(--tinta)}
.tab.on{background:var(--miel-suave);color:var(--miel)}

/* ---------- estructura ---------- */
main{display:none;max-width:1180px;margin:0 auto;padding:20px}
main.on{display:block}
.cols{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(340px,1fr);gap:18px;
  align-items:start}
@media(max-width:920px){.cols{grid-template-columns:1fr}}
.caja{background:var(--tarjeta);border:1px solid var(--borde);border-radius:18px;
  overflow:hidden;box-shadow:var(--sombra)}
.caja h2{margin:0;padding:15px 20px;font-size:15px;font-weight:800;
  border-bottom:1px solid var(--borde);display:flex;align-items:center;gap:9px}
.caja h2 small{margin-left:auto;font:500 12px "IBM Plex Mono",monospace;
  color:var(--tinta3)}
.pad{padding:18px 20px}
.ayuda{font-size:13.5px;color:var(--tinta2);margin:0 0 14px}

/* ---------- camara ---------- */
#video{display:block;width:100%;background:#15110d;aspect-ratio:16/9;object-fit:contain}
#caras{padding:12px 20px;display:flex;gap:8px;flex-wrap:wrap;align-items:center;
  font-size:13px;color:var(--tinta2);min-height:46px}
.quien{background:var(--paseo-suave);color:var(--paseo);border-radius:999px;
  padding:4px 13px;font-weight:700;font-size:13px}
.quien.no{background:var(--miel-suave);color:var(--miel)}

/* ---------- charla ---------- */
#charla{height:min(44vh,400px);overflow-y:auto;padding:18px 20px;
  display:flex;flex-direction:column;gap:12px}
.msg{max-width:86%;padding:11px 16px;border-radius:18px;font-size:15px;
  line-height:1.5;animation:entra .25s ease}
@keyframes entra{from{opacity:0;transform:translateY(6px)}}
.msg.yo{align-self:flex-end;background:var(--paseo);color:#fff;
  border-bottom-right-radius:6px}
.msg.el{align-self:flex-start;background:var(--hueso);border-bottom-left-radius:6px}
.msg.sis{align-self:center;background:none;color:var(--tinta3);
  font:500 12.5px "IBM Plex Mono",monospace;padding:2px}
.vacio{margin:auto;text-align:center;color:var(--tinta3);font-size:14px}

.barra{display:flex;gap:10px;padding:14px 20px;border-top:1px solid var(--borde);
  align-items:center}
input[type=text],select,textarea{flex:1;background:var(--fondo);
  border:1.5px solid var(--borde);border-radius:13px;color:var(--tinta);
  padding:12px 15px;font:400 15px Nunito,sans-serif;transition:border-color .15s}
input:focus,select:focus,textarea:focus{outline:none;border-color:var(--miel)}
textarea{min-height:78px;resize:vertical;line-height:1.55}
button{background:var(--hueso);color:var(--tinta);border:none;border-radius:13px;
  padding:12px 18px;font:700 15px Nunito,sans-serif;cursor:pointer;
  transition:all .15s}
button:hover{filter:brightness(.96)}
button:active{transform:scale(.97)}
.pri{background:var(--miel);color:#fff}
.ok{background:var(--paseo);color:#fff}
.grande{width:100%;padding:17px;font-size:16.5px;display:flex;
  align-items:center;justify-content:center;gap:10px}
.grande.hablando{background:var(--paseo);color:#fff;animation:late 1.1s infinite}
@keyframes late{0%,100%{transform:scale(1)}50%{transform:scale(1.02)}}
.pista{padding:0 20px 16px;font-size:12.5px;color:var(--tinta3);text-align:center}

/* ---------- formularios ---------- */
label{display:flex;flex-direction:column;gap:7px;font-size:13px;font-weight:700;
  color:var(--tinta2)}
.dos{display:grid;grid-template-columns:1fr 1fr;gap:15px}
@media(max-width:600px){.dos{grid-template-columns:1fr}}
form{display:flex;flex-direction:column;gap:16px}
.aviso{margin:0 20px 16px;padding:11px 16px;border-radius:12px;font-size:13.5px;
  font-weight:600;background:var(--paseo-suave);color:var(--paseo);display:none}

/* ---------- fichas ---------- */
.rejilla{display:grid;grid-template-columns:repeat(auto-fill,minmax(165px,1fr));
  gap:12px;padding:18px 20px}
.ficha{background:var(--hueso);border-radius:14px;padding:15px;
  display:flex;flex-direction:column;gap:5px}
.ficha b{font-size:15px}
.ficha small{color:var(--tinta2);font-size:12.5px}
.sello{font:700 11px "IBM Plex Mono",monospace;padding:3px 9px;border-radius:999px;
  width:fit-content;margin-top:4px;background:var(--paseo-suave);color:var(--paseo)}
.sello.no{background:var(--miel-suave);color:var(--miel)}

/* ---------- señales ---------- */
.senal{display:flex;gap:14px;padding:16px 20px;border-bottom:1px solid var(--borde);
  align-items:flex-start}
.senal:last-child{border-bottom:none}
.veces{flex:none;width:44px;height:44px;border-radius:14px;display:grid;
  place-items:center;font:800 17px Nunito;background:var(--miel-suave);color:var(--miel)}
.senal.mucho .veces{background:var(--alerta-suave);color:var(--alerta)}
.senal b{font-size:15px;display:block}
.senal p{margin:4px 0 0;font-size:13.5px;color:var(--tinta2);font-style:italic}
.senal .cuando{font:500 12px "IBM Plex Mono",monospace;color:var(--tinta3)}

/* ---------- mensajes ---------- */
.grabando{background:var(--alerta)!important;color:#fff!important;
  animation:late 1s infinite}
.mensaje{display:flex;gap:13px;align-items:center;padding:14px 20px;
  border-bottom:1px solid var(--borde)}
.mensaje:last-child{border-bottom:none}
.burbuja{flex:none;width:40px;height:40px;border-radius:50%;display:grid;
  place-items:center;background:var(--miel-suave);color:var(--miel);
  font:800 15px Nunito}
.mensaje b{font-size:14.5px}
.mensaje small{display:block;color:var(--tinta2);font-size:12.5px}
.nuevo{margin-left:auto;font:700 11px "IBM Plex Mono",monospace;
  background:var(--paseo);color:#fff;padding:3px 9px;border-radius:999px}
</style></head><body>

<header>
  <div class="carita" id="carita">
    <svg width="46" height="30" viewBox="0 0 46 30">
      <rect id="oi" class="ojo" x="4" y="5" width="16" height="20" rx="7" fill="#7fd4f5"/>
      <rect id="od" class="ojo" x="26" y="5" width="16" height="20" rx="7" fill="#7fd4f5"/>
    </svg>
  </div>
  <div>
    <h1 id="titulo">Dante</h1>
    <div class="animo" id="animo">conectando…</div>
  </div>
  <nav class="tabs">
    <button class="tab on" data-v="charla">Conversar</button>
    <button class="tab" data-v="gente">Personas</button>
    <button class="tab" data-v="voz">Mensajes</button>
    <button class="tab" data-v="senales">Cómo está</button>
    <button class="tab" data-v="cfg">Ajustes</button>
  </nav>
</header>

<!-- ============ CONVERSAR ============ -->
<main id="v-charla" class="on"><div class="cols">
  <div class="caja">
    <h2>🐾 Lo que ve Dante</h2>
    <img id="video" src="/camara.mjpg" alt="cámara">
    <div id="caras">nadie a la vista</div>
  </div>
  <div class="caja">
    <h2>Conversación</h2>
    <div id="charla"><div class="vacio">Todavía no han hablado hoy.<br>Apretá el botón de abajo y decile algo.</div></div>
    <div class="barra">
      <input type="text" id="entrada" placeholder="Escribile a Dante…" autocomplete="off">
      <button id="enviar" class="pri">Enviar</button>
    </div>
    <div class="barra" style="border-top:none;padding-top:0">
      <button id="micro" class="grande ok">🎙️ Mantené para hablar</button>
    </div>
    <div class="barra" style="border-top:none;padding-top:0">
      <button id="altavoz" style="flex:1">🔊 Altavoz: sí</button>
      <button id="diario" style="flex:1">☀️ ¿Cómo va el día?</button>
    </div>
    <div class="pista">También podés mantener la <b>barra espaciadora</b>.</div>
  </div>
</div></main>

<!-- ============ PERSONAS ============ -->
<main id="v-gente"><div class="cols">
  <div class="caja">
    <h2>Quién está enfrente</h2>
    <img id="video2" src="/camara.mjpg" alt="cámara">
    <div class="pad">
      <p class="ayuda">Poné a la persona de frente, con buena luz y que quede sola en el cuadro. Dante va a reconocerla la próxima vez y va a decir su nombre en voz alta.</p>
      <div class="dos" style="margin-bottom:14px">
        <input type="text" id="nom" placeholder="Nombre (Ana)">
        <input type="text" id="rel" placeholder="Parentesco (hija)">
      </div>
      <button id="btn-cara" class="pri grande">📸 Recordar esta cara</button>
    </div>
    <div class="aviso" id="aviso-cara"></div>
  </div>
  <div class="caja">
    <h2>Su gente <small id="n-gente"></small></h2>
    <div class="rejilla" id="gente">cargando…</div>
  </div>
</div></main>

<!-- ============ MENSAJES ============ -->
<main id="v-voz"><div class="cols">
  <div class="caja">
    <h2>💌 Dejale un mensaje</h2>
    <div class="pad">
      <p class="ayuda">Grabá con tu voz. Cuando pregunte por vos, Dante se lo reproduce — <b>con tu voz, no con la suya</b>. Para alguien que se olvida de las caras, oír a su hija vale más que oír a un asistente contándole que llamó.</p>
      <label style="margin-bottom:14px">De parte de quién
        <input type="text" id="de" placeholder="Ana">
      </label>
      <button id="grabar" class="pri grande">🔴 Mantené para grabar</button>
      <div class="pista" id="tiempo" style="padding:12px 0 0">hasta 60 segundos</div>
    </div>
    <div class="aviso" id="aviso-voz"></div>
  </div>
  <div class="caja">
    <h2>Mensajes dejados <small id="n-voz"></small></h2>
    <div id="voces"><div class="pad ayuda">Todavía no hay ninguno.</div></div>
  </div>
</div></main>

<!-- ============ SEÑALES ============ -->
<main id="v-senales">
  <div class="caja" style="max-width:760px;margin:0 auto">
    <h2>Cómo estuvo esta semana <small id="n-sen"></small></h2>
    <div class="pad" style="padding-bottom:6px">
      <p class="ayuda">Cosas que mencionó en sus conversaciones. <b>Esto no es un diagnóstico</b> y Dante no interpreta nada: solo repite lo que ella dijo, y cuántas veces. Si algo se repite, quizás valga la pena preguntarle.</p>
    </div>
    <div id="senales"><div class="pad ayuda">Sin novedades. Eso es buena señal.</div></div>
  </div>
</main>

<!-- ============ AJUSTES ============ -->
<main id="v-cfg">
  <div class="caja" style="max-width:760px;margin:0 auto">
    <h2>Cómo es y cómo se comporta</h2>
    <div class="aviso" id="aviso-cfg">Guardado. Ya se lo dije a Dante.</div>
    <form class="pad" id="cfg">
      <div class="dos">
        <label>¿Cómo se llama?<input name="nombre_usuario" placeholder="Rosa"></label>
        <label>¿Cómo tratarla?<select name="trato">
          <option value="tu">De tú</option><option value="usted">De usted</option></select></label>
      </div>
      <div class="dos">
        <label>Nombre de la mascota<input name="nombre_mascota" placeholder="Dante"></label>
        <label>¿Qué es?<input name="especie" placeholder="perro"></label>
      </div>
      <div class="dos">
        <label>Voz<select name="voz">
          <option value="coral">coral — clarita y alegre</option>
          <option value="shimmer">shimmer — suave y ligera</option>
          <option value="sage">sage — tranquila</option>
          <option value="ballad">ballad — dulce</option>
          <option value="marin">marin — adulta</option>
          <option value="cedar">cedar — grave</option>
          <option value="alloy">alloy — neutra</option></select></label>
        <label>Edad de la voz<select name="edad_voz">
          <option value="nino">como un cachorrito</option>
          <option value="joven">joven</option>
          <option value="adulto">adulta</option></select></label>
      </div>
      <div class="dos">
        <label>Ciudad<input name="ciudad" placeholder="Bogotá"></label>
      </div>
      <label>¿Cómo querés que se comporte?
        <textarea name="caracter" placeholder="Paciente. Si repite una pregunta, respondele igual de bien la segunda vez, sin hacérselo notar."></textarea></label>
      <label>Temas que le gusta conversar
        <textarea name="temas_queridos" placeholder="Su época de maestra, música de los sesenta, sus nietos"></textarea></label>
      <label>Temas que es mejor no sacar
        <textarea name="temas_evitar" placeholder="La muerte de su esposo, salvo que ella lo saque"></textarea></label>
      <label>¿A quién avisamos si algo preocupa?
        <input name="contacto_familia" placeholder="ana@correo.com"></label>
      <button type="submit" class="pri grande">Guardar</button>
    </form>
  </div>

  <div class="caja" style="max-width:760px;margin:18px auto 0">
    <h2>Su vida 🦴</h2>
    <p class="pad" style="margin:0;opacity:.75;line-height:1.5">
      Esto no se queda en un formulario: Dante <b>lo guarda en su memoria</b>,
      con el nombre de ella, igual que lo que aprende conversando. Mientras
      más le cuentes, menos tiene que preguntar.<br>
      Podés dejar todo vacío y llenarlo después — o dejar que lo aprenda solo.
    </p>
    <form class="pad" id="cfg2">
      <div class="dos">
        <label>¿Cuándo y dónde nació?
          <input name="nacio" placeholder="en 1948, en Santa Marta"></label>
        <label>¿A qué se dedicó?
          <input name="oficio" placeholder="fue maestra de primaria 30 años"></label>
      </div>
      <label>¿Con quién vive?
        <input name="vive_con" placeholder="sola, pero su hija Ana viene los martes"></label>
      <label>Su familia: nombres y quién es cada uno
        <textarea name="familia" placeholder="Ana, su hija mayor. Miguel, su hijo, vive en Cali. Lucía, su nieta de 12 años."></textarea></label>
      <label>Salud: lo que conviene que sepa
        <textarea name="salud" placeholder="Toma pastilla para la presión en la mañana. Le duele la rodilla izquierda. Oye poco del oído derecho."></textarea></label>
      <label>¿Cómo es su día?
        <textarea name="rutina" placeholder="Se levanta a las 6. Desayuna viendo las noticias. Duerme siesta después del almuerzo."></textarea></label>
      <label>Lo que le gusta contar
        <textarea name="historia" placeholder="Cómo conoció a su esposo en un baile. Los años en que enseñaba. El viaje a Cartagena del 82."></textarea></label>
      <button type="submit" class="pri grande">Guardar en su memoria</button>
    </form>
  </div>
</main>

<script>
const $ = (s) => document.querySelector(s);
const charla = $('#charla'), animo = $('#animo'), carita = $('#carita');
const oi = $('#oi'), od = $('#od');
let ws, entra, sale, flujo, nodo, hablando = false, proximo = 0;
let altavozOn = localStorage.getItem('dante_altavoz') !== 'no';

/* ---------- la carita ---------- */
const CARAS = {
  idle:      {c:'#7fd4f5', f:'listo',      h:20, y:5,  r:7},
  escuchando:{c:'#7ee6b8', f:'te escucha', h:22, y:4,  r:11},
  pensando:  {c:'#f6c26b', f:'pensando…',  h:14, y:2,  r:6},
  hablando:  {c:'#8fd0f8', f:'hablando',   h:20, y:5,  r:7},
  feliz:     {c:'#8ef0c4', f:'contento',   h:11, y:12, r:5},
  atencion:  {c:'#f7a0a0', f:'atento',     h:22, y:4,  r:10},
};
function pintarCara(e){
  const d = CARAS[e] || CARAS.idle;
  animo.textContent = d.f;
  for (const o of [oi, od]){
    o.setAttribute('fill', d.c);
    o.setAttribute('height', d.h);
    o.setAttribute('y', d.y);
    o.setAttribute('rx', d.r);
  }
}
pintarCara('idle');
setInterval(() => {                       // parpadeo
  if (animo.textContent !== 'listo') return;
  for (const o of [oi,od]){ o.setAttribute('height',3); o.setAttribute('y',13); }
  setTimeout(()=>pintarCara('idle'), 130);
}, 4200 + Math.random()*2600);

function linea(cl, t){
  const v = charla.querySelector('.vacio'); if (v) v.remove();
  const d = document.createElement('div');
  d.className = 'msg ' + cl; d.textContent = t;
  charla.appendChild(d); charla.scrollTop = charla.scrollHeight;
}

/* ---------- conexión ---------- */
function conectar(){
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.binaryType = 'arraybuffer';
  ws.onopen = () => pintarCara('idle');
  ws.onclose = () => { animo.textContent = 'desconectado'; setTimeout(conectar, 1500); };
  ws.onmessage = (e) => {
    if (typeof e.data !== 'string'){ reproducir(e.data); return; }
    const m = JSON.parse(e.data);
    if (m.t === 'estado') pintarCara(m.v);
    else if (m.t === 'dijo') linea(m.quien === 'dante' ? 'el' : 'yo', m.texto);
    else if (m.t === 'herramienta') linea('sis', '· ' + m.nombre.replace(/_/g,' ') + ' ·');
    else if (m.t === 'pantalla') linea('sis', m.titulo + ': ' + m.cuerpo);
    else if (m.t === 'mensaje') linea('sis', '💌 reproduciendo el mensaje de ' + m.de);
    else if (m.t === 'caras'){
      const c = $('#caras'); c.innerHTML = '';
      if (!m.lista.length){ c.textContent = 'nadie a la vista'; return; }
      m.lista.forEach(x => {
        const s = document.createElement('span');
        s.className = 'quien' + (x.nombre ? '' : ' no');
        s.textContent = x.nombre || 'no la conozco';
        c.appendChild(s);
      });
    }
  };
}
conectar();

/* ---------- audio de salida ---------- */
function reproducir(datos){
  if (!altavozOn) return;
  if (!sale){ sale = new AudioContext({sampleRate:24000}); proximo = 0; }
  if (sale.state === 'suspended') sale.resume();
  const pcm = new Int16Array(datos); if (!pcm.length) return;
  const b = sale.createBuffer(1, pcm.length, 24000), ch = b.getChannelData(0);
  for (let i=0;i<pcm.length;i++) ch[i] = pcm[i]/32768;
  const n = sale.createBufferSource(); n.buffer = b; n.connect(sale.destination);
  const ahora = sale.currentTime;
  if (proximo < ahora + .06) proximo = ahora + .06;
  n.start(proximo); proximo += b.duration;
}

/* ---------- micrófono ---------- */
async function abrirMicro(){
  if (entra) return true;
  try{
    entra = new AudioContext({sampleRate:24000});
    flujo = await navigator.mediaDevices.getUserMedia({audio:{
      echoCancellation:true, noiseSuppression:true, autoGainControl:true}});
    const f = entra.createMediaStreamSource(flujo);
    nodo = entra.createScriptProcessor(1024,1,1);
    nodo.onaudioprocess = (e) => {
      const d = e.inputBuffer.getChannelData(0);
      const p = new Int16Array(d.length);
      for (let i=0;i<d.length;i++){ const v=Math.max(-1,Math.min(1,d[i]));
        p[i] = v<0 ? v*0x8000 : v*0x7fff; }
      if (hablando && ws && ws.readyState===1) ws.send(p.buffer);
      if (grabandoVoz) trozos.push(p);
    };
    f.connect(nodo); nodo.connect(entra.destination);
    return true;
  }catch(err){ linea('sis','no pude abrir el micrófono: '+err.message); return false; }
}

const micro = $('#micro');
async function hablarSi(){
  if (hablando) return;
  if (!await abrirMicro()) return;
  hablando = true;
  micro.classList.add('hablando'); micro.textContent = '🎙️ Te escucho… soltá al terminar';
  ws.send(JSON.stringify({t:'boton', v:'abajo'}));
}
function hablarNo(){
  if (!hablando) return;
  hablando = false;
  micro.classList.remove('hablando'); micro.textContent = '🎙️ Mantené para hablar';
  ws.send(JSON.stringify({t:'boton', v:'arriba'}));
}
micro.addEventListener('mousedown', hablarSi);
micro.addEventListener('touchstart', e=>{e.preventDefault();hablarSi();});
addEventListener('mouseup', hablarNo); addEventListener('touchend', hablarNo);
addEventListener('keydown', e=>{ if(e.code==='Space' && e.target.tagName!=='INPUT'
  && e.target.tagName!=='TEXTAREA'){e.preventDefault();hablarSi();} });
addEventListener('keyup', e=>{ if(e.code==='Space') hablarNo(); });

$('#enviar').onclick = mandar;
$('#entrada').onkeydown = e => { if (e.key==='Enter') mandar(); };
function mandar(){
  const i = $('#entrada');
  if (!i.value.trim() || !ws || ws.readyState!==1) return;
  ws.send(JSON.stringify({t:'texto', v:i.value})); i.value='';
}
$('#diario').onclick = () => ws.send(JSON.stringify({t:'diario'}));
const alt = $('#altavoz');
function pintarAlt(){ alt.textContent = altavozOn ? '🔊 Altavoz: sí' : '🔇 Altavoz: no';
  alt.style.opacity = altavozOn ? 1 : .6; }
pintarAlt();
alt.onclick = () => { altavozOn = !altavozOn;
  localStorage.setItem('dante_altavoz', altavozOn?'si':'no'); pintarAlt(); };

/* ---------- pestañas ---------- */
document.querySelectorAll('.tab').forEach(b => b.onclick = () => {
  document.querySelectorAll('.tab').forEach(x=>x.classList.remove('on'));
  document.querySelectorAll('main').forEach(x=>x.classList.remove('on'));
  b.classList.add('on'); $('#v-'+b.dataset.v).classList.add('on');
  if (b.dataset.v==='gente') cargarGente();
  if (b.dataset.v==='senales') cargarSenales();
  if (b.dataset.v==='voz') cargarVoces();
});

/* ---------- ajustes ---------- */
const form = $('#cfg'), form2 = $('#cfg2');
async function cargarCfg(){
  const a = await (await fetch('/api/ajustes')).json();
  for (const [k,v] of Object.entries(a.ajustes||{})){
    const el = form.elements[k] || form2.elements[k]; if (el) el.value = v; }
  if (a.ajustes?.nombre_mascota) $('#titulo').textContent = a.ajustes.nombre_mascota;
}
cargarCfg();
// Los dos formularios mandan siempre los dos juegos de datos. Si mandaran
// solo lo suyo, guardar uno borraria los recuerdos que escribio el otro.
async function guardarTodo(aviso){
  const d = {...Object.fromEntries(new FormData(form).entries()),
             ...Object.fromEntries(new FormData(form2).entries())};
  await fetch('/api/ajustes',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(d)});
  avisar('#aviso-cfg', aviso);
  if (d.nombre_mascota) $('#titulo').textContent = d.nombre_mascota;
}
form.onsubmit  = e => { e.preventDefault(); guardarTodo('Guardado. Ya se lo dije a Dante.'); };
form2.onsubmit = e => { e.preventDefault();
  guardarTodo('Guardado. Dante ya lo tiene en su memoria.');
  window.scrollTo({top:0,behavior:'smooth'}); };
function avisar(sel, txt){ const a=$(sel); a.textContent=txt; a.style.display='block';
  setTimeout(()=>a.style.display='none', 3600); }

/* ---------- personas ---------- */
async function cargarGente(){
  const g = $('#gente'), r = await (await fetch('/api/personas')).json();
  $('#n-gente').textContent = r.personas.length + ' personas';
  if (!r.personas.length){ g.innerHTML='<div class="ayuda">Todavía no conoce a nadie.</div>'; return; }
  g.innerHTML='';
  r.personas.forEach(p => {
    const d=document.createElement('div'); d.className='ficha';
    d.innerHTML=`<b></b><small></small><span class="sello ${p.cara?'':'no'}">${p.cara?'la reconoce':'sin foto'}</span>`;
    d.querySelector('b').textContent=p.nombre;
    d.querySelector('small').textContent=p.relacion||'sin parentesco';
    g.appendChild(d);
  });
}
$('#btn-cara').onclick = async () => {
  const nombre=$('#nom').value.trim(), relacion=$('#rel').value.trim();
  if (!nombre){ avisar('#aviso-cara','Escribí primero el nombre.'); return; }
  const r = await (await fetch('/api/cara',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({nombre,relacion})})).json();
  avisar('#aviso-cara', r.ok ? `Listo. Dante ya reconoce a ${nombre}.` : 'No pude: '+r.motivo);
  if (r.ok){ $('#nom').value=''; $('#rel').value=''; cargarGente(); }
};

/* ---------- señales ---------- */
async function cargarSenales(){
  const c = $('#senales'), r = await (await fetch('/api/senales')).json();
  $('#n-sen').textContent = r.senales.length ? r.senales.length+' cosas' : '';
  if (!r.senales.length){ c.innerHTML='<div class="pad ayuda">Sin novedades. Eso es buena señal.</div>'; return; }
  c.innerHTML='';
  r.senales.forEach(s => {
    const d=document.createElement('div');
    d.className='senal'+(s.veces>=3?' mucho':'');
    d.innerHTML=`<div class="veces">${s.veces}</div><div style="flex:1">
      <b></b><span class="cuando"></span><p></p></div>`;
    d.querySelector('b').textContent = s.que;
    d.querySelector('.cuando').textContent = 'la última vez el '+s.ultima;
    d.querySelector('p').textContent = s.ejemplos.map(e=>'"'+e+'"').join('  ·  ');
    c.appendChild(d);
  });
}

/* ---------- mensajes de voz ---------- */
let grabandoVoz=false, trozos=[], desde=0, cronometro;
const btnGrabar=$('#grabar');
async function grabarSi(){
  const de=$('#de').value.trim();
  if (!de){ avisar('#aviso-voz','Escribí primero de parte de quién es.'); return; }
  if (!await abrirMicro()) return;
  trozos=[]; grabandoVoz=true; desde=Date.now();
  btnGrabar.classList.add('grabando'); btnGrabar.textContent='🔴 Grabando… soltá al terminar';
  cronometro=setInterval(()=>{ const s=(Date.now()-desde)/1000;
    $('#tiempo').textContent=s.toFixed(1)+' s';
    if (s>60) grabarNo(); }, 100);
}
async function grabarNo(){
  if (!grabandoVoz) return;
  grabandoVoz=false; clearInterval(cronometro);
  btnGrabar.classList.remove('grabando'); btnGrabar.textContent='🔴 Mantené para grabar';
  const total=trozos.reduce((a,t)=>a+t.length,0);
  if (total < 12000){ $('#tiempo').textContent='hasta 60 segundos';
    avisar('#aviso-voz','Muy corto. Mantené apretado mientras hablás.'); return; }
  const todo=new Int16Array(total); let o=0;
  for (const t of trozos){ todo.set(t,o); o+=t.length; }
  $('#tiempo').textContent='enviando…';
  const r = await (await fetch('/api/mensaje?de='+encodeURIComponent($('#de').value.trim()),
    {method:'POST',headers:{'Content-Type':'application/octet-stream'},body:todo.buffer})).json();
  $('#tiempo').textContent='hasta 60 segundos';
  avisar('#aviso-voz', r.ok ? `Listo, ${r.segundos}s. Dante se lo va a reproducir.` : 'No pude: '+r.motivo);
  if (r.ok) cargarVoces();
}
btnGrabar.addEventListener('mousedown', grabarSi);
btnGrabar.addEventListener('touchstart', e=>{e.preventDefault();grabarSi();});
addEventListener('mouseup', grabarNo); addEventListener('touchend', grabarNo);

async function cargarVoces(){
  const c=$('#voces'), r=await (await fetch('/api/mensajes')).json();
  const sin = r.mensajes.filter(m=>!m.escuchado).length;
  $('#n-voz').textContent = sin ? sin+' sin escuchar' : '';
  if (!r.mensajes.length){ c.innerHTML='<div class="pad ayuda">Todavía no hay ninguno.</div>'; return; }
  c.innerHTML='';
  r.mensajes.forEach(m => {
    const d=document.createElement('div'); d.className='mensaje';
    d.innerHTML=`<div class="burbuja"></div><div style="flex:1"><b></b><small></small></div>`;
    d.querySelector('.burbuja').textContent = (m.de||'?')[0].toUpperCase();
    d.querySelector('b').textContent = m.de;
    d.querySelector('small').textContent =
      (m.transcripcion || `${(m.segundos||0).toFixed(1)} segundos`) +
      (m.escuchado ? ' · ya lo escuchó' : '');
    if (!m.escuchado){ const n=document.createElement('span');
      n.className='nuevo'; n.textContent='sin oír'; d.appendChild(n); }
    c.appendChild(d);
  });
}
</script></body></html>"""


def crear_app(sesion, bucle):
    """Arma la aplicacion web sobre una sesion que ya esta corriendo."""
    app = FastAPI(title="Dante")
    clientes: set = set()

    @app.middleware("http")
    async def puerta(peticion, siguiente):
        """Si Auth0 esta configurado, todo pasa por el login menos el propio
        login. Si no lo esta, esto no hace nada."""
        ruta = peticion.url.path
        if not auth.activo() or ruta in ("/login", "/callback", "/salir"):
            return await siguiente(peticion)
        if auth.usuario_de(peticion):
            return await siguiente(peticion)
        return RedirectResponse("/login")

    def _raiz(peticion: Request) -> str:
        """De donde cree el portal que cuelga.

        Detras de un tunel, peticion.base_url dice localhost, que es donde
        escucha uvicorn y no donde entra la gente. Auth0 compara la direccion
        de vuelta caracter por caracter, asi que si no coincide el login falla
        entero. Por eso DANTE_PANEL_URL manda cuando esta puesta.
        """
        return config.PANEL_URL or str(peticion.base_url).rstrip("/")

    @app.get("/login")
    def login(peticion: Request):
        if not auth.activo():
            return RedirectResponse("/")
        e = auth.nuevo_estado()
        return RedirectResponse(auth.url_de_login(_raiz(peticion) + "/callback", e))

    @app.get("/callback")
    def callback(peticion: Request, code: str = "", state: str = ""):
        if not auth.gastar_estado(state):
            return HTMLResponse(
                "<p>El enlace de entrada vencio o ya se uso. "
                "<a href='/login'>Vuelve a entrar</a>.</p>", 400)
        u = auth.canjear(code, _raiz(peticion) + "/callback")
        if not u:
            return HTMLResponse("<p>No pude verificar tu cuenta.</p>", 400)
        if u.get("rechazado"):
            return HTMLResponse(
                f"<p>La cuenta {u['rechazado']} no esta autorizada para este "
                f"agente.</p>", 403)
        r = RedirectResponse("/")
        # secure solo fuera de localhost: en http://127.0.0.1 el navegador
        # descartaria una galletita marcada como segura.
        local = (not config.PANEL_URL
                 and peticion.url.hostname in ("127.0.0.1", "localhost"))
        r.set_cookie(auth.COOKIE, auth.galleta_de(u), httponly=True,
                     samesite="lax", secure=not local, max_age=auth.DURACION)
        return r

    @app.get("/salir")
    def salir(peticion: Request):
        r = RedirectResponse(auth.url_de_salida(_raiz(peticion) + "/")
                             if auth.activo() else "/")
        r.delete_cookie(auth.COOKIE)
        return r

    @app.get("/api/quien_soy")
    def quien_soy(peticion: Request):
        u = auth.usuario_de(peticion) or {}
        return {"auth": auth.activo(), "usuario": u}

    def repartir(ev: dict) -> None:
        """El bus de la sesion llama a esto desde su propio hilo."""
        texto = json.dumps(ev, ensure_ascii=False)
        for ws in list(clientes):
            try:
                asyncio.run_coroutine_threadsafe(ws.send_text(texto), bucle)
            except Exception:
                pass

    sesion.oyentes.append(repartir)

    def repartir_audio(pcm: bytes) -> None:
        for ws in list(clientes):
            try:
                asyncio.run_coroutine_threadsafe(ws.send_bytes(pcm), bucle)
            except Exception:
                pass

    sesion.oyentes_audio.append(repartir_audio)

    @app.get("/", response_class=HTMLResponse)
    def inicio():
        return PAGINA

    # ------------------------------------------------------------- API ----
    @app.get("/api/ajustes")
    def ver_ajustes():
        c = memoria.abrir()
        try:
            return ajustes.resumen(c)
        finally:
            c.close()

    @app.post("/api/ajustes")
    async def poner_ajustes(datos: dict):
        c = memoria.abrir()
        try:
            nuevos = ajustes.guardar(c, datos)
        finally:
            c.close()
        # La sesion en curso ya tiene sus instrucciones cargadas; se las
        # cambiamos en caliente para no tener que reiniciar nada.
        try:
            asyncio.run_coroutine_threadsafe(sesion.configurar(), sesion.bucle)
        except Exception as e:
            # Si esto falla, lo guardado no llega a la conversacion en curso y
            # Dante sigue con las instrucciones viejas. Callarlo hace parecer
            # que el portal no guarda, que es justo la pista equivocada.
            print(f"  aviso: guarde los ajustes pero no pude aplicarlos a la "
                  f"conversacion en curso ({e}). Reinicia para que tomen.")
        repartir({"t": "ajustes", "ajustes": nuevos})
        return {"ok": True, "ajustes": nuevos}

    @app.get("/api/personas")
    def ver_personas():
        c = memoria.abrir()
        try:
            filas = c.execute(
                "SELECT nombre, relacion, notas, ultima_visita, "
                "cara IS NOT NULL AS cara FROM personas ORDER BY nombre").fetchall()
            return {"personas": [dict(f) for f in filas]}
        finally:
            c.close()

    @app.post("/api/cara")
    async def registrar_cara(datos: dict):
        """Toma el cuadro de ahora mismo y lo asocia a un nombre."""
        nombre = (datos.get("nombre") or "").strip()
        if not nombre:
            return {"ok": False, "motivo": "falta el nombre"}
        if not sesion.ojos.activa:
            return {"ok": False, "motivo": sesion.ojos.motivo or "sin camara"}

        cuadro = sesion.ojos.camara.ultimo()
        if cuadro is None:
            return {"ok": False, "motivo": "la camara no esta dando imagen"}

        r = sesion.ojos.rostros.registrar(cuadro, nombre)
        if r.get("ok"):
            c = memoria.abrir()
            try:
                memoria.registrar_persona(c, nombre, (datos.get("relacion") or "").strip())
            finally:
                c.close()
            sesion.pantalla("Nueva cara", f"Ahora reconozco a {nombre}", 7)
            sesion.cara("atencion")
        return r

    @app.get("/api/senales")
    def ver_senales():
        c = memoria.abrir()
        try:
            return {"senales": memoria.senales_recientes(c, 7)}
        finally:
            c.close()

    @app.get("/api/mensajes")
    def ver_mensajes():
        c = memoria.abrir()
        try:
            filas = c.execute(
                "SELECT id, de, transcripcion, segundos, creado, escuchado "
                "FROM mensajes ORDER BY id DESC LIMIT 30").fetchall()
            return {"mensajes": [dict(f) for f in filas]}
        finally:
            c.close()

    @app.post("/api/mensaje")
    async def dejar_mensaje(peticion: Request, de: str = ""):
        """Recibe PCM16 crudo del navegador y lo guarda como mensaje de voz."""
        pcm = await peticion.body()
        if len(pcm) > 24000 * 2 * 90:          # tope de 90 segundos
            return {"ok": False, "motivo": "el mensaje es demasiado largo"}

        r = msg.guardar(de, pcm)
        if not r.get("ok"):
            return r

        # Transcribir despues de guardar: si falla, el audio ya esta a salvo.
        texto = msg.transcribir(pcm)
        if texto:
            c = memoria.abrir()
            try:
                c.execute("UPDATE mensajes SET transcripcion=? WHERE id=?",
                          (texto, r["id"]))
                c.commit()
            finally:
                c.close()
            r["transcripcion"] = texto

        # Que la sesion en curso se entere sin reiniciar.
        try:
            asyncio.run_coroutine_threadsafe(sesion.configurar(), sesion.bucle)
        except Exception as e:
            # Si esto falla, lo guardado no llega a la conversacion en curso y
            # Dante sigue con las instrucciones viejas. Callarlo hace parecer
            # que el portal no guarda, que es justo la pista equivocada.
            print(f"  aviso: guarde los ajustes pero no pude aplicarlos a la "
                  f"conversacion en curso ({e}). Reinicia para que tomen.")
        sesion.pantalla("Mensaje nuevo", f"{de} te dejo un mensaje", 8)
        repartir({"t": "mensaje_nuevo", "de": de})
        return r

    @app.get("/camara.mjpg")
    def camara():
        """Video con las caras marcadas. Reconoce cada medio segundo, no en
        cada cuadro: identificar cuesta y a 25 por segundo no aporta nada."""
        import cv2

        def cuadros():
            ultimo_analisis, caras = 0.0, []
            while True:
                if not sesion.ojos.activa:
                    time.sleep(0.4)
                    continue
                c = sesion.ojos.camara.ultimo()
                if c is None:
                    time.sleep(0.05)
                    continue

                ahora = time.time()
                if ahora - ultimo_analisis > 0.5:
                    ultimo_analisis = ahora
                    try:
                        caras = sesion.ojos.rostros.quien(c)
                        repartir({"t": "caras", "lista": [
                            {"nombre": x["nombre"], "certeza": x["certeza"]} for x in caras]})
                    except Exception:
                        caras = []

                for x in caras:
                    px, py, pw, ph = x["caja"]
                    color = (110, 230, 140) if x["nombre"] else (90, 170, 255)
                    cv2.rectangle(c, (px, py), (px + pw, py + ph), color, 2)
                    etiqueta = x["nombre"] or "sin registrar"
                    cv2.rectangle(c, (px, py - 26), (px + 11 * len(etiqueta), py), color, -1)
                    cv2.putText(c, etiqueta, (px + 4, py - 8),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (20, 25, 30), 2)

                ok, buf = cv2.imencode(".jpg", c, [int(cv2.IMWRITE_JPEG_QUALITY), 72])
                if ok:
                    yield (b"--x\r\nContent-Type: image/jpeg\r\n\r\n"
                           + buf.tobytes() + b"\r\n")
                time.sleep(0.04)

        return StreamingResponse(cuadros(),
                                 media_type="multipart/x-mixed-replace; boundary=x")

    @app.websocket("/ws")
    async def canal(ws: WebSocket):
        # En Starlette el middleware http NO corre para websockets, asi que la
        # puerta de arriba no cubre esta ruta. Sin esto, cualquiera que alcance
        # el puerto puede leer la conversacion, oir el audio y hablarle al
        # agente. Comprobado explotandolo.
        if auth.activo() and not auth.usuario_de(ws):
            await ws.close(1008, "sin sesion")
            return
        await ws.accept()
        clientes.add(ws)
        await ws.send_text(json.dumps({"t": "estado", "v": sesion.estado}))
        try:
            while True:
                m = await ws.receive()
                if "bytes" in m and m["bytes"]:
                    if len(m["bytes"]) > 64000:
                        continue          # un trozo de audio son 960 bytes
                    # Audio del navegador: mismo camino que el del aparato.
                    asyncio.run_coroutine_threadsafe(
                        sesion.audio_del_panel(m["bytes"]), sesion.bucle)
                elif "text" in m and m["text"]:
                    if len(m["text"]) > 8000:
                        continue
                    try:
                        d = json.loads(m["text"])
                    except ValueError:
                        continue
                    if not isinstance(d, dict):
                        continue
                    if d.get("t") == "texto":
                        asyncio.run_coroutine_threadsafe(
                            sesion.decir_texto(d.get("v", "")), sesion.bucle)
                    elif d.get("t") == "boton":
                        asyncio.run_coroutine_threadsafe(
                            sesion._boton(d.get("v") == "abajo"), sesion.bucle)
        except (WebSocketDisconnect, RuntimeError, KeyError):
            pass
        finally:
            clientes.discard(ws)

    return app


def arrancar(sesion, puerto: int = 8800) -> str:
    """Levanta el panel en un hilo aparte y devuelve la direccion."""
    import uvicorn

    bucle = asyncio.get_running_loop()
    sesion.bucle = bucle
    app = crear_app(sesion, bucle)

    cfg = uvicorn.Config(app, host=config.PANEL_HOST, port=puerto,
                         log_level="warning", access_log=False)
    servidor = uvicorn.Server(cfg)
    threading.Thread(target=servidor.run, daemon=True).start()

    if config.PANEL_URL:
        return config.PANEL_URL
    visible = "127.0.0.1" if config.PANEL_HOST in ("0.0.0.0", "") else config.PANEL_HOST
    return f"http://{visible}:{puerto}"
