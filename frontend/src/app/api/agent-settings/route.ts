/**
 * Proxy route for /api/v1/agent-settings
 * GET  → fetch the current user's agent settings (system prompt override, etc.)
 * PATCH → update the user's agent settings
 * DELETE → reset to defaults
 */
import { NextRequest, NextResponse } from "next/server";
import { backendFetch, BackendApiError } from "@/lib/server-api";

function authHeaders(req: NextRequest): Record<string, string> {
  const tok = req.cookies.get("access_token")?.value;
  return tok ? { Authorization: `Bearer ${tok}` } : {};
}

export async function GET(req: NextRequest) {
  try {
    const data = await backendFetch(`/api/v1/agent-settings`, {
      headers: { ...authHeaders(req) },
    });
    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}

export async function PATCH(req: NextRequest) {
  try {
    const body = await req.text();
    const data = await backendFetch(`/api/v1/agent-settings`, {
      method: "PATCH",
      headers: { ...authHeaders(req), "Content-Type": "application/json" },
      body,
    });
    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}

export async function DELETE(req: NextRequest) {
  try {
    await backendFetch(`/api/v1/agent-settings`, {
      method: "DELETE",
      headers: { ...authHeaders(req) },
    });
    return new NextResponse(null, { status: 204 });
  } catch (error) {
    if (error instanceof BackendApiError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}
