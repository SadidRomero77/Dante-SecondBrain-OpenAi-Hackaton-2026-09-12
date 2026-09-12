import { logger, task } from "@trigger.dev/sdk";

/**
 * El resumen semanal que le llega a la familia.
 *
 * Por que esto vive en la nube y no en el PC de la casa: es lo unico del
 * proyecto que tiene que SALIR de la casa. Que un correo se envie de verdad
 * depende de reintentos, de que el destinatario exista y de que el momento
 * llegue aunque el computador este dormido. Un temporizador local no hace
 * ninguna de las tres.
 *
 * El resumen lo arma el agente con la memoria local y llega aqui ya escrito:
 * los datos de la persona no salen de su casa, solo el texto que su familia
 * iba a leer de todas formas.
 */
export const resumenSemanal = task({
  id: "resumen-semanal",
  maxDuration: 300,
  run: async (payload: {
    persona: string;
    correoFamilia: string;
    desde: string;
    hasta: string;
    resumen: string;
    conversaciones: number;
    señales?: string[];
  }) => {
    const { persona, correoFamilia, desde, hasta, resumen, conversaciones } = payload;
    const señales = payload.señales ?? [];

    logger.info("Armando el resumen", { persona, desde, hasta, conversaciones });

    const cuerpo = [
      `Hola,`,
      ``,
      `Este es el resumen de ${persona} entre el ${desde} y el ${hasta}.`,
      ``,
      resumen,
      ``,
      `Conversaciones esta semana: ${conversaciones}.`,
      señales.length
        ? `\nCosas que quizas quieras preguntarle:\n${señales.map((s) => `  · ${s}`).join("\n")}`
        : "",
      ``,
      `Esto lo escribio Dante a partir de lo que hablaron. No es una`,
      `valoracion medica, y puede equivocarse.`,
    ]
      .filter(Boolean)
      .join("\n");

    const clave = process.env.RESEND_API_KEY;
    if (!clave) {
      // Sin proveedor de correo la tarea no falla: deja el texto listo y
      // visible en el panel. Preferimos que se vea a que se pierda.
      logger.warn("Sin RESEND_API_KEY: el resumen no se envia, queda aqui", {
        destinatario: correoFamilia,
      });
      return { enviado: false, motivo: "sin proveedor de correo", cuerpo };
    }

    const r = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${clave}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        from: process.env.RESEND_REMITENTE ?? "Dante <onboarding@resend.dev>",
        to: [correoFamilia],
        subject: `Como estuvo ${persona} esta semana`,
        text: cuerpo,
      }),
    });

    if (!r.ok) {
      // Lanzar hace que Trigger.dev reintente con espera creciente, que es
      // justo para lo que sirve tenerlo aqui.
      throw new Error(`Resend respondio ${r.status}: ${await r.text()}`);
    }

    logger.info("Resumen enviado", { destinatario: correoFamilia });
    return { enviado: true, destinatario: correoFamilia };
  },
});
