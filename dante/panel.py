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

from . import ajustes, auth, config, memoria

PAGINA = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dante</title>
<style>
  :root{
    --fondo:#0d1116; --panel:#151b22; --linea:#232c36;
    --tinta:#e6edf3; --tinta2:#93a1ae; --acento:#4fc3f7; --calido:#ffb74d;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--fondo);color:var(--tinta);
       font:15px/1.55 ui-sans-serif,system-ui,"Segoe UI",sans-serif}
  header{display:flex;align-items:center;gap:14px;padding:14px 20px;
         border-bottom:1px solid var(--linea)}
  h1{margin:0;font-size:17px;letter-spacing:.2px}
  .estado{margin-left:auto;display:flex;align-items:center;gap:9px;
          font:500 12px ui-monospace,monospace;color:var(--tinta2);
          text-transform:uppercase;letter-spacing:.1em}
  .punto{width:9px;height:9px;border-radius:50%;background:var(--tinta2)}
  .punto.escuchando{background:#4ade80;box-shadow:0 0 10px #4ade80}
  .punto.pensando{background:var(--calido);box-shadow:0 0 10px var(--calido)}
  .punto.hablando{background:var(--acento);box-shadow:0 0 10px var(--acento)}
  main{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(320px,1fr);
       gap:16px;padding:16px;align-items:start}
  @media(max-width:900px){main{grid-template-columns:1fr}}
  .caja{background:var(--panel);border:1px solid var(--linea);border-radius:12px;
        overflow:hidden}
  .caja h2{margin:0;padding:11px 15px;font-size:12px;font-weight:600;
           text-transform:uppercase;letter-spacing:.11em;color:var(--tinta2);
           border-bottom:1px solid var(--linea)}
  #video{display:block;width:100%;background:#000;aspect-ratio:16/9;object-fit:contain}
  #caras{padding:10px 15px;font:12px ui-monospace,monospace;color:var(--tinta2);
         min-height:38px;display:flex;flex-wrap:wrap;gap:7px;align-items:center}
  .quien{background:#12301f;color:#6ee7a0;border:1px solid #1d5136;
         padding:2px 9px;border-radius:999px}
  .quien.desconocido{background:#31241a;color:var(--calido);border-color:#54401f}
  #charla{height:min(46vh,420px);overflow-y:auto;padding:14px 15px;
          display:flex;flex-direction:column;gap:10px}
  .msg{max-width:88%;padding:8px 13px;border-radius:12px;font-size:14px}
  .msg.usuario{align-self:flex-end;background:#1c3446;color:#dbeafe}
  .msg.dante{align-self:flex-start;background:#1b2129;border:1px solid var(--linea)}
  .msg.sistema{align-self:center;font:11px ui-monospace,monospace;
               color:var(--tinta2);background:none;padding:2px}
  .barra{display:flex;gap:9px;padding:12px 15px;border-top:1px solid var(--linea)}
  input[type=text]{flex:1;background:#0e141a;border:1px solid var(--linea);
        border-radius:9px;color:var(--tinta);padding:10px 13px;font-size:14px}
  input[type=text]:focus{outline:none;border-color:var(--acento)}
  button{background:#1e2933;color:var(--tinta);border:1px solid var(--linea);
         border-radius:9px;padding:10px 15px;font-size:14px;cursor:pointer}
  button:hover{border-color:var(--acento)}
  button.hablando{background:#2d5a3d;border-color:#4ade80;color:#dcfce7}
  #micro{min-width:150px;font-weight:600}
  .pista{padding:0 15px 12px;font-size:11px;color:var(--tinta2)}
  .tabs{display:flex;gap:4px;margin-left:18px}
  .tab{background:none;border:none;color:var(--tinta2);padding:7px 13px;
       border-radius:8px;font-size:13px}
  .tab:hover{color:var(--tinta);border:none;background:#1b222a}
  .tab.activo{background:#1c2b38;color:var(--acento)}
  .vista{display:none}
  .vista.activo{display:block}
  form.cfg{padding:16px;display:flex;flex-direction:column;gap:15px}
  label{display:flex;flex-direction:column;gap:6px;font-size:12px;
        color:var(--tinta2);text-transform:uppercase;letter-spacing:.08em}
  label input,label select,label textarea{background:#0e141a;
        border:1px solid var(--linea);border-radius:9px;color:var(--tinta);
        padding:10px 12px;font:14px inherit;text-transform:none;letter-spacing:0}
  label textarea{min-height:74px;resize:vertical;line-height:1.5}
  label input:focus,label select:focus,label textarea:focus{
        outline:none;border-color:var(--acento)}
  .dos{display:grid;grid-template-columns:1fr 1fr;gap:15px}
  @media(max-width:640px){.dos{grid-template-columns:1fr}}
  .guardar{background:#1d4d33;border-color:#2f7a52;color:#d6f5e3;font-weight:600}
  .aviso{padding:9px 15px;font-size:12px;border-radius:8px;margin:0 16px;
         background:#1a2a1f;color:#8fe0ac;display:none}
  .gente{padding:14px 16px;display:grid;
         grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px}
  .persona{background:#111820;border:1px solid var(--linea);border-radius:10px;
           padding:12px;display:flex;flex-direction:column;gap:5px}
  .persona b{font-size:14px}
  .persona small{color:var(--tinta2);font-size:11px}
  .chip{display:inline-block;font:10px ui-monospace,monospace;padding:2px 7px;
        border-radius:999px;background:#12301f;color:#6ee7a0;width:fit-content}
  .chip.no{background:#2a2118;color:var(--calido)}
  .registrar{padding:0 16px 16px;display:flex;gap:9px;flex-wrap:wrap}
  .registrar input{flex:1;min-width:160px;background:#0e141a;
        border:1px solid var(--linea);border-radius:9px;color:var(--tinta);
        padding:10px 12px;font-size:14px}
</style></head><body>
<header>
  <svg width="26" height="26" viewBox="0 0 26 26" fill="none">
    <ellipse cx="8.5" cy="13" rx="4" ry="5" fill="#4fc3f7"/>
    <ellipse cx="17.5" cy="13" rx="4" ry="5" fill="#4fc3f7"/>
  </svg>
  <h1 id="titulo">Dante</h1>
  <nav class="tabs">
    <button class="tab activo" data-vista="conversar">Conversacion</button>
    <button class="tab" data-vista="personas">Personas</button>
    <button class="tab" data-vista="ajustes">Configuracion</button>
  </nav>
  <div class="estado"><span class="punto" id="punto"></span><span id="etiqueta">conectando</span></div>
</header>

<main id="v-conversar" class="vista activo">
  <div>
    <div class="caja">
      <h2>Lo que ve Dante</h2>
      <img id="video" src="/camara.mjpg" alt="camara">
      <div id="caras">sin caras a la vista</div>
    </div>
  </div>

  <div class="caja">
    <h2>Conversacion</h2>
    <div id="charla"></div>
    <div class="barra">
      <input type="text" id="entrada" placeholder="Escribile a Dante..." autocomplete="off">
      <button id="enviar">Enviar</button>
    </div>
    <div class="barra" style="border-top:none;padding-top:0">
      <button id="micro">Mantener para hablar</button>
    </div>
    <div class="pista">Manten apretado el boton, o la barra espaciadora, para hablarle por el microfono del computador.</div>
  </div>
</main>

<main id="v-personas" class="vista" style="grid-template-columns:minmax(0,1fr)">
  <div class="caja">
    <h2>Quien esta enfrente ahora</h2>
    <img id="video2" src="/camara.mjpg" alt="camara">
    <div class="registrar">
      <input type="text" id="nom" placeholder="Nombre (ej: Ana)">
      <input type="text" id="rel" placeholder="Relacion (ej: hija)" style="max-width:180px">
      <button id="btn-cara" class="guardar">Registrar esta cara</button>
    </div>
    <div class="pista">Que quede una sola cara en el cuadro, de frente y con buena luz.
      Dante la va a reconocer la proxima vez y va a decir el nombre en voz alta.</div>
    <div class="aviso" id="aviso-cara"></div>
    <h2 style="border-top:1px solid var(--linea)">Personas registradas</h2>
    <div class="gente" id="gente">cargando...</div>
  </div>
</main>

<main id="v-ajustes" class="vista" style="grid-template-columns:minmax(0,1fr)">
  <div class="caja">
    <h2>Como es y como se comporta</h2>
    <div class="aviso" id="aviso-cfg">Guardado. Se aplica en la proxima conversacion.</div>
    <form class="cfg" id="cfg">
      <div class="dos">
        <label>Nombre del propietario
          <input name="nombre_usuario" placeholder="Rosa"></label>
        <label>Como tratarlo
          <select name="trato"><option value="tu">De tu</option>
            <option value="usted">De usted</option></select></label>
      </div>
      <div class="dos">
        <label>Nombre de la mascota
          <input name="nombre_mascota" placeholder="Dante"></label>
        <label>Que es
          <input name="especie" placeholder="perro"></label>
      </div>
      <div class="dos">
        <label>Voz
          <select name="voz">
            <option value="marin">marin</option><option value="cedar">cedar</option>
            <option value="alloy">alloy</option><option value="sage">sage</option>
            <option value="coral">coral</option></select></label>
        <label>Ciudad
          <input name="ciudad" placeholder="Bogota"></label>
      </div>
      <label>Como quieres que se comporte
        <textarea name="caracter" placeholder="Paciente. Si repite una pregunta, respondele igual de bien la segunda vez, sin hacerselo notar."></textarea></label>
      <label>Temas que le gusta conversar
        <textarea name="temas_queridos" placeholder="Su epoca de maestra, musica de los sesenta, sus nietos"></textarea></label>
      <label>Temas que es mejor no sacar
        <textarea name="temas_evitar" placeholder="La muerte de su esposo, a menos que ella lo saque"></textarea></label>
      <label>A quien avisar si algo preocupa
        <input name="contacto_familia" placeholder="ana@correo.com"></label>
      <button type="submit" class="guardar">Guardar configuracion</button>
    </form>
  </div>
</main>

<script>
const charla = document.getElementById('charla');
const punto = document.getElementById('punto');
const etiqueta = document.getElementById('etiqueta');
const caras = document.getElementById('caras');
const micro = document.getElementById('micro');
let ws, audioCtx, stream, nodo, hablando = false;

function linea(clase, texto){
  const d = document.createElement('div');
  d.className = 'msg ' + clase;
  d.textContent = texto;
  charla.appendChild(d);
  charla.scrollTop = charla.scrollHeight;
}

function conectar(){
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.binaryType = 'arraybuffer';
  ws.onopen = () => { etiqueta.textContent = 'listo'; };
  ws.onclose = () => { etiqueta.textContent = 'desconectado'; setTimeout(conectar, 1500); };
  ws.onmessage = (e) => {
    if (typeof e.data !== 'string') return;
    const m = JSON.parse(e.data);
    if (m.t === 'estado'){
      punto.className = 'punto ' + m.v;
      etiqueta.textContent = {idle:'listo', escuchando:'escuchando',
        pensando:'pensando', hablando:'hablando', feliz:'listo',
        atencion:'atento'}[m.v] || m.v;
    } else if (m.t === 'dijo'){
      linea(m.quien === 'dante' ? 'dante' : 'usuario', m.texto);
    } else if (m.t === 'herramienta'){
      linea('sistema', '· ' + m.nombre + ' ·');
    } else if (m.t === 'pantalla'){
      linea('sistema', m.titulo + ': ' + m.cuerpo);
    } else if (m.t === 'caras'){
      caras.innerHTML = '';
      if (!m.lista.length){ caras.textContent = 'sin caras a la vista'; return; }
      m.lista.forEach(c => {
        const s = document.createElement('span');
        s.className = 'quien' + (c.nombre ? '' : ' desconocido');
        s.textContent = c.nombre ? c.nombre : 'sin registrar';
        caras.appendChild(s);
      });
    }
  };
}
conectar();

document.getElementById('enviar').onclick = mandarTexto;
document.getElementById('entrada').onkeydown = (e) => { if (e.key === 'Enter') mandarTexto(); };
function mandarTexto(){
  const i = document.getElementById('entrada');
  if (!i.value.trim() || !ws || ws.readyState !== 1) return;
  ws.send(JSON.stringify({t:'texto', v:i.value}));
  i.value = '';
}

// --- microfono del navegador -> PCM16 a 24 kHz, el mismo formato de siempre ---
async function abrirMicro(){
  if (audioCtx) return true;
  try{
    audioCtx = new AudioContext({sampleRate: 24000});
    stream = await navigator.mediaDevices.getUserMedia({audio:{
      echoCancellation:true, noiseSuppression:true, autoGainControl:true}});
    const fuente = audioCtx.createMediaStreamSource(stream);
    nodo = audioCtx.createScriptProcessor(1024, 1, 1);
    nodo.onaudioprocess = (e) => {
      if (!hablando || !ws || ws.readyState !== 1) return;
      const f = e.inputBuffer.getChannelData(0);
      const pcm = new Int16Array(f.length);
      for (let i = 0; i < f.length; i++){
        const v = Math.max(-1, Math.min(1, f[i]));
        pcm[i] = v < 0 ? v * 0x8000 : v * 0x7fff;
      }
      ws.send(pcm.buffer);
    };
    fuente.connect(nodo);
    nodo.connect(audioCtx.destination);
    return true;
  }catch(err){
    linea('sistema', 'no pude abrir el microfono: ' + err.message);
    return false;
  }
}
async function empezar(){
  if (hablando) return;
  if (!await abrirMicro()) return;
  hablando = true;
  micro.classList.add('hablando');
  micro.textContent = 'Escuchando... suelta';
  ws.send(JSON.stringify({t:'boton', v:'abajo'}));
}
function terminar(){
  if (!hablando) return;
  hablando = false;
  micro.classList.remove('hablando');
  micro.textContent = 'Mantener para hablar';
  ws.send(JSON.stringify({t:'boton', v:'arriba'}));
}
// --- pestanas ---
document.querySelectorAll('.tab').forEach(b => b.onclick = () => {
  document.querySelectorAll('.tab').forEach(x => x.classList.remove('activo'));
  document.querySelectorAll('.vista').forEach(x => x.classList.remove('activo'));
  b.classList.add('activo');
  document.getElementById('v-' + b.dataset.vista).classList.add('activo');
  if (b.dataset.vista === 'personas') cargarGente();
});

// --- configuracion ---
const form = document.getElementById('cfg');
async function cargarCfg(){
  const a = await (await fetch('/api/ajustes')).json();
  for (const [k, v] of Object.entries(a.ajustes || {})){
    const el = form.elements[k]; if (el) el.value = v;
  }
  if (a.ajustes && a.ajustes.nombre_mascota)
    document.getElementById('titulo').textContent = a.ajustes.nombre_mascota;
}
cargarCfg();
form.onsubmit = async (e) => {
  e.preventDefault();
  const d = Object.fromEntries(new FormData(form).entries());
  await fetch('/api/ajustes', {method:'POST',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify(d)});
  const av = document.getElementById('aviso-cfg');
  av.style.display = 'block'; setTimeout(()=>av.style.display='none', 2600);
  if (d.nombre_mascota) document.getElementById('titulo').textContent = d.nombre_mascota;
};

// --- personas ---
async function cargarGente(){
  const g = document.getElementById('gente');
  const r = await (await fetch('/api/personas')).json();
  if (!r.personas.length){ g.textContent = 'Todavia no hay nadie registrado.'; return; }
  g.innerHTML = '';
  r.personas.forEach(p => {
    const d = document.createElement('div');
    d.className = 'persona';
    d.innerHTML = `<b></b><small></small>
      <span class="chip ${p.cara ? '' : 'no'}">${p.cara ? 'cara registrada' : 'sin cara'}</span>`;
    d.querySelector('b').textContent = p.nombre;
    d.querySelector('small').textContent = p.relacion || 'sin relacion';
    g.appendChild(d);
  });
}
document.getElementById('btn-cara').onclick = async () => {
  const nombre = document.getElementById('nom').value.trim();
  const relacion = document.getElementById('rel').value.trim();
  const av = document.getElementById('aviso-cara');
  if (!nombre){ av.textContent = 'Escribe primero el nombre.'; av.style.display='block'; return; }
  const r = await (await fetch('/api/cara', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({nombre, relacion})})).json();
  av.textContent = r.ok ? `Listo. ${nombre} quedo registrada.` : ('No pude: ' + r.motivo);
  av.style.display = 'block';
  setTimeout(()=>av.style.display='none', 4000);
  if (r.ok) cargarGente();
};

micro.addEventListener('mousedown', empezar);
micro.addEventListener('touchstart', (e)=>{e.preventDefault();empezar();});
window.addEventListener('mouseup', terminar);
window.addEventListener('touchend', terminar);
window.addEventListener('keydown', (e)=>{
  if (e.code === 'Space' && e.target.tagName !== 'INPUT'){ e.preventDefault(); empezar(); }});
window.addEventListener('keyup', (e)=>{ if (e.code === 'Space') terminar(); });
</script></body></html>"""


def crear_app(sesion, bucle):
    """Arma la aplicacion web sobre una sesion que ya esta corriendo."""
    app = FastAPI(title="Dante")
    clientes: set = set()
    estados: set = set()

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

    @app.get("/login")
    def login(peticion: Request):
        if not auth.activo():
            return RedirectResponse("/")
        e = auth.nuevo_estado()
        estados.add(e)
        volver = str(peticion.base_url).rstrip("/") + "/callback"
        return RedirectResponse(auth.url_de_login(volver, e))

    @app.get("/callback")
    def callback(peticion: Request, code: str = "", state: str = ""):
        if state not in estados:
            return HTMLResponse("<p>Estado invalido. Vuelve a entrar.</p>", 400)
        estados.discard(state)
        volver = str(peticion.base_url).rstrip("/") + "/callback"
        u = auth.canjear(code, volver)
        if not u:
            return HTMLResponse("<p>No pude verificar tu cuenta.</p>", 400)
        if u.get("rechazado"):
            return HTMLResponse(
                f"<p>La cuenta {u['rechazado']} no esta autorizada para este "
                f"agente.</p>", 403)
        r = RedirectResponse("/")
        r.set_cookie(auth.COOKIE, auth.galleta_de(u), httponly=True,
                     samesite="lax", max_age=auth.DURACION)
        return r

    @app.get("/salir")
    def salir(peticion: Request):
        r = RedirectResponse(auth.url_de_salida(str(peticion.base_url))
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
        except Exception:
            pass
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
        await ws.accept()
        clientes.add(ws)
        await ws.send_text(json.dumps({"t": "estado", "v": sesion.estado}))
        try:
            while True:
                m = await ws.receive()
                if "bytes" in m and m["bytes"]:
                    # Audio del navegador: mismo camino que el del aparato.
                    asyncio.run_coroutine_threadsafe(
                        sesion.audio_del_panel(m["bytes"]), sesion.bucle)
                elif "text" in m and m["text"]:
                    d = json.loads(m["text"])
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

    cfg = uvicorn.Config(app, host="127.0.0.1", port=puerto,
                         log_level="warning", access_log=False)
    servidor = uvicorn.Server(cfg)
    threading.Thread(target=servidor.run, daemon=True).start()
    return f"http://127.0.0.1:{puerto}"
