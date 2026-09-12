# Seguridad y datos personales

Dante maneja lo más íntimo que tiene una persona: su voz, su cara, su memoria y
su salud declarada. Este documento dice qué se protege, cómo, y qué falta.

## Qué datos hay y dónde viven

| Dato | Dónde | Sale de la máquina |
|---|---|---|
| Transcripciones de las conversaciones | `data/dante.db` | No |
| Hechos, personas, eventos | `data/dante.db` | No |
| Vectores de rostros | `data/dante.db`, columna `cara` | No |
| Fotos de la cámara | En memoria, no se guardan | Solo si se usa `mirar()` |
| Turno de voz | — | **Sí**, a OpenAI, mientras dura |
| Resumen semanal | — | **Sí**, a Trigger.dev, solo el texto |
| Correo de quien entra al portal | Cookie firmada | No |

**La cara no se guarda como foto.** Se guarda un vector de 128 números del que
no se puede reconstruir el rostro. Borrar a una persona borra su vector.

## Lo que se corrigió en la auditoría del 10/09/2026

**El WebSocket del portal estaba abierto.** En Starlette, `@app.middleware("http")`
no corre para el scope de WebSocket, así que la puerta de Auth0 no cubría `/ws`.
Comprobado explotándolo: sin credenciales se podía hablarle al agente, **leer la
conversación privada** y recibir el audio. Ahora el handler valida la misma
cookie firmada y devuelve 403 sin ella.

**El puerto de WiFi estaba abierto a la red local.** Escuchaba en `0.0.0.0` sin
autenticación: cualquiera en la misma red podía hacerse pasar por el aparato,
mandarle audio al agente y oír lo que respondía. Ahora hay una ficha compartida
que se genera sola, se guarda en `data/.ficha` y se le escribe al aparato con
`dante setup` por el cable.

**El secreto de firma de sesiones tenía un valor por defecto en el código.**
Cualquiera que leyera el repositorio podría falsificar una sesión en una
instalación que no lo hubiera cambiado. Ahora se genera al azar y se guarda en
`data/.secreto`, con permisos `600`. No se reusa el de Auth0: si ese se rota, no
queremos que además caigan las sesiones.

**Los estados de login no vencían.** Se guardaban para siempre en un conjunto
que solo crecía. Ahora vencen a los diez minutos y se queman al usarse.

**Sin límites en lo que manda el navegador.** Ahora hay tope de tamaño y
validación de forma.

## Configuración segura

```bash
AUTH0_CORREOS=quien@puede.com,otro@tambien.com
```

**Vacío significa que cualquiera con cuenta de Google puede entrar.** El agente
avisa al arrancar si está así, y avisa más fuerte si además está expuesto a la
red.

Por defecto el portal escucha solo en `127.0.0.1`. Para exponerlo hay que poner
`DANTE_PANEL_HOST=0.0.0.0` a propósito — y entonces **Auth0 deja de ser
opcional**.

## Lo que falta

- **Sin cifrado en reposo.** `data/dante.db` es un SQLite en claro. Quien tenga
  acceso al disco lee todo. Cifrarlo con SQLCipher es el siguiente paso.
- **Sin límite de peticiones.** Nada impide intentar mil logins.
- **Sin HTTPS propio.** Detrás de un proxy con TLS está bien; expuesto directo,
  no.
- **Las transcripciones se imprimen en la consola.** Cómodo para depurar,
  inadecuado si alguien mira la pantalla por encima del hombro.
- **Sin borrado por persona.** Se puede borrar la base entera, pero no "olvidá
  todo lo de Ana". Para un producto real con datos de salud, hace falta.
- **Sin registro de acceso.** No queda constancia de quién entró al portal ni
  cuándo.

## Si vas a hostearlo

1. Auth0 configurado y `AUTH0_CORREOS` con la lista exacta.
2. `DANTE_SECRETO` puesto a mano, no el generado.
3. Detrás de un proxy con TLS. La cookie ya se marca `secure` fuera de localhost.
4. El volumen de datos cifrado a nivel de disco.
5. Tope de gasto en OpenAI: sin eso, un abuso del portal se traduce en dinero.

## Reportar un problema

Abrí un issue sin incluir datos reales de ninguna persona.
