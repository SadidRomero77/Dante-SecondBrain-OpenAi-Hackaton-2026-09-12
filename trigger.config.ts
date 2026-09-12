import { defineConfig } from "@trigger.dev/sdk";

export default defineConfig({
  project: "proj_slhciwuoxapsrziamieq",
  dirs: ["./src/trigger"],
  // Estas tareas mandan correos y esperan: minutos, no horas.
  maxDuration: 3600,
  retries: {
    enabledInDev: false,
    default: {
      maxAttempts: 5,
      minTimeoutInMs: 2000,
      maxTimeoutInMs: 60000,
      factor: 2,
      randomize: true,
    },
  },
});
