import { NextRequest } from "next/server";
import { authedBackendFetch } from "@/lib/authed-backend-fetch";

/**
 * Proxy /api/agent-settings/env-vars to the FastAPI backend.
 * Uses `authedBackendFetch` for silent token refresh + real error surfacing.
 */

export async function GET(request: NextRequest) {
  const r = await authedBackendFetch(request, `/api/v1/agent-settings/env-vars`);
  if (r.ok) return r.response;
  return Response.json({ detail: r.message }, { status: r.status });
}

export async function POST(request: NextRequest) {
  const body = await request.text();
  const r = await authedBackendFetch(request, `/api/v1/agent-settings/env-vars`, {
    method: "POST",
    body,
    headers: { "Content-Type": "application/json" },
  });
  if (r.ok) return new Response(JSON.stringify(r.data), { status: 201, headers: { "Content-Type": "application/json" } });
  return Response.json({ detail: r.message }, { status: r.status });
}
