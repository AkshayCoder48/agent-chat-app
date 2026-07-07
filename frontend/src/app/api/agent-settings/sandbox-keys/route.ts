import { NextRequest, NextResponse } from "next/server";
import { backendFetch, BackendApiError } from "@/lib/server-api";

function authHeaders(req: NextRequest): Record<string, string> {
  const tok = req.cookies.get("access_token")?.value;
  return tok ? { Authorization: `Bearer ${tok}` } : {};
}

export async function GET(request: NextRequest) {
  try {
    const data = await backendFetch(`/api/v1/agent-settings/sandbox-keys`, {
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

export async function PUT(request: NextRequest) {
  try {
    const body = await request.text();
    const data = await backendFetch(`/api/v1/agent-settings/sandbox-keys`, {
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
