import { NextRequest, NextResponse } from "next/server";
import { backendFetch, BackendApiError } from "@/lib/server-api";

function authHeaders(req: NextRequest): Record<string, string> {
  const tok = req.cookies.get("access_token")?.value;
  return tok ? { Authorization: `Bearer ${tok}` } : {};
}

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ server_id: string }> },
) {
  const { server_id } = await params;
  try {
    const body = await request.text();
    const data = await backendFetch(`/api/v1/mcp-servers/${server_id}`, {
      method: "PUT",
      body,
      headers: {
        "Content-Type": "application/json",
        ...authHeaders(request),
      },
    });
    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ server_id: string }> },
) {
  const { server_id } = await params;
  try {
    await backendFetch(`/api/v1/mcp-servers/${server_id}`, {
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
