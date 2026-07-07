import { NextRequest } from "next/server";
import { authedBackendFetch } from "@/lib/authed-backend-fetch";

/**
 * Proxy /api/agent-settings/env-vars/[name] to the FastAPI backend.
 * Uses `authedBackendFetch` for silent token refresh + real error surfacing.
 */

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ name: string }> },
) {
  const { name } = await params;
  const body = await request.text();
  const r = await authedBackendFetch(
    request,
    `/api/v1/agent-settings/env-vars/${encodeURIComponent(name)}`,
    {
      method: "PUT",
      body,
      headers: { "Content-Type": "application/json" },
    },
  );
  if (r.ok) return r.response;
  return Response.json({ detail: r.message }, { status: r.status });
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ name: string }> },
) {
  const { name } = await params;
  const r = await authedBackendFetch(
    request,
    `/api/v1/agent-settings/env-vars/${encodeURIComponent(name)}`,
    { method: "DELETE" },
  );
  if (r.ok) return r.response;
  return Response.json({ detail: r.message }, { status: r.status });
}
