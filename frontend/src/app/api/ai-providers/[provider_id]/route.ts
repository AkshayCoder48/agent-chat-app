import { NextRequest, NextResponse } from "next/server";
import { backendFetch, BackendApiError } from "@/lib/server-api";

function authHeaders(req: NextRequest): Record<string, string> {
  const tok = req.cookies.get("access_token")?.value;
  return tok ? { Authorization: `Bearer ${tok}` } : {};
}

/**
 * PATCH /api/ai-providers/:id
 * Update an existing provider. Send api_key="" to clear it.
 */
export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ provider_id: string }> },
) {
  const { provider_id } = await params;
  try {
    const body = await request.json();
    const data = await backendFetch(`/api/v1/ai-providers/${provider_id}`, {
      method: "PATCH",
      headers: { ...authHeaders(request), "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}

/**
 * DELETE /api/ai-providers/:id
 */
export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ provider_id: string }> },
) {
  const { provider_id } = await params;
  try {
    await backendFetch(`/api/v1/ai-providers/${provider_id}`, {
      method: "DELETE",
      headers: { ...authHeaders(request) },
    });
    return new NextResponse(null, { status: 204 });
  } catch (error) {
    if (error instanceof BackendApiError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}
