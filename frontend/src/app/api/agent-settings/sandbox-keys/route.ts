import { NextRequest } from "next/server";
import { authedBackendFetch } from "@/lib/authed-backend-fetch";

/**
 * Proxy /api/agent-settings/sandbox-keys to the FastAPI backend.
 *
 * Uses `authedBackendFetch` which:
 *   - Forwards the access_token cookie as `Authorization: Bearer …`
 *   - On 401, silently refreshes the access_token via /api/auth/me and
 *     retries the original request once. This means an expired 15-minute
 *     access token no longer causes "Failed to save" in the Settings UI
 *     as long as the 7-day refresh token is still valid.
 *   - Surfaces the real backend error message (instead of a generic
 *     "Failed to save") so the user can see *why* the save failed.
 */

export async function GET(request: NextRequest) {
  const r = await authedBackendFetch(
    request,
    `/api/v1/agent-settings/sandbox-keys`,
  );
  if (r.ok) return r.response;
  return Response.json({ detail: r.message }, { status: r.status });
}

export async function PUT(request: NextRequest) {
  const body = await request.text();
  const r = await authedBackendFetch(
    request,
    `/api/v1/agent-settings/sandbox-keys`,
    {
      method: "PUT",
      body,
      headers: { "Content-Type": "application/json" },
    },
  );
  if (r.ok) return r.response;
  return Response.json({ detail: r.message }, { status: r.status });
}
