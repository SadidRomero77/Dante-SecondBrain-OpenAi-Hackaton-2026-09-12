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

import base64



import asyncio

import json

import threading

import time

from pathlib import Path



from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect

from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse



from . import ajustes, auth, config, demo, memoria, mensajes as msg
from .favicon_b64 import B64 as FAVICON_B64



PAGINA = """<!doctype html>

<html lang="es"><head><meta charset="utf-8">

<meta name="viewport" content="width=device-width, initial-scale=1">

<title>Kibo</title>

<link rel="icon" type="image/png" href="data:image/png;base64,@@FAVICON@@">
<link rel="icon" type="image/x-icon" href="/favicon.ico">

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

@media (prefers-color-scheme:dark){:root[data-theme="dark"]{

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

.marca-kibo{display:flex;flex-direction:column;justify-content:center;gap:1px;min-width:0}

.kibo-word{display:flex;align-items:center;font:800 32px/1 Nunito,sans-serif;letter-spacing:-.04em}

.kibo-k{position:relative;color:#ee9c2a;padding-left:14px}

.kibo-ib{color:#4a2c1a}

.kibo-o{width:24px;height:24px;margin-left:2px;flex:none}

.kibo-o svg{display:block;width:100%;height:100%}

.kibo-raya{position:absolute;background:#ee9c2a;border-radius:99px}

.kibo-raya.a{width:11px;height:5px;left:0;top:2px;transform:rotate(-38deg)}

.kibo-raya.b{width:9px;height:4.5px;left:-2px;top:12px;transform:rotate(-52deg)}

.lema{margin:0;padding-left:14px;font-size:12.5px;font-weight:700;color:#5c3d28;letter-spacing:.01em}

.tabs{margin-left:auto;display:flex;gap:4px;flex-wrap:wrap}

.tab{background:none;border:none;color:var(--tinta2);padding:9px 15px;

  border-radius:11px;font:600 14px Nunito,sans-serif;cursor:pointer;

  transition:all .15s}

.tab:hover{background:var(--hueso);color:var(--tinta)}

.tab.on{background:var(--miel-suave);color:var(--miel)}



/* ====================== que se note que es un perro ======================

   Huellas, huesos y una cola. Suena a adorno y no lo es: quien abre esto es

   una familia que le confio a su madre a un muneco, no un operador mirando

   un tablero. Si la pantalla no tiene nada de perro, el perro no existe.

   Todo esto se apaga entero con prefers-reduced-motion. */



/* huellitas de fondo, casi invisibles: se ven si las buscas */

body{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120' viewBox='0 0 120 120'%3E%3Cg fill='%23b99a72' fill-opacity='.055'%3E%3Cellipse cx='28' cy='36' rx='6.5' ry='8.5'/%3E%3Cellipse cx='16' cy='22' rx='3.6' ry='4.6'/%3E%3Cellipse cx='27' cy='16' rx='3.6' ry='4.6'/%3E%3Cellipse cx='38' cy='22' rx='3.6' ry='4.6'/%3E%3Cellipse cx='88' cy='96' rx='6.5' ry='8.5'/%3E%3Cellipse cx='76' cy='82' rx='3.6' ry='4.6'/%3E%3Cellipse cx='87' cy='76' rx='3.6' ry='4.6'/%3E%3Cellipse cx='98' cy='82' rx='3.6' ry='4.6'/%3E%3C/g%3E%3C/svg%3E");

  background-attachment:fixed}



/* la cola, detras de la carita */

.perro{position:relative;display:flex;align-items:center;flex:none}

.cola{display:none}

@keyframes menear{0%,100%{transform:rotate(-16deg)}50%{transform:rotate(16deg)}}

.cola{animation:menear 1.1s ease-in-out infinite}

.contento .cola{animation-duration:.3s}

.dormido .cola{animation:none;transform:rotate(6deg)}



/* un huesito antes de cada titulo */

.caja h2::before{content:"";display:inline-block;width:17px;height:9px;

  margin-right:9px;vertical-align:-1px;opacity:.65;

  background:currentColor;

  -webkit-mask:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 34 18'%3E%3Cpath d='M7 4a4 4 0 1 0-.6 6.2A4 4 0 1 0 9.4 13h15.2A4 4 0 1 0 27 10.2 4 4 0 1 0 24.6 4H9.4A4 4 0 0 0 7 4z'/%3E%3C/svg%3E") center/contain no-repeat;

  mask:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 34 18'%3E%3Cpath d='M7 4a4 4 0 1 0-.6 6.2A4 4 0 1 0 9.4 13h15.2A4 4 0 1 0 27 10.2 4 4 0 1 0 24.6 4H9.4A4 4 0 0 0 7 4z'/%3E%3C/svg%3E") center/contain no-repeat}



/* el boton principal saca una huella al pasar por encima */

.pri{position:relative;overflow:hidden}

.pri::after{content:"🐾";position:absolute;right:11px;top:50%;

  transform:translateY(-50%) scale(.6);opacity:0;transition:all .22s}

.pri:hover::after{opacity:.5;transform:translateY(-50%) scale(1)}



/* estado vacio: un hueso grande y triste en vez de una linea de texto */

.ayuda.vacio{text-align:center;padding:26px 16px}

.ayuda.vacio::before{content:"🦴";display:block;font-size:34px;opacity:.45;

  margin-bottom:8px;animation:respirar 2.6s ease-in-out infinite}



/* cargando: un huesito que rebota */

@keyframes rebotar{0%,100%{transform:translateY(0) rotate(-8deg)}

  50%{transform:translateY(-9px) rotate(8deg)}}

.cargando::before{content:"🦴";display:inline-block;margin-right:8px;

  animation:rebotar .62s ease-in-out infinite}



/* al guardar algo, una huella cruza el aviso */

@keyframes pasar{from{transform:translateX(-14px);opacity:0}

  40%{opacity:.85} to{transform:translateX(0);opacity:.85}}

.aviso::before{content:"🐾";margin-right:8px;display:inline-block;

  animation:pasar .45s ease-out}



@media(prefers-reduced-motion:reduce){

  .cola,.ayuda.vacio::before,.cargando::before,.aviso::before{animation:none}}



/* la carita respira: quieta parece apagada, y esto no es un panel de control */

@keyframes respirar{0%,100%{transform:translateY(0)}50%{transform:translateY(-2px)}}

.carita{animation:respirar 3.4s ease-in-out infinite}

@media(prefers-reduced-motion:reduce){.carita{animation:none}}



/* ---------- el pulso de hoy ---------- */

.pulso{display:grid;grid-template-columns:repeat(auto-fit,minmax(132px,1fr));

  gap:10px;margin-bottom:16px}

.dato{background:var(--tarjeta);border:1px solid var(--borde);border-radius:14px;

  padding:13px 15px;box-shadow:var(--sombra);transition:transform .18s,border-color .18s}

.dato:hover{transform:translateY(-2px);border-color:var(--miel)}

.dato b{display:block;font-size:25px;font-weight:800;line-height:1.15;

  letter-spacing:-.02em;font-variant-numeric:tabular-nums}

.dato span{font-size:12px;color:var(--tinta2);font-weight:700;

  text-transform:uppercase;letter-spacing:.05em}

.dato.hay b{color:var(--miel)}

.hoy-lista{display:flex;flex-wrap:wrap;gap:7px;margin-top:9px}

.pastilla{background:var(--miel-suave);color:var(--miel);border-radius:999px;

  padding:5px 13px;font-size:13px;font-weight:700}



/* ---------- estructura ---------- */

main{display:none;max-width:1180px;margin:0 auto;padding:20px}

main.on{display:block}

.cols{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(340px,1fr);gap:18px;

  align-items:start}

@media(max-width:920px){.cols{grid-template-columns:1fr}}

.ficha{transition:transform .18s,box-shadow .18s}

.ficha:hover{transform:translateX(3px)}

.tab{position:relative}

.tab.on::after{content:"";position:absolute;left:50%;bottom:2px;width:16px;

  height:2px;border-radius:2px;background:var(--miel);transform:translateX(-50%)}

main.on{animation:entrar .22s ease-out}

@keyframes entrar{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:none}}

@media(prefers-reduced-motion:reduce){main.on{animation:none}}

.editando{background:var(--miel-suave);border-radius:12px;padding:11px}

.editando input,.editando select{margin:3px 0}

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



/* ---------- pase visual: companero, no tablero ---------- */

body{min-height:100vh;background-color:var(--fondo);

  background-image:

    radial-gradient(circle at 8% 0%,rgba(232,149,47,.13),transparent 30rem),

    radial-gradient(circle at 92% 12%,rgba(63,156,115,.10),transparent 27rem),

    url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120' viewBox='0 0 120 120'%3E%3Cg fill='%23b99a72' fill-opacity='.045'%3E%3Cellipse cx='28' cy='36' rx='6.5' ry='8.5'/%3E%3Cellipse cx='16' cy='22' rx='3.6' ry='4.6'/%3E%3Cellipse cx='27' cy='16' rx='3.6' ry='4.6'/%3E%3Cellipse cx='38' cy='22' rx='3.6' ry='4.6'/%3E%3C/g%3E%3C/svg%3E");

  background-attachment:fixed}

header{padding:18px clamp(16px,4vw,48px);gap:14px;

  background:rgba(255,253,250,.88);border-bottom:1px solid rgba(233,222,208,.85);

  box-shadow:0 8px 28px rgba(91,70,54,.08);backdrop-filter:blur(16px)}

.perro{padding-left:0}

.carita{width:72px;height:52px;border-radius:18px;box-shadow:0 9px 20px rgba(91,70,54,.2)}

.kibo-word{font-size:34px}

.kibo-o{width:26px;height:26px}

.lema{font-size:13px}

.tabs{gap:6px;align-items:center}

.tab{padding:10px 14px;border:1px solid transparent;font-size:13px}

.tab:hover{transform:translateY(-1px);box-shadow:0 5px 12px rgba(91,70,54,.08)}

.tab.on{background:var(--miel-suave);border-color:rgba(232,149,47,.22);box-shadow:0 5px 14px rgba(232,149,47,.12)}

main{max-width:1240px;padding:28px clamp(16px,4vw,48px) 48px}

.pulso{gap:14px;margin-bottom:22px}

.dato{min-height:92px;padding:17px 18px;border-radius:18px;background:rgba(255,253,250,.9);

  box-shadow:0 10px 28px -19px rgba(91,70,54,.48)}

.dato b{font-size:29px;color:var(--hocico)}

.dato span{font-size:11px;letter-spacing:.08em}

.dato.hay b{color:var(--miel)}

.cols{grid-template-columns:minmax(0,1.02fr) minmax(360px,.98fr);gap:22px}

.caja{border-radius:22px;border-color:rgba(233,222,208,.9);box-shadow:0 18px 38px -26px rgba(91,70,54,.45)}

.caja h2{padding:18px 22px;font-size:16px;background:linear-gradient(90deg,rgba(242,233,221,.48),transparent)}

.caja h2::before{width:19px;height:10px;opacity:.82}

#video,#video2{background:linear-gradient(145deg,#2a211a,#120e0a);border-bottom:1px solid var(--borde)}

#caras{padding:13px 22px;min-height:50px;background:rgba(242,233,221,.32)}

#charla{height:min(48vh,470px);padding:22px;gap:14px;background:rgba(255,253,250,.38)}

.msg{padding:12px 17px;border-radius:20px;box-shadow:0 5px 14px rgba(91,70,54,.06)}

.msg.yo{background:linear-gradient(135deg,var(--paseo),#328762)}

.msg.el{background:var(--hueso);border:1px solid rgba(233,222,208,.7)}

.barra{padding:14px 22px;background:rgba(255,253,250,.45)}

input[type=text],select,textarea{background:rgba(250,246,240,.72);border-color:rgba(233,222,208,.95);box-shadow:inset 0 1px 2px rgba(91,70,54,.035)}

input[type=text]:focus,select:focus,textarea:focus{border-color:var(--miel);box-shadow:0 0 0 4px rgba(232,149,47,.13)}

.carita{background:transparent;box-shadow:none;overflow:visible;position:relative}

.carita svg{width:78px;height:60px;overflow:visible;filter:drop-shadow(0 8px 7px rgba(91,70,54,.18))}

.oreja{transform-box:fill-box;transform-origin:center bottom;animation:orejear 3.8s ease-in-out infinite}

.oreja.der{animation-delay:.18s}

@keyframes orejear{0%,100%{transform:rotate(0deg)}50%{transform:rotate(3deg)}}

.contento .oreja{animation-duration:.55s}

.dormido .oreja{animation:none;transform:rotate(-5deg)}

.ojo{filter:drop-shadow(0 2px 2px rgba(51,40,31,.18))}

.pupila{transition:transform .25s ease,opacity .25s ease}

.contento .pupila{transform:translateY(-1px)}

.dormido .pupila{opacity:0}

input:not([type]),input[type=text],input[type=email],input[type=date],input[type=time],select,textarea{

  width:100%;min-width:0;min-height:48px;padding:12px 15px;border:1.5px solid rgba(233,222,208,.95);

  border-radius:14px;background:rgba(250,246,240,.78);color:var(--tinta);

  font:400 15px Nunito,sans-serif;box-shadow:inset 0 1px 2px rgba(91,70,54,.035);

  transition:border-color .18s,box-shadow .18s,background .18s}

input:not([type]):hover,input[type=text]:hover,input[type=email]:hover,input[type=date]:hover,input[type=time]:hover,select:hover,textarea:hover{background:var(--tarjeta);border-color:#d9c7b4}

input:not([type]):focus,input[type=text]:focus,input[type=email]:focus,input[type=date]:focus,input[type=time]:focus,select:focus,textarea:focus{

  outline:none;border-color:var(--miel);background:var(--tarjeta);box-shadow:0 0 0 4px rgba(232,149,47,.13)}

input::placeholder,textarea::placeholder{color:#ad9a87;opacity:1}

select{appearance:none;padding-right:42px;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 14 14'%3E%3Cpath d='m3 5 4 4 4-4' fill='none' stroke='%237d6b58' stroke-width='1.7' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 15px center}

input[type=date],input[type=time]{color-scheme:light}

label{gap:8px}

.dos>label{min-width:0}

button{box-shadow:0 5px 12px rgba(91,70,54,.07)}

button:hover{filter:none;transform:translateY(-1px);box-shadow:0 8px 16px rgba(91,70,54,.12)}

button:active{transform:translateY(0) scale(.98)}

.pri{background:linear-gradient(135deg,#eea13b,var(--miel));box-shadow:0 9px 18px rgba(232,149,47,.23)}

.ok{background:linear-gradient(135deg,#4ba97f,var(--paseo));box-shadow:0 9px 18px rgba(63,156,115,.2)}

.grande{min-height:52px}

.ficha{border:1px solid rgba(233,222,208,.8);box-shadow:0 8px 18px -16px rgba(91,70,54,.65)}

.ficha:hover{transform:translateY(-2px);box-shadow:0 12px 22px -15px rgba(91,70,54,.55)}

.aviso{box-shadow:0 7px 16px rgba(63,156,115,.08)}

@media(max-width:920px){

  header{flex-wrap:wrap}

  .tabs{order:3;width:100%;margin-left:0;overflow-x:auto;flex-wrap:nowrap;padding:3px 0 1px;scrollbar-width:none}

  .tabs::-webkit-scrollbar{display:none}

  .tab{flex:0 0 auto}

  main{padding-top:20px}

  .cols{grid-template-columns:1fr}

}

@media(max-width:560px){

  header{padding:14px 14px 10px;gap:11px}

  .carita{width:58px;height:44px;border-radius:15px}

  .carita svg{transform:scale(.84)}

  .kibo-word{font-size:26px}

  .kibo-o{width:20px;height:20px}

  .lema{font-size:11.5px}

  main{padding:14px 12px 34px}

  .pulso{grid-template-columns:repeat(2,minmax(0,1fr));gap:9px;margin-bottom:14px}

  .dato{min-height:78px;padding:13px 14px;border-radius:15px}

  .dato b{font-size:24px}

  .dato span{font-size:10px}

  .caja{border-radius:18px}

  .caja h2{padding:15px 17px;font-size:14px}

  #charla{height:47vh;padding:16px}

  .barra{padding:12px 16px}

  .dos{gap:10px}

}

@media(prefers-reduced-motion:reduce){button:hover,.ficha:hover,.dato:hover{transform:none}}

    /* Avatar Esculpido de Dante */
    .dante-avatar-box {
      position: relative; width: 72px; height: 72px; display: flex;
      align-items: center; justify-content: center; flex: none; cursor: pointer;
      border-radius: 20px; overflow: hidden;
      background: radial-gradient(circle at 50% 35%, rgba(254, 215, 125, 0.22), transparent 70%);
      transition: transform .25s cubic-bezier(.34, 1.56, .64, 1), background .25s, box-shadow .25s;
      user-select: none;
    }
    .dante-avatar-box:hover {
      transform: scale(1.08);
      background: radial-gradient(circle at 50% 35%, rgba(254, 215, 125, 0.45), transparent 75%);
    }
    .dante-avatar-box:active { transform: scale(0.95); }

    .dante-avatar {
      /* La silueta y sus animaciones nunca se salen del espacio del avatar. */
      display: block; width: 100%; height: 100%; overflow: hidden;
      filter: drop-shadow(0 4px 8px rgba(80, 45, 10, 0.16));
    }

    /* Respiración y balanceo del cráneo esculpido */
    .cabeza-grupo {
      transform-origin: 80px 110px;
      transition: transform .32s cubic-bezier(.34, 1.4, .64, 1);
      animation: respirar-cabeza 3.6s ease-in-out infinite;
    }
    @keyframes respirar-cabeza {
      0%, 100% { transform: translateY(0) rotate(0deg); }
      50% { transform: translateY(-2.2px) rotate(0.4deg); }
    }

    /* Orejas: pivote en la sien, movimiento suave (sin rebote) */
    .oreja { transition: transform .35s ease-in-out; }
    .oreja-izq {
      transform-origin: 50px 50px;
      animation: oreja-izq-idle 5.2s ease-in-out infinite;
    }
    .oreja-der {
      transform-origin: 110px 50px;
      animation: oreja-der-idle 5.2s ease-in-out infinite .4s;
    }
    @keyframes oreja-izq-idle {
      0%, 100% { transform: rotate(0deg); }
      50% { transform: rotate(-2deg); }
    }
    @keyframes oreja-der-idle {
      0%, 100% { transform: rotate(0deg); }
      50% { transform: rotate(2deg); }
    }

    /* Mechón de pelo diminuto en la corona */
    .pelito-tuft {
      transform-origin: 80px 38px;
      animation: pelito-bounce 3.6s ease-in-out infinite;
    }
    @keyframes pelito-bounce {
      0%, 100% { transform: rotate(0deg); }
      50% { transform: rotate(-4deg); }
    }

    /* Medalla hueso en el collar */
    #medalla-hueso {
      transform-origin: 0px -5px;
      transition: transform .28s ease;
    }

    /* Movimiento de pupilas y cejas */
    .pupila { transition: transform .18s ease-out; }
    .ceja { transition: transform .28s ease; }

    /* Partículas de cariño (click) */
    .particula-amor {
      position: absolute; pointer-events: none; font-size: 20px;
      animation: subir-particula .85s ease-out forwards; z-index: 30;
    }
    @keyframes subir-particula {
      0% { opacity: 1; transform: translate(-50%, 0) scale(.6); }
      100% { opacity: 0; transform: translate(-50%, -46px) scale(1.3); }
    }

    /* ESTADOS DE EMOCIÓN */
    /* Escuchando: orejas alertas arriba, cabeza atenta adelante, ojos despiertos */
    .emocion-escuchando .cabeza-grupo { transform: translateY(-3px) scale(1.02); animation: none; }
    .emocion-escuchando .oreja-izq { transform: rotate(-9deg); animation: none; }
    .emocion-escuchando .oreja-der { transform: rotate(9deg); animation: none; }
    .emocion-escuchando .ceja-izq { transform: translateY(-3px); }
    .emocion-escuchando .ceja-der { transform: translateY(-3px); }

    /* Pensando: cabeza inclinada curiosa, oreja levantada, mirada arriba a un lado */
    .emocion-pensando .cabeza-grupo { transform: rotate(7.5deg) translateY(-1.5px); animation: none; }
    .emocion-pensando .oreja-izq { transform: rotate(-8deg); }
    .emocion-pensando .oreja-der { transform: rotate(4deg); }
    .emocion-pensando .ceja-izq { transform: translateY(-4px) rotate(-6deg); }
    .emocion-pensando .ceja-der { transform: translateY(1.5px) rotate(5deg); }
    .emocion-pensando .pupila { transform: translate(2.5px, -3.2px); }

    /* Hablando: boca abierta gesticulando, lengua viva, orejas acompasadas */
    .emocion-hablando #boca-cerrada { display: none; }
    .emocion-hablando #boca-abierta { display: block; }
    .emocion-hablando .lengua-animada { animation: lengua-hablar .26s ease-in-out infinite alternate; }
    @keyframes lengua-hablar {
      from { transform: translateY(0); }
      to { transform: translateY(-3.5px) scale(.94); }
    }
    .emocion-hablando .oreja-izq { animation: oreja-habla-izq .45s ease-in-out infinite alternate; }
    .emocion-hablando .oreja-der { animation: oreja-habla-der .45s ease-in-out infinite alternate; }
    @keyframes oreja-habla-izq { from { transform: rotate(0deg); } to { transform: rotate(-4deg); } }
    @keyframes oreja-habla-der { from { transform: rotate(0deg); } to { transform: rotate(4deg); } }

    /* Feliz: ojos en arco sonriente (^ ^), hocico abierto con lengua fuera, orejas revoloteando felices */
    .emocion-feliz .ojo-abierto { display: none !important; }
    .emocion-feliz .ojo-feliz { display: block !important; }
    .emocion-feliz #boca-cerrada { display: none; }
    .emocion-feliz #boca-abierta { display: block; }
    .emocion-feliz .cabeza-grupo { animation: saltito-feliz .48s ease-in-out infinite alternate; }
    @keyframes saltito-feliz {
      from { transform: translateY(0); }
      to { transform: translateY(-4px) scale(1.02); }
    }
    .emocion-feliz .oreja-izq { animation: oreja-feliz-izq .55s ease-in-out infinite alternate; }
    .emocion-feliz .oreja-der { animation: oreja-feliz-der .55s ease-in-out infinite alternate; }
    @keyframes oreja-feliz-izq { from { transform: rotate(-4deg); } to { transform: rotate(3deg); } }
    @keyframes oreja-feliz-der { from { transform: rotate(4deg); } to { transform: rotate(-3deg); } }
    .emocion-feliz #medalla-hueso { animation: medalla-campana .38s ease-in-out infinite alternate; }
    @keyframes medalla-campana { from { transform: rotate(-14deg); } to { transform: rotate(14deg); } }

    /* Atento / Alerta: ojos dilatados, postura erguida, cejas arriba */
    .emocion-atencion .cabeza-grupo { transform: translateY(-4px) scale(1.04); }
    .emocion-atencion .oreja-izq { transform: rotate(-10deg); }
    .emocion-atencion .oreja-der { transform: rotate(10deg); }
    .emocion-atencion .ceja-izq, .emocion-atencion .ceja-der { transform: translateY(-3.5px); }

    /* Dormido: párpados cerrados, respiración lenta y tranquila, orejitas caídas */
    .emocion-dormido .parpado { transform: scaleY(1) !important; }
    .emocion-dormido .cabeza-grupo { transform: translateY(2.5px); animation: dormir-cabeza 4.8s ease-in-out infinite; }
    @keyframes dormir-cabeza { 0%, 100% { transform: translateY(2.5px); } 50% { transform: translateY(0.5px); } }
    .emocion-dormido .oreja-izq { transform: rotate(4deg); }
    .emocion-dormido .oreja-der { transform: rotate(-4deg); }
</style></head><body>



<header>
  <div class="dante-avatar-box" id="dante-avatar-box" title="Acariciá a Dante para ver su reacción alegre 🐾">
    <svg id="dante-svg" class="dante-avatar" viewBox="0 0 160 160" width="72" height="72" aria-label="Dante el perro compañero">
      <defs>
        <!-- Degradados cálidos y sombreados para las facetas poligonales del pelaje -->
        <linearGradient id="grad-frente" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stop-color="#fed77d"/>
          <stop offset="100%" stop-color="#f5b84e"/>
        </linearGradient>
        <linearGradient id="grad-mejilla-izq" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="#e38e24"/>
          <stop offset="100%" stop-color="#cb7414"/>
        </linearGradient>
        <linearGradient id="grad-mejilla-der" x1="100%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stop-color="#d67f1b"/>
          <stop offset="100%" stop-color="#be670c"/>
        </linearGradient>
        <linearGradient id="grad-hocico" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stop-color="#fff5e6"/>
          <stop offset="100%" stop-color="#f7ddba"/>
        </linearGradient>
        <linearGradient id="grad-oreja-izq" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="#e29427"/>
          <stop offset="100%" stop-color="#be670c"/>
        </linearGradient>
        <linearGradient id="grad-oreja-der" x1="100%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stop-color="#d6841e"/>
          <stop offset="100%" stop-color="#b15907"/>
        </linearGradient>
        <linearGradient id="grad-collar" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stop-color="#1b724e"/>
          <stop offset="50%" stop-color="#2ca16e"/>
          <stop offset="100%" stop-color="#165c3e"/>
        </linearGradient>
        <linearGradient id="grad-oro" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="#ffe678"/>
          <stop offset="50%" stop-color="#f8be22"/>
          <stop offset="100%" stop-color="#cf8904"/>
        </linearGradient>
        <radialGradient id="grad-ojo" cx="35%" cy="35%" r="65%">
          <stop offset="0%" stop-color="#4e3120"/>
          <stop offset="65%" stop-color="#24170f"/>
          <stop offset="100%" stop-color="#140c07"/>
        </radialGradient>
        <filter id="soft-shadow" x="-10%" y="-10%" width="120%" height="130%">
          <feDropShadow dx="0" dy="2" stdDeviation="2.2" flood-color="#552200" flood-opacity="0.16"/>
        </filter>
      </defs>

      <!-- BASE: cuello y collar a una distancia prudente, sin salirse del icono -->
      <g id="cuello-y-collar">
        <path d="M 62 116 L 58 132 Q 80 140 102 132 L 98 116 Z" fill="#dc851d"/>
        <path d="M 60 128 L 58 134 Q 80 140 102 134 L 100 128 Z" fill="#c97312"/>
        <path id="banda-collar" d="M 52 126 Q 80 138 108 126 L 106 136 Q 80 146 54 136 Z" fill="url(#grad-collar)" stroke="#134a33" stroke-width="1.1"/>
        <circle cx="64" cy="132" r="1.5" fill="#f8cf52"/>
        <circle cx="96" cy="132" r="1.5" fill="#f8cf52"/>
        <circle cx="80" cy="138" r="2.7" fill="none" stroke="#e8a817" stroke-width="1.45"/>
        <g id="medalla-hueso" transform="translate(80, 142)">
          <path d="M -5.4 -2.8 C -7.2 -4.7 -9.4 -2.2 -7.6 -0.6 C -9.4 1.1 -7.2 3.6 -5.4 1.8 L 5.4 1.8 C 7.2 3.6 9.4 1.1 7.6 -0.6 C 9.4 -2.2 7.2 -4.7 5.4 -2.8 Z" fill="url(#grad-oro)" stroke="#b57404" stroke-width="0.7"/>
          <circle cx="0" cy="-0.35" r="0.75" fill="#fff" opacity="0.85"/>
        </g>
      </g>

      <!-- CABEZA CON ESTRUCTURA BIEN MOLDEADA EN PLANOS POLIGONALES -->
      <g id="cabeza-grupo" class="cabeza-grupo">
        <!-- Orejas dentro de la cabeza para que se muevan con ella -->
        <g id="oreja-izq" class="oreja oreja-izq">
          <path d="M 46 48 C 26 46 10 66 14 92 C 17 104 31 101 39 85 C 45 74 51 59 51 49 Z" fill="#9e4e04"/>
          <path d="M 48 48 C 29 46 14 65 17 89 C 19 99 32 96 39 82 C 45 71 52 58 52 48 Z" fill="url(#grad-oreja-izq)"/>
          <path d="M 41 53 C 30 53 23 66 25 81 C 29 87 34 83 38 73 Z" fill="#883e02" opacity="0.75"/>
          <path d="M 44 49 C 32 49 22 62 23 75" fill="none" stroke="#fcd484" stroke-width="1.6" stroke-linecap="round" opacity="0.6"/>
        </g>
        <g id="oreja-der" class="oreja oreja-der">
          <path d="M 114 48 C 134 46 150 66 146 92 C 143 104 129 101 121 85 C 115 74 109 59 109 49 Z" fill="#924602"/>
          <path d="M 112 48 C 131 46 146 65 143 89 C 141 99 128 96 121 82 C 115 71 108 58 108 48 Z" fill="url(#grad-oreja-der)"/>
          <path d="M 119 53 C 130 53 137 66 135 81 C 131 87 126 83 122 73 Z" fill="#7d3701" opacity="0.75"/>
          <path d="M 116 49 C 128 49 138 62 137 75" fill="none" stroke="#fcd484" stroke-width="1.6" stroke-linecap="round" opacity="0.6"/>
        </g>
        <!-- Facetas geométricas / polígonos esculpidos de la cabeza -->
        <g id="poligonos-cabeza">
          <!-- 1. Plano Frente Superior / Corona -->
          <polygon points="62,38 98,38 104,54 56,54" fill="#fed679"/>

          <!-- 2. Plano Diamante Central de la Frente -->
          <polygon points="56,54 104,54 100,72 80,78 60,72" fill="#f8bf53"/>

          <!-- 3. Faceta Lateral Izquierda (Sien superior) -->
          <polygon points="62,38 56,54 44,52" fill="#e8982c"/>

          <!-- 4. Faceta Lateral Derecha (Sien superior) -->
          <polygon points="98,38 104,54 116,52" fill="#df8e22"/>

          <!-- 5. Mejilla Izquierda Superior (Polígono angular que ensancha la cara) -->
          <polygon points="44,52 56,54 60,72 40,78 34,64" fill="url(#grad-mejilla-izq)"/>

          <!-- 6. Mejilla Derecha Superior (Polígono angular simétrico) -->
          <polygon points="116,52 104,54 100,72 120,78 126,64" fill="url(#grad-mejilla-der)"/>

          <!-- 7. Mejilla Izquierda Inferior (Mandíbula) -->
          <polygon points="34,64 40,78 54,98 44,106 32,84" fill="#c97312"/>

          <!-- 8. Mejilla Derecha Inferior (Mandíbula) -->
          <polygon points="126,64 120,78 106,98 116,106 128,84" fill="#be670c"/>

          <!-- 9. Quijada y Barbilla (Planos inferiores) -->
          <polygon points="44,106 54,98 80,110 66,126 50,120" fill="#dc851d"/>
          <polygon points="116,106 106,98 80,110 94,126 110,120" fill="#ce7714"/>
          <polygon points="66,126 80,110 94,126 80,128" fill="#e8952b"/>

          <!-- Líneas de estructura sutiles entre facetas -->
          <path d="M 62 38 L 98 38 L 104 54 L 120 78 L 116 106 L 94 126 L 66 126 L 44 106 L 40 78 L 56 54 Z" fill="none" stroke="#ad5b07" stroke-width="1.2" opacity="0.32"/>
        </g>

        <!-- PELITO DIMINUTO EN LA CORONA (Para que no se vea calvo) -->
        <g id="pelito-cabeza" class="pelito-tuft">
          <path d="M 76 38 C 77 30 79 25 82 26 C 84 27 83 33 85 38 C 87 31 91 30 90 38 Z" fill="#fed679" stroke="#ad5b07" stroke-width="1" stroke-linejoin="round"/>
          <path d="M 79 34 C 80 29 81 28 82 28" fill="none" stroke="#fff1bd" stroke-width="1.2" stroke-linecap="round"/>
        </g>

        <!-- CEJAS EXPRESIVAS -->
        <g id="cejas">
          <path id="ceja-izq" class="ceja ceja-izq" d="M 48 50 Q 58 45 66 49" fill="none" stroke="#7a3f0f" stroke-width="3" stroke-linecap="round"/>
          <path id="ceja-der" class="ceja ceja-der" d="M 94 49 Q 102 45 112 50" fill="none" stroke="#7a3f0f" stroke-width="3" stroke-linecap="round"/>
        </g>

        <!-- OJOS (Animados con párpados, reflejos y estado feliz) -->
        <!-- Ojo Izquierdo -->
        <g id="ojo-izq-cont" class="ojo-contenedor" transform="translate(58, 63)">
          <g id="ojo-izq-abierto" class="ojo-abierto">
            <ellipse cx="0" cy="0" rx="10" ry="12" fill="#ffffff" stroke="#ecd7c4" stroke-width="0.8"/>
            <path d="M -9.5 -2 C -9 -9 9 -9 9.5 -2 C 6 -4 -6 -4 -9.5 -2 Z" fill="#d9c5b2" opacity="0.45"/>
            <g id="pupila-izq" class="pupila">
              <ellipse cx="0.5" cy="0.5" rx="7.5" ry="9" fill="url(#grad-ojo)"/>
              <circle cx="0.5" cy="0.5" r="7.5" fill="none" stroke="#a2571b" stroke-width="1"/>
              <circle cx="-2.5" cy="-3.5" r="3" fill="#ffffff"/>
              <circle cx="3" cy="3.5" r="1.3" fill="#ffffff" opacity="0.9"/>
            </g>
            <path id="parpado-izq" class="parpado" d="M -11 -13 L 11 -13 L 11 0 Q 0 4 -11 0 Z" fill="#e8982c" style="transform-origin: 0px -12px; transform: scaleY(0); transition: transform 0.12s ease;"/>
          </g>
          <path id="ojo-izq-feliz" class="ojo-feliz" d="M -9 3 Q 0 -8 9 3" fill="none" stroke="#2c1a0e" stroke-width="3.6" stroke-linecap="round" style="display: none;"/>
        </g>

        <!-- Ojo Derecho -->
        <g id="ojo-der-cont" class="ojo-contenedor" transform="translate(102, 63)">
          <g id="ojo-der-abierto" class="ojo-abierto">
            <ellipse cx="0" cy="0" rx="10" ry="12" fill="#ffffff" stroke="#ecd7c4" stroke-width="0.8"/>
            <path d="M -9.5 -2 C -9 -9 9 -9 9.5 -2 C 6 -4 -6 -4 -9.5 -2 Z" fill="#d9c5b2" opacity="0.45"/>
            <g id="pupila-der" class="pupila">
              <ellipse cx="-0.5" cy="0.5" rx="7.5" ry="9" fill="url(#grad-ojo)"/>
              <circle cx="-0.5" cy="0.5" r="7.5" fill="none" stroke="#a2571b" stroke-width="1"/>
              <circle cx="-3.5" cy="-3.5" r="3" fill="#ffffff"/>
              <circle cx="2" cy="3.5" r="1.3" fill="#ffffff" opacity="0.9"/>
            </g>
            <path id="parpado-der" class="parpado" d="M -11 -13 L 11 -13 L 11 0 Q 0 4 -11 0 Z" fill="#df8e22" style="transform-origin: 0px -12px; transform: scaleY(0); transition: transform 0.12s ease;"/>
          </g>
          <path id="ojo-der-feliz" class="ojo-feliz" d="M -9 3 Q 0 -8 9 3" fill="none" stroke="#2c1a0e" stroke-width="3.6" stroke-linecap="round" style="display: none;"/>
        </g>

        <!-- Mejillas con rubor sutil -->
        <ellipse cx="42" cy="79" rx="7" ry="4" fill="#f87a55" opacity="0.28"/>
        <ellipse cx="118" cy="79" rx="7" ry="4" fill="#f87a55" opacity="0.28"/>

        <!-- HOCICO (Estructura poligonal-redondeada con trufa, boca y lengua) -->
        <g id="hocico-grupo" class="hocico-grupo" filter="url(#soft-shadow)">
          <!-- Base crema del hocico -->
          <path d="M 64 74 C 70 71, 90 71, 96 74 C 105 78, 107 90, 103 99 C 97 108, 89 113, 80 113 C 71 113, 63 108, 57 99 C 53 90, 55 78, 64 74 Z" fill="url(#grad-hocico)" stroke="#e4cbab" stroke-width="1.2"/>
          <ellipse cx="80" cy="85" rx="14" ry="7" fill="#ebd2b2" opacity="0.5"/>

          <!-- Puntos de bigote caricaturizados -->
          <circle cx="68" cy="94" r="1" fill="#c49f76"/>
          <circle cx="72" cy="97" r="1" fill="#c49f76"/>
          <circle cx="88" cy="97" r="1" fill="#c49f76"/>
          <circle cx="92" cy="94" r="1" fill="#c49f76"/>

          <!-- Boca y lengua -->
          <g id="boca-grupo">
            <!-- Boca cerrada / sonrisa amigable -->
            <path id="boca-cerrada" d="M 69 98 Q 75 102 80 98 Q 85 102 91 98" fill="none" stroke="#52321c" stroke-width="2.2" stroke-linecap="round"/>

            <!-- Boca abierta con lengua alegre (en feliz o hablando) -->
            <g id="boca-abierta" style="display: none;">
              <path d="M 72 98 Q 80 99 88 98 Q 89 110 80 113 Q 71 110 72 98 Z" fill="#631722"/>
              <g id="lengua-animada" class="lengua-animada">
                <path d="M 73 104 Q 80 101 87 104 C 88 116 86 122 80 123 C 74 122 72 116 73 104 Z" fill="#f86284" stroke="#d43f62" stroke-width="0.8"/>
                <path d="M 80 106 L 80 118" fill="none" stroke="#de4366" stroke-width="1.2" stroke-linecap="round"/>
                <ellipse cx="77" cy="112" rx="1.8" ry="3" fill="#ff9cb4" opacity="0.65"/>
              </g>
            </g>
          </g>

          <!-- Trufa de la nariz -->
          <g id="trufa-nariz">
            <path d="M 72 79 C 75 76, 85 76, 88 79 C 90 82, 87 87, 80 89 C 73 87, 70 82, 72 79 Z" fill="#291b12" stroke="#1d120a" stroke-width="1"/>
            <ellipse cx="76" cy="83.5" rx="1.6" ry="1.2" fill="#150c06"/>
            <ellipse cx="84" cy="83.5" rx="1.6" ry="1.2" fill="#150c06"/>
            <ellipse cx="77.5" cy="80" rx="3.5" ry="1.5" fill="#ffffff" opacity="0.5" transform="rotate(-8, 77.5, 80)"/>
            <line x1="80" y1="89" x2="80" y2="98" stroke="#52321c" stroke-width="2.2" stroke-linecap="round"/>
          </g>
        </g>
      </g>
    </svg>
  </div>
  <div class="marca-kibo">
    <div class="kibo-word" aria-label="Kibo">
      <span class="kibo-k"><span class="kibo-raya a"></span><span class="kibo-raya b"></span>K</span><span class="kibo-ib">ib</span><span class="kibo-o">
        <svg viewBox="0 0 48 48" aria-hidden="true">
          <circle cx="24" cy="24" r="24" fill="#4a2c1a"/>
          <ellipse cx="24" cy="28" rx="7.2" ry="8.2" fill="#f0c45c"/>
          <circle cx="14.2" cy="19" r="4.1" fill="#f0c45c"/>
          <circle cx="23.2" cy="15.2" r="4.1" fill="#f0c45c"/>
          <circle cx="33.4" cy="19" r="4.1" fill="#f0c45c"/>
          <circle cx="35.2" cy="28.2" r="3.5" fill="#f0c45c"/>
        </svg>
      </span>
    </div>
    <p class="lema">Tu compañero. Tu memoria.</p>
  </div>

  <nav class="tabs">

    <button class="tab on" data-v="charla">Conversar</button>

    <button class="tab" data-v="gente">Personas</button>

    <button class="tab" data-v="voz">Mensajes</button>

    <button class="tab" data-v="agenda">Recordatorios</button>

    <button class="tab" data-v="senales">Cómo está</button>

    <button class="tab" data-v="cfg">Ajustes</button>

  </nav>

</header>



<!-- ============ CONVERSAR ============ -->

<main id="v-charla" class="on">

<div class="pulso" id="pulso"></div>

<div class="cols">

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

<main id="v-gente">

<div class="caja" style="margin-bottom:18px">

  <h2>Dónde quedaron las cosas <small id="n-obj"></small></h2>

  <div class="pad" style="padding-bottom:6px">

    <p class="ayuda">Lo que Dante tiene anotado. Si ella le dice dónde dejó

    algo, o si lo ve por la cámara, queda acá. Cuando pregunte «¿dónde están

    mis lentes?», responde con esto — y si no lo sabe, <b>lo dice</b> en vez

    de inventar un sitio.</p>

  </div>

  <div id="objetos"></div>

</div>

<div class="cols">

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



      <div style="display:flex;align-items:center;gap:10px;margin:18px 0 12px">

        <div style="flex:1;height:1px;background:var(--borde)"></div>

        <span class="ayuda" style="font-weight:700">o escribilo</span>

        <div style="flex:1;height:1px;background:var(--borde)"></div>

      </div>

      <p class="ayuda" style="margin-top:0">Si estás en el trabajo o no te

      sale grabarte, escribilo. Dante se lo lee con su voz. Un recado que

      llega vale más que uno hablado que nunca mandaste.</p>

      <textarea id="recado" placeholder="Mamá, mañana voy a las 4. No te preocupes por el almuerzo."></textarea>

      <button id="b-recado" class="pri" style="margin-top:8px">Dejar el recado</button>

    </div>

    <div class="aviso" id="aviso-voz"></div>

  </div>

  <div class="caja">

    <h2>Mensajes dejados <small id="n-voz"></small></h2>

    <div id="voces"><div class="pad ayuda vacio">Todavía no hay ninguno.</div></div>

  </div>

</div></main>



<!-- ============ SEÑALES ============ -->

<!-- ============ RECORDATORIOS ============ -->

<main id="v-agenda">

  <div class="caja" style="max-width:760px;margin:0 auto">

    <h2>Recordatorios y fechas 🐕</h2>

    <div class="aviso" id="aviso-ag">Anotado. Dante ya lo sabe.</div>

    <div class="pad" style="padding-bottom:6px">

      <p class="ayuda">Dante los dice <b>solo, cuando llega la hora</b> — nadie

      tiene que preguntarle. Y si ella pregunta «¿qué tengo hoy?», se los cuenta.</p>

    </div>

    <form class="pad" id="ag-nuevo">

      <label>¿Qué hay que recordar?

        <input name="que" placeholder="Pastilla azul de la presión" required></label>

      <div class="dos">

        <label>¿Cada cuánto?<select name="clase">

          <option value="diario">Todos los días</option>

          <option value="unico">Un día concreto</option>

          <option value="anual">Todos los años</option></select></label>

        <label>¿Qué es?<select name="tipo">

          <option value="medicacion">Medicamento</option>

          <option value="visita">Visita</option>

          <option value="cita">Cita</option>

          <option value="fecha">Fecha importante</option>

          <option value="otro">Otra cosa</option></select></label>

      </div>

      <div class="dos">

        <label id="l-fecha" style="display:none">¿Qué día?

          <input type="date" name="fecha"></label>

        <label>¿A qué hora?<input type="time" name="hora" value="09:00"></label>

      </div>

      <button type="submit" class="pri grande">Anotar</button>

    </form>

    <div id="agenda"></div>

  </div>

</main>



<main id="v-senales">

  <div class="caja" style="max-width:760px;margin:0 auto">

    <h2>Cómo estuvo esta semana <small id="n-sen"></small></h2>

    <div class="pad" style="padding-bottom:6px">

      <p class="ayuda">Cosas que mencionó en sus conversaciones. <b>Esto no es un diagnóstico</b> y Dante no interpreta nada: solo repite lo que ella dijo, y cuántas veces. Si algo se repite, quizás valga la pena preguntarle.</p>

    </div>

    <div id="senales"><div class="pad ayuda vacio">Sin novedades. Eso es buena señal.</div></div>

  </div>



  <div class="caja" style="max-width:760px;margin:18px auto 0">

    <h2>Qué cambió <small id="n-cam"></small></h2>

    <div class="pad" style="padding-bottom:6px">

      <p class="ayuda">Comparado con las semanas anteriores. <b>Dante no saca

      conclusiones</b>: te da el número para que decidas tú. Y se calla cuando

      no tiene suficiente con qué comparar.</p>

    </div>

    <div id="cambios"></div>

  </div>



  <div class="caja" style="max-width:760px;margin:18px auto 0">

    <h2>La nota para la familia</h2>

    <div class="pad">

      <p class="ayuda">Esto es lo que reciben sus hijos. Lo escribe Dante con

      lo de arriba, sin copiar sus conversaciones.</p>

      <button class="pri" id="b-resumen">Ver el de esta semana</button>

      <div id="resumen" style="margin-top:12px"></div>

    </div>

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
const charla = $('#charla');
const danteBox = $('#dante-avatar-box');
const parpadoIzq = $('#parpado-izq'), parpadoDer = $('#parpado-der');
const pupilaIzq = $('#pupila-izq'), pupilaDer = $('#pupila-der');
const bocaCerrada = $('#boca-cerrada'), bocaAbierta = $('#boca-abierta');

let ws, entra, sale, flujo, nodo, hablando = false, proximo = 0;
let altavozOn = localStorage.getItem('dante_altavoz') !== 'no';
let estadoActual = 'idle';
let parpadeando = false;

/* ---------- Nombres y descripciones de las emociones de Dante ---------- */
const NOMBRES_EMOCION = {
  idle:       'listo',
  escuchando: 'te escucha',
  pensando:   'pensando…',
  hablando:   'hablando',
  feliz:      'contento',
  atencion:   'atento',
  dormido:    'descansando'
};

function pintarCara(e) {
  estadoActual = e || 'idle';


  if (!danteBox) return;

  // Limpiar clases de emoción previas
  danteBox.classList.remove(
    'emocion-idle', 'emocion-escuchando', 'emocion-pensando',
    'emocion-hablando', 'emocion-feliz', 'emocion-atencion', 'emocion-dormido'
  );
  danteBox.classList.add('emocion-' + estadoActual);

  // Manejo de boca y ojos según emoción
  const ojoIzqAbierto = $('#ojo-izq-abierto');
  const ojoIzqFeliz = $('#ojo-izq-feliz');
  const ojoDerAbierto = $('#ojo-der-abierto');
  const ojoDerFeliz = $('#ojo-der-feliz');

  if (estadoActual === 'feliz') {
    if (ojoIzqAbierto) ojoIzqAbierto.style.display = 'none';
    if (ojoIzqFeliz) ojoIzqFeliz.style.display = 'block';
    if (ojoDerAbierto) ojoDerAbierto.style.display = 'none';
    if (ojoDerFeliz) ojoDerFeliz.style.display = 'block';
    if (bocaCerrada) bocaCerrada.style.display = 'none';
    if (bocaAbierta) bocaAbierta.style.display = 'block';
  } else {
    if (ojoIzqAbierto) ojoIzqAbierto.style.display = 'block';
    if (ojoIzqFeliz) ojoIzqFeliz.style.display = 'none';
    if (ojoDerAbierto) ojoDerAbierto.style.display = 'block';
    if (ojoDerFeliz) ojoDerFeliz.style.display = 'none';

    if (estadoActual === 'hablando') {
      if (bocaCerrada) bocaCerrada.style.display = 'none';
      if (bocaAbierta) bocaAbierta.style.display = 'block';
    } else {
      if (bocaCerrada) bocaCerrada.style.display = 'block';
      if (bocaAbierta) bocaAbierta.style.display = 'none';
    }
  }

  // Párpados si está dormido
  if (parpadoIzq && parpadoDer) {
    if (estadoActual === 'dormido') {
      parpadoIzq.style.transform = 'scaleY(1)';
      parpadoDer.style.transform = 'scaleY(1)';
    } else if (!parpadeando) {
      parpadoIzq.style.transform = 'scaleY(0)';
      parpadoDer.style.transform = 'scaleY(0)';
    }
  }
}
pintarCara('idle');

/* Pestañeo natural periódico */
setInterval(() => {
  if (estadoActual !== 'idle' && estadoActual !== 'escuchando') return;
  parpadeando = true;
  if (parpadoIzq) parpadoIzq.style.transform = 'scaleY(1)';
  if (parpadoDer) parpadoDer.style.transform = 'scaleY(1)';
  setTimeout(() => {
    parpadeando = false;
    if (estadoActual !== 'dormido') {
      if (parpadoIzq) parpadoIzq.style.transform = 'scaleY(0)';
      if (parpadoDer) parpadoDer.style.transform = 'scaleY(0)';
    }
  }, 130);
}, 3800 + Math.random() * 3200);

/* Seguimiento suave de la mirada con el cursor */
window.addEventListener('mousemove', (e) => {
  if (estadoActual === 'dormido' || estadoActual === 'pensando' || estadoActual === 'feliz') return;
  if (!danteBox || !pupilaIzq || !pupilaDer) return;
  const rect = danteBox.getBoundingClientRect();
  const centroX = rect.left + rect.width / 2;
  const centroY = rect.top + rect.height / 2;
  const dx = Math.max(-1, Math.min(1, (e.clientX - centroX) / 300));
  const dy = Math.max(-1, Math.min(1, (e.clientY - centroY) / 300));
  pupilaIzq.style.transform = `translate(${dx * 2.5}px, ${dy * 2.2}px)`;
  pupilaDer.style.transform = `translate(${dx * 2.5}px, ${dy * 2.2}px)`;
});

/* Ladrido sintético tierno con Web Audio al acariciar a Dante */
function ladrarCachorro() {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'triangle';
    osc.frequency.setValueAtTime(340, ctx.currentTime);
    osc.frequency.exponentialRampToValueAtTime(160, ctx.currentTime + 0.16);
    gain.gain.setValueAtTime(0.2, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.16);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.17);
  } catch (err) {
    console.debug('Audio ladrar:', err);
  }
}

/* Interacción táctil / clic sobre Dante */
if (danteBox) {
  danteBox.addEventListener('click', (ev) => {
    ladrarCachorro();

    // Partícula visual flotante (corazón o huellita)
    const part = document.createElement('div');
    part.className = 'particula-amor';
    part.textContent = Math.random() > 0.4 ? '🐾' : '💖';
    part.style.left = (ev.offsetX || 36) + 'px';
    part.style.top = (ev.offsetY || 36) + 'px';
    danteBox.appendChild(part);
    setTimeout(() => part.remove(), 850);

    const prev = estadoActual;
    pintarCara('feliz');
    setTimeout(() => {
      if (estadoActual === 'feliz') pintarCara(prev === 'dormido' ? 'idle' : prev);
    }, 1800);
  });
}

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

  ws.onclose = () => { setTimeout(conectar, 1500); };

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

  if (b.dataset.v==='gente'){ cargarGente(); cargarObjetos(); }

  if (b.dataset.v==='senales') cargarSenales();

  if (b.dataset.v==='agenda') cargarAgenda();

  if (b.dataset.v==='voz') cargarVoces();

});



/* ---------- ajustes ---------- */

const form = $('#cfg'), form2 = $('#cfg2');

async function cargarCfg(){

  const a = await (await fetch('/api/ajustes')).json();

  for (const [k,v] of Object.entries(a.ajustes||{})){

    const el = form.elements[k] || form2.elements[k]; if (el) el.value = v; }

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

}

form.onsubmit  = e => { e.preventDefault(); guardarTodo('Guardado. Ya se lo dije a Dante.'); };

form2.onsubmit = e => { e.preventDefault();

  guardarTodo('Guardado. Dante ya lo tiene en su memoria.');

  window.scrollTo({top:0,behavior:'smooth'}); };

function avisar(sel, txt){ const a=$(sel); a.textContent=txt; a.style.display='block';

  setTimeout(()=>a.style.display='none', 3600); }



$('#b-recado').onclick = async () => {

  const de = $('#de').value.trim(), texto = $('#recado').value.trim();

  if (!de)    { avisar('#aviso-voz','Poné de parte de quién es.'); return; }

  if (!texto) { avisar('#aviso-voz','Escribí el recado.'); return; }

  const r = await (await fetch('/api/recado',{method:'POST',

    headers:{'Content-Type':'application/json'},

    body:JSON.stringify({de, texto})})).json();

  if (!r.ok){ avisar('#aviso-voz', r.motivo||'No pude guardarlo.'); return; }

  $('#recado').value = '';

  avisar('#aviso-voz','Listo. Dante se lo dice apenas hablen.');

  cargarVoces();

};



async function cargarObjetos(){

  const g = $('#objetos'), r = await (await fetch('/api/objetos')).json();

  const l = r.objetos || [];

  $('#n-obj').textContent = l.length ? l.length+' cosas' : '';

  if (!l.length){

    g.innerHTML = '<div class="pad ayuda vacio">Todavía no tiene ninguna anotada.</div>';

    return; }

  g.innerHTML = '';

  l.forEach(o => {

    const d = document.createElement('div'); d.className = 'ficha';

    d.innerHTML = `<div style="flex:1"><b>${o.visto?'👁️':'🦴'} ${o.nombre}</b>

      <div class="ayuda">${o.donde} · ${o.fecha.replace('T',' a las ')}

      ${o.visto?'<b style="color:var(--paseo)">· lo vio</b>':''}</div></div>`;

    g.appendChild(d);

  });

}



/* ---------- recordatorios ---------- */

const fNuevo = $('#ag-nuevo');

// El dia solo se pide cuando hace falta: para algo diario sobra, y un campo

// que no se usa hace dudar de si habia que llenarlo.

fNuevo.elements.clase.onchange = () => {

  const c = fNuevo.elements.clase.value;

  $('#l-fecha').style.display = (c === 'diario') ? 'none' : '';

};

const COMO = {medicacion:'💊', visita:'🚪', cita:'📋', fecha:'🎂', otro:'🦴'};

async function cargarAgenda(){

  const r = await (await fetch('/api/recordatorios')).json();

  pintarAgenda(r.recordatorios || []);

}

function pintarAgenda(lista){

  const g = $('#agenda');

  if (!lista.length){

    g.innerHTML = '<div class="pad ayuda vacio">Todavía no hay ninguno. '

                + 'Dante también los anota si se lo pedís hablando.</div>'; return; }

  g.innerHTML = '';

  lista.forEach(e => {

    const d = document.createElement('div');

    d.className = 'ficha';

    d.innerHTML = `<div style="flex:1">

        <b>${COMO[e.tipo]||'🦴'} ${e.que}</b>

        <div class="ayuda">${e.en_palabras.split('—')[1]||''}

          ${e.hoy ? '<b style="color:var(--miel)">· hoy</b>' : ''}</div>

      </div>`;

    const ed = document.createElement('button');

    ed.textContent = 'Editar'; ed.className = 'chico';

    ed.onclick = () => editarFicha(d, e);

    const b = document.createElement('button');

    b.textContent = 'Quitar'; b.className = 'chico';

    b.onclick = async () => {

      if (!confirm('¿Quitar «'+e.que+'»?')) return;

      const r = await (await fetch('/api/recordatorios/'+e.id,{method:'DELETE'})).json();

      pintarAgenda(r.recordatorios||[]);

      avisar('#aviso-ag','Quitado.');

    };

    d.appendChild(ed); d.appendChild(b); g.appendChild(d);

  });

}

// Editar donde está, sin abrir otra pantalla: quien corrige una hora quiere

// ver el resto de la lista mientras lo hace.

function editarFicha(fila, e){

  const hora = (e.cuando.match(/(\d{2}:\d{2})/)||['09:00'])[0];

  const dia  = e.clase==='anual' ? '2000-'+e.cuando.split(' ')[1]

             : e.clase==='unico' ? e.cuando.slice(0,10) : '';

  fila.className = 'ficha editando';

  fila.innerHTML = `

    <div style="flex:1">

      <input class="e-que" value="${e.que.replace(/"/g,'&quot;')}" style="width:100%">

      <div class="dos" style="gap:8px">

        <select class="e-clase">

          <option value="diario">Todos los días</option>

          <option value="unico">Un día concreto</option>

          <option value="anual">Todos los años</option></select>

        <select class="e-tipo">

          <option value="medicacion">Medicamento</option>

          <option value="visita">Visita</option>

          <option value="cita">Cita</option>

          <option value="fecha">Fecha importante</option>

          <option value="otro">Otra cosa</option></select>

      </div>

      <div class="dos" style="gap:8px">

        <input type="date" class="e-dia" value="${dia}">

        <input type="time" class="e-hora" value="${hora}">

      </div>

    </div>`;

  fila.querySelector('.e-clase').value = e.clase;

  fila.querySelector('.e-tipo').value  = e.tipo || 'otro';

  const dia_ = fila.querySelector('.e-dia');

  const verDia = () => dia_.style.visibility =

    (fila.querySelector('.e-clase').value==='diario') ? 'hidden' : 'visible';

  fila.querySelector('.e-clase').onchange = verDia; verDia();



  const ok = document.createElement('button');

  ok.textContent = 'Guardar'; ok.className = 'chico pri';

  ok.onclick = async () => {

    const cl = fila.querySelector('.e-clase').value;

    const h  = fila.querySelector('.e-hora').value || '09:00';

    const f  = dia_.value;

    const cuando = cl==='diario' ? 'diario '+h

                 : cl==='anual'  ? 'anual '+(f||'').slice(5)

                 : (f||'')+'T'+h;

    const r = await (await fetch('/api/recordatorios/'+e.id,{method:'PUT',

      headers:{'Content-Type':'application/json'},

      body:JSON.stringify({que:fila.querySelector('.e-que').value, cuando,

                           tipo:fila.querySelector('.e-tipo').value})})).json();

    if (!r.ok){ avisar('#aviso-ag', r.error||'No pude guardarlo.'); return; }

    pintarAgenda(r.recordatorios||[]);

    avisar('#aviso-ag','Cambiado. Dante ya lo sabe.');

  };

  const no = document.createElement('button');

  no.textContent = 'Dejar'; no.className = 'chico';

  no.onclick = () => cargarAgenda();

  fila.appendChild(ok); fila.appendChild(no);

}



/* ---------- el pulso de hoy ---------- */

async function cargarPulso(){

  const h = await (await fetch('/api/hoy')).json();

  const n = h.pendientes.length;

  $('#pulso').innerHTML = `

    <div class="dato ${n?'hay':''}"><b>${n}</b><span>hoy pendiente${n===1?'':'s'}</span></div>

    <div class="dato"><b>${h.hechos}</b><span>cosas que recuerda</span></div>

    <div class="dato"><b>${h.personas}</b><span>personas · ${h.caras} caras</span></div>

    <div class="dato"><b>${h.charlas}</b><span>conversaciones</span></div>`;

  if (n) $('#pulso').insertAdjacentHTML('beforeend',

    `<div class="dato" style="grid-column:1/-1"><span>lo de hoy</span>

      <div class="hoy-lista">${h.pendientes.map(

        p=>`<span class="pastilla">${p.split('—')[0]}</span>`).join('')}</div></div>`);

}

cargarPulso();

setInterval(cargarPulso, 30000);

fNuevo.onsubmit = async ev => {

  ev.preventDefault();

  const d = Object.fromEntries(new FormData(fNuevo).entries());

  const hora = d.hora || '09:00';

  let cuando;

  if (d.clase === 'diario')      cuando = 'diario ' + hora;

  else if (d.clase === 'anual')  cuando = 'anual ' + (d.fecha||'').slice(5);

  else                           cuando = (d.fecha||'') + 'T' + hora;

  const r = await (await fetch('/api/recordatorios',{method:'POST',

    headers:{'Content-Type':'application/json'},

    body:JSON.stringify({que:d.que, cuando, tipo:d.tipo})})).json();

  if (!r.ok){ avisar('#aviso-ag', r.error||'No pude anotarlo.'); return; }

  pintarAgenda(r.recordatorios||[]);

  fNuevo.reset(); fNuevo.elements.hora.value = '09:00';

  $('#l-fecha').style.display='none';

  avisar('#aviso-ag','Anotado. Dante ya lo sabe.');

};



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

  pintarCambios(r.cambios||[]);

  if (!r.senales.length){ c.innerHTML='<div class="pad ayuda vacio">Sin novedades. Eso es buena señal.</div>'; return; }

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



function pintarCambios(lista){

  const c = $('#cambios');

  $('#n-cam').textContent = lista.length ? lista.length+' cosas' : '';

  if (!lista.length){

    c.innerHTML = '<div class="pad ayuda vacio">Nada distinto de lo habitual, '

                + 'o todavía no hay suficientes semanas para comparar.</div>'; return; }

  c.innerHTML = '';

  lista.forEach(x => {

    const d = document.createElement('div'); d.className = 'ficha';

    d.innerHTML = `<div style="flex:1"><b>${x.que}</b>

      <div class="ayuda">esta semana <b>${x.esta_semana}</b> · antes ${x.antes}</div></div>

      <div class="veces">${x.cuanto}</div>`;

    c.appendChild(d);

  });

}

$('#b-resumen').onclick = async () => {

  const caja = $('#resumen');

  caja.innerHTML = '<span class="ayuda cargando">Dante lo está escribiendo…</span>';

  const r = await (await fetch('/api/resumen')).json();

  caja.innerHTML = r.hay

    ? `<div class="pad" style="background:var(--hueso);border-radius:12px">

         <div class="ayuda" style="margin-bottom:6px">del ${r.desde} al ${r.hasta}</div>

         ${r.nota}</div>`

    : '<span class="ayuda">No hubo conversaciones esta semana. No hay nada que contar.</span>';

};



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

  if (!r.mensajes.length){ c.innerHTML='<div class="pad ayuda vacio">Todavía no hay ninguno.</div>'; return; }

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

    app = FastAPI(title="Kibo")

    clientes: set = set()



    @app.middleware("http")
    async def reparto(peticion, siguiente):
        """En el demo publico, apunta esta peticion a la memoria del visitante.

        Se ejecuta dentro de la puerta de Auth0, asi que lo primero que toca
        cualquier consulta ya esta apuntando a la base correcta: ninguna
        peticion de un visitante puede escribir en la del dueno del aparato.
        """
        if not demo.activo():
            return await siguiente(peticion)
        id_ = peticion.cookies.get(demo.GALLETA) or ""
        # Su ruta se calcula desde la galleta, exista o no una conversacion
        # abierta. Si aqui cayera en la base de siempre, el visitante veria
        # -y podria cambiar- la vida del dueno del aparato.
        memoria.RUTA.set(demo.ruta_de(id_) if id_ else demo.ruta_de("nuevo"))
        respuesta = await siguiente(peticion)
        if not id_:
            # Se entrega ya, para que el websocket la traiga puesta y sepamos
            # que visita es antes de abrirle un Dante propio.
            respuesta.set_cookie(demo.GALLETA, demo.nueva_id(), httponly=True,
                                 samesite="lax", max_age=3600)
        return respuesta

    @app.middleware("http")

    async def puerta(peticion, siguiente):

        """Si Auth0 esta configurado, todo pasa por el login menos el propio

        login. Si no lo esta, esto no hace nada."""

        ruta = peticion.url.path
        # En el demo no se pide cuenta de Google. Cada visita esta aislada y
        # dura minutos; exigirle un login a un jurado del otro lado del mundo
        # es la forma mas segura de que cierre la pestana sin ver nada.
        if demo.activo():
            return await siguiente(peticion)

        if not auth.activo() or ruta in (
            "/login", "/callback", "/salir",
            "/favicon.svg", "/favicon.ico", "/favicon.png",
        ):

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

        return PAGINA.replace("@@FAVICON@@", FAVICON_B64)



    @app.get("/favicon.png")
    def favicon_png():

        return FileResponse(Path(__file__).resolve().parent / "favicon.png", media_type="image/png")



    @app.get("/favicon.ico")
    @app.get("/favicon.svg")
    def favicon_ico():

        ico = Path(__file__).resolve().parent / "favicon.ico"

        return FileResponse(ico, media_type="image/x-icon")



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



    @app.get("/api/hoy")

    def ver_hoy():

        """Un vistazo de como esta Dante ahora mismo.



        Es lo primero que ve quien abre el portal, asi que responde lo que

        de verdad se pregunta: que hay pendiente, a quien conoce, cuanto

        recuerda. Numeros, no adornos.

        """

        c = memoria.abrir()

        try:

            p = memoria.principal(c)

            n = lambda q: c.execute(q).fetchone()["n"]

            return {

                "persona": p["nombre"] if p else "",

                "pendientes": memoria.agenda_de(c, "hoy"),

                "personas": n("SELECT COUNT(*) n FROM personas"),

                "caras": n("SELECT COUNT(*) n FROM personas WHERE cara IS NOT NULL"),

                "hechos": n("SELECT COUNT(*) n FROM hechos"),

                "charlas": n("SELECT COUNT(*) n FROM episodios"),

            }

        finally:

            c.close()



    @app.get("/api/objetos")

    def ver_objetos():

        c = memoria.abrir()

        try:

            return {"objetos": memoria.objetos_todos(c)}

        finally:

            c.close()



    @app.get("/api/recordatorios")

    def ver_recordatorios():

        c = memoria.abrir()

        try:

            return {"recordatorios": memoria.eventos_todos(c)}

        finally:

            c.close()



    @app.post("/api/recordatorios")

    async def poner_recordatorio(datos: dict):

        c = memoria.abrir()

        try:

            id_ = memoria.poner_evento(c, datos.get("que", ""),

                                       datos.get("cuando", ""),

                                       datos.get("tipo", ""))

            if not id_:

                return {"ok": False,

                        "error": "Falta el texto o la fecha no se entiende."}

            return {"ok": True, "recordatorios": memoria.eventos_todos(c)}

        finally:

            c.close()



    @app.put("/api/recordatorios/{id_}")

    async def editar_recordatorio(id_: int, datos: dict):

        c = memoria.abrir()

        try:

            ok = memoria.editar_evento(c, id_, datos.get("que", ""),

                                       datos.get("cuando", ""),

                                       datos.get("tipo", ""))

            if not ok:

                return {"ok": False,

                        "error": "Falta el texto o la fecha no se entiende."}

            return {"ok": True, "recordatorios": memoria.eventos_todos(c)}

        finally:

            c.close()



    @app.delete("/api/recordatorios/{id_}")

    def quitar_recordatorio(id_: int):

        c = memoria.abrir()

        try:

            memoria.quitar_evento(c, id_)

            return {"ok": True, "recordatorios": memoria.eventos_todos(c)}

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

            return {"senales": memoria.senales_recientes(c, 7),

                    "cambios": memoria.cambios(c)}

        finally:

            c.close()



    @app.get("/api/resumen")

    def ver_resumen():

        from . import semanal

        c = memoria.abrir()

        try:

            datos = semanal._datos(c)

            if not datos["conversaciones"]:

                return {"hay": False}

            return {"hay": True, "nota": semanal.redactar(datos),

                    "desde": datos["desde"], "hasta": datos["hasta"]}

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



    @app.post("/api/recado")

    async def dejar_recado(datos: dict):

        from . import mensajes as _m

        return _m.guardar_texto(datos.get("de", ""), datos.get("texto", ""))



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
        if not demo.activo() and auth.activo() and not auth.usuario_de(ws):
            await ws.close(1008, "sin sesion")
            return

        # En el demo publico cada navegador tiene su propio Dante. Sin esto,
        # diez jueces comparten una sola sesion: se pisan al hablar y el
        # segundo lee la conversacion del primero.
        visita, propio = None, sesion
        if demo.activo():
            id_ = ws.cookies.get(demo.GALLETA) or demo.nueva_id()
            visita = demo.de(id_)
            if visita is None:
                if not demo.hay_sitio():
                    await ws.accept()
                    await ws.send_text(json.dumps({"t": "lleno", "v":
                        f"Ahora mismo hay {demo.cuantas()} personas hablando "
                        f"con Dante, que es el maximo. Probá en un par de "
                        f"minutos."}))
                    await ws.close(1013, "lleno")
                    return
                try:
                    visita = await demo.abrir(id_)
                except Exception as e:
                    await ws.accept()
                    await ws.send_text(json.dumps({"t": "lleno", "v":
                        f"No pude abrir una sesion nueva: {e}"}))
                    await ws.close(1011, "error")
                    return
            propio = visita.sesion
            memoria.RUTA.set(visita.ruta)

        await ws.accept()
        if visita is None:
            clientes.add(ws)
        else:
            # No entra en 'clientes': lo que diga su Dante va solo a sus
            # pestanas. Mezclarlo con el bus general le mandaria a un juez
            # la conversacion de otro, que es justo lo que vinimos a evitar.
            visita.clientes.add(ws)
            if not visita.reparte:
                visita.reparte = True
                bucle_v = asyncio.get_running_loop()

                def solo_suyo(ev: dict, v=visita, b=bucle_v) -> None:
                    texto = json.dumps(ev, ensure_ascii=False)
                    for c in list(v.clientes):
                        try:
                            asyncio.run_coroutine_threadsafe(c.send_text(texto), b)
                        except Exception:
                            pass

                def audio_suyo(pcm: bytes, v=visita, b=bucle_v) -> None:
                    for c in list(v.clientes):
                        try:
                            asyncio.run_coroutine_threadsafe(c.send_bytes(pcm), b)
                        except Exception:
                            pass

                propio.oyentes.append(solo_suyo)
                propio.oyentes_audio.append(audio_suyo)
            await ws.send_text(json.dumps({"t": "demo",
                                           "minutos": visita.quedan}))
        await ws.send_text(json.dumps({"t": "estado", "v": propio.estado}))
        try:
            while True:
                m = await ws.receive()
                if "bytes" in m and m["bytes"]:
                    if len(m["bytes"]) > 64000:
                        continue          # un trozo de audio son 960 bytes
                    # Audio del navegador: mismo camino que el del aparato.
                    asyncio.run_coroutine_threadsafe(
                        propio.audio_del_panel(m["bytes"]), propio.bucle)
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
                            propio.decir_texto(d.get("v", "")), propio.bucle)
                    elif d.get("t") == "boton":
                        asyncio.run_coroutine_threadsafe(
                            propio._boton(d.get("v") == "abajo"), propio.bucle)
        except (WebSocketDisconnect, RuntimeError, KeyError):
            pass
        finally:
            clientes.discard(ws)
            if visita is not None:
                visita.clientes.discard(ws)
                # Si cerro la pestana, su Dante se va con el: dejarlo abierto
                # gastaria creditos hablandole a nadie.
                if not visita.clientes:
                    await demo.cerrar(visita.id)
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
