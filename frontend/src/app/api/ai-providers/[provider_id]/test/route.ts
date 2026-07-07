import { NextRequest, NextResponse } from "next/server";
import { backendFetch, BackendApiError } from "@/lib/server-api";

function authHeaders(req: NextRequest): Record<string, string> {
  const tok = req.cookies.get("access_token")?.value;
  return tok ? { Authorization: `Bearer ${tok}` } : {};
}

/**
 * POST /api/ai-providers/:id/test?model=...
 * Sends a minimal /v1/chat/completions request to verify the provider is
 * reachable. Returns { ok, status_code, detail, sample_response }.
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ provider_id: string }> },
) {
  const { provider_id } = await params;
  const url = new URL(request.url);
  const model = url.searchParams.get("model");
  const qs = model ? `?model=${encodeURIComponent(model)}` : "";
  try {
    const data = await backendFetch(`/api/v1/ai-providers/${provider_id}/test${qs}`, {
      method: "POST",
      headers: { ...authHeaders(request), "Content-Length": "0" },
    });
    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}
