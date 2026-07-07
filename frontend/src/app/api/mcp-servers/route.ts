import { NextRequest, NextResponse } from "next/server";
import { backendFetch, BackendApiError } from "@/lib/server-api";

function authHeaders(req: NextRequest): Record<string, string> {
  const tok = req.cookies.get("access_token")?.value;
  return tok ? { Authorization: `Bearer ${tok}` } : {};
}

export async function GET(request: NextRequest) {
  const url = new URL(request.url);
  const activeOnly = url.searchParams.get("active_only");
  const qs = activeOnly ? `?active_only=${encodeURIComponent(activeOnly)}` : "";
  try {
    const data = await backendFetch(`/api/v1/mcp-servers${qs}`, {
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

export async function POST(request: NextRequest) {
  try {
    const body = await request.text();
    const data = await backendFetch(`/api/v1/mcp-servers`, {
      method: "POST",
      body,
      headers: {
        "Content-Type": "application/json",
        ...authHeaders(request),
      },
    });
    return NextResponse.json(data, { status: 201 });
  } catch (error) {
    if (error instanceof BackendApiError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}
