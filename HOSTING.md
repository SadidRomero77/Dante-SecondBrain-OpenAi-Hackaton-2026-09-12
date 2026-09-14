# Publicar el portal para el demo

## Lo primero: que se puede publicar y que no

**El agente se queda en tu portatil.** No es una limitacion que se pueda
rodear: el ESP32 esta en el USB y la camara tambien. Ningun servidor en la
nube puede estirar un cable hasta tu mesa.

Lo que sale a internet es **el portal**. La gente entra desde su telefono,
configura el perrito, le escribe, ve lo que la camara esta viendo — y todo eso
lo atiende tu maquina.

```
telefono  ->  internet  ->  tunel  ->  tu portatil  ->  USB  ->  el perrito
```

Para un demo es justo lo que se quiere. Para produccion habria que repensarlo,
porque todo depende de que tu maquina siga encendida.

## El paso que casi siempre se olvida

Auth0 compara la direccion de vuelta **caracter por caracter**. Si el portal
cree que vive en `localhost` y la gente entra por el tunel, el login falla
entero y no es evidente por que.

Por eso existe `DANTE_PANEL_URL`. Cuando esta puesta, el portal arma sus
direcciones con ella en vez de adivinarlas.

## Con ngrok (recomendado para el demo)

El plan gratis da **un dominio fijo**, y eso importa: con una direccion que
cambia cada vez, hay que volver a configurar Auth0 en cada arranque. Justo lo
que no se quiere quince minutos antes de presentar.

**1.** Crea la cuenta en `ngrok.com`, reclama tu dominio gratuito y anotalo.

**2.** Deja el tunel corriendo en su propia terminal:

```
ngrok http 8800 --domain=TU-DOMINIO.ngrok-free.app
```

**3.** En el panel de Auth0, en tu aplicacion, agrega:

| Campo | Valor |
|---|---|
| Allowed Callback URLs | `https://TU-DOMINIO.ngrok-free.app/callback` |
| Allowed Logout URLs | `https://TU-DOMINIO.ngrok-free.app/` |
| Allowed Web Origins | `https://TU-DOMINIO.ngrok-free.app` |

**4.** En tu `.env`:

```
DANTE_PANEL_URL=https://TU-DOMINIO.ngrok-free.app
```

**5.** Arranca Dante como siempre:

```
uv run dante hablar --panel
```

Comparte la direccion. **El puerto sigue escuchando solo en tu maquina**: el
tunel es el unico camino de entrada, y se corta cuando cierras esa terminal.

## Con Cloudflare (sin cuenta, para probar rapido)

```
cloudflared tunnel --url http://localhost:8800
```

Imprime una direccion `trycloudflare.com` y funciona al instante. El problema
para un demo es que **cambia en cada arranque**, asi que hay que rehacer los
tres campos de Auth0 cada vez. Sirve para probar, no para presentar.

## Antes de compartir la direccion

Por un tunel el portal pide cuenta siempre. Pero en casa hay UNA memoria: con
`DANTE_CORREOS` vacio, cualquiera que se cree una cuenta **ve la camara en
vivo** y **lee los recuerdos** de la persona, y puede cambiar la configuracion.

Dante te lo avisa al arrancar.

Si prefieres que solo entren los jurados, pon sus correos:

```
DANTE_CORREOS=jurado1@ejemplo.com,jurado2@ejemplo.com
```

Y si vas a mostrarlo abierto, revisa antes que recuerdos hay cargados. Para el
demo conviene la persona de ejemplo:

```
uv run dante semilla
```

## Si el login no vuelve

Casi siempre es una de dos:

- La direccion de Auth0 **no coincide exactamente** con `DANTE_PANEL_URL`.
  Una barra de mas al final ya basta para que falle.
- `DANTE_PANEL_URL` se puso **despues** de arrancar Dante. Se lee al empezar:
  hay que reiniciarlo.

---

# Como quedo desplegado (12/09/2026)

```
navegador  ->  Cloudflare (HTTPS)  ->  EC2  ->  Caddy :443  ->  contenedor :8800
```

**https://kibo.kibosecondbrain.com**

| Pieza | Que es |
|---|---|
| EC2 `t3.small` en `us-east-1` | la maquina. Nombre `kibo` |
| `kibo-web` | grupo de seguridad: 80, 443 y 22 |
| `kibo-ssm` | rol que le deja leer el secreto y ser administrada por HTTPS |
| `/kibo/openai` | la llave, cifrada en el almacen de AWS |
| Registro A `kibo` | apunta a la IP, con la nube **naranja** |

## Tres cosas que costaron y conviene no repetir

**No hay SSH.** La red desde donde se desplego bloquea el puerto 22 -ni
siquiera llega a github.com-, asi que la maquina se administra con
`aws ssm send-command`, que va por HTTPS. Quedo mejor asi: **no hace falta
dejar SSH abierto a internet**. Para tocarla:

```
aws ssm send-command --instance-ids <id> --document-name AWS-RunShellScript \
  --parameters file://comandos.json
```

**Caddy necesita el nombre escrito.** Con un bloque generico `:443`, Caddy no
emite certificado para un nombre que no conoce y Cloudflare devuelve 525. El
Caddyfile dice `kibo.kibosecondbrain.com:443` a proposito.

**Cloudflare bloquea clientes automaticos.** Un `curl` o un script reciben 403
en todas las rutas mientras un navegador recibe 200. Al probar el despliegue
parece que el sitio esta roto y no lo esta: hay que mandar una cabecera de
navegador, o probar desde uno de verdad.

## Lo que falta para produccion

- El tramo Cloudflare -> maquina usa un certificado propio no verificado
  (modo Full). Para produccion, un certificado de origen de Cloudflare.
- El puerto 22 sigue abierto en el grupo de seguridad aunque no se use.
  Cerrarlo.
- La memoria de cada cuenta vive en `/datos/cuentas/<id>/` y NO se borra.
  El contenedor tiene que lanzarse con `-v kibo-datos:/datos`: sin volumen,
  cada despliegue se lleva las cuentas y la memoria de todos.
