import { logger, task, wait } from "@trigger.dev/sdk";

/**
 * Vigila que un medicamento se confirme, y avisa a la familia si no.
 *
 * Dante recuerda la pastilla en voz alta desde el PC de la casa. Esta tarea
 * hace lo otro: espera, y si nadie confirmo, le avisa a la hija. La espera
 * puede durar horas y tiene que sobrevivir a que el computador se duerma o se
 * reinicie, que es exactamente lo que un temporizador local no garantiza.
 */
export const vigilarMedicacion = task({
  id: "vigilar-medicacion",
  maxDuration: 3600,
  run: async (payload: {
    persona: string;
    medicamento: string;
    correoFamilia: string;
    minutosDeGracia: number;
    urlConfirmacion: string;
  }) => {
    const { persona, medicamento, correoFamilia, minutosDeGracia, urlConfirmacion } =
      payload;

    logger.info("Vigilando", { persona, medicamento, minutosDeGracia });
    await wait.for({ minutes: minutosDeGracia });

    // Se le pregunta al agente si quedo confirmado. Si no contesta —el PC
    // apagado, sin red— tratamos eso como NO confirmado: avisar de mas es
    // mejor que callar de menos.
    let confirmado = false;
    let alcanzable = true;
    try {
      const r = await fetch(urlConfirmacion, { signal: AbortSignal.timeout(10000) });
      if (r.ok) {
        const d = (await r.json()) as { confirmado?: boolean };
        confirmado = d.confirmado === true;
      } else {
        alcanzable = false;
      }
    } catch {
      alcanzable = false;
    }

    if (confirmado) {
      logger.info("Confirmado, no hay que avisar", { persona, medicamento });
      return { aviso: false, confirmado: true };
    }

    const razon = alcanzable
      ? `${persona} no confirmo ${medicamento}.`
      : `No pude comunicarme con el aparato de ${persona}, y ${medicamento} quedo sin confirmar.`;

    const clave = process.env.RESEND_API_KEY;
    if (!clave) {
      logger.warn("Sin RESEND_API_KEY: el aviso no sale", { razon });
      return { aviso: false, motivo: "sin proveedor de correo", razon };
    }

    const r = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: { Authorization: `Bearer ${clave}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        from: process.env.RESEND_REMITENTE ?? "Dante <onboarding@resend.dev>",
        to: [correoFamilia],
        subject: `${persona}: ${medicamento} sin confirmar`,
        text: `${razon}\n\nQuizas quieras llamarla.\n\nDante`,
      }),
    });
    if (!r.ok) throw new Error(`Resend respondio ${r.status}`);

    logger.info("Aviso enviado", { correoFamilia });
    return { aviso: true, razon };
  },
});
