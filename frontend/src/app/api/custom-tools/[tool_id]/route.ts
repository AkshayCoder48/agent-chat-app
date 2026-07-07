import { NextRequest, NextResponse } from "next/server";
import { backendFetch, BackendApiError } from "@/lib/server-api";

function authHeaders(req: NextRequest): Record<string, string> {
  const tok = req.cookies.get("access_token")?.value;
  return tok ? { Authorization: `Bearer ${tok}` } : {};
}

/**
 * GET /api/custom-tools/{id}
 */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ tool_id: string }> }
) {
  const { tool_id } = await params;
  try {
    const data = await backendFetch(`/api/v1/custom-tools/${tool_id}`, {
      headers: { ...authHeaders(request) },
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
 * PATCH /api/custom-tools/{id}
 */
export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ tool_id: string }> }
) {
  const { tool_id } = await params;
  try {
    const body = await request.json();
    const data = await backendFetch(`/api/v1/custom-tools/${tool_id}`, {
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
 * DELETE /api/custom-tools/{id}
 */
export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ tool_id: string }> }
) {
  const { tool_id } = await params;
  try {
    await backendFetch(`/api/v1/custom-tools/${tool_id}`, {
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
