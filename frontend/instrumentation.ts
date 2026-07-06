import { registerOTel } from "@vercel/otel";

export function register() {
  registerOTel({
    serviceName: "agent_chat_app-frontend",
  });
}
