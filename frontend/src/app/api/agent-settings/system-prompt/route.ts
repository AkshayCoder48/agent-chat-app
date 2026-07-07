import { NextRequest } from "next/server";
import { authedBackendFetch } from "@/lib/authed-backend-fetch";

/**
 * Proxy /api/agent-settings/system-prompt to the FastAPI backend.
 * Uses `authedBackendFetch` for silent token refresh + real error surfacing.
 */

export async function GET(request: NextRequest) {
  const r = await authedBackendFetch(
    request,
    `/api/v1/agent-settings/system-prompt`,
  );
  if (r.ok) return r.response;
  return Response.json({ detail: r.message }, { status: r.status });
}

export async function PUT(request: NextRequest) {
  const body = await request.text();
  const r = await authedBackendFetch(
    request,
    `/api/v1/agent-settings/system-prompt`,
    {
      method: "PUT",
      body,
      headers: { "Content-Type": "application/json" },
    },
  );
  if (r.ok) return r.response;
  return Response.json({ detail: r.message }, { status: r.status });
}

export async function DELETE(request: NextRequest) {
  const r = await authedBackendFetch(
    request,
    `/api/v1/agent-settings/system-prompt`,
    { method: "DELETE" },
  );
  if (r.ok) return r.response;
  return Response.json({ detail: r.message }, { status: r.status });
}
