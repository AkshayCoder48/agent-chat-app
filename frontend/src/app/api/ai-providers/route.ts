import { NextRequest, NextResponse } from "next/server";
import { backendFetch, BackendApiError } from "@/lib/server-api";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

function authHeaders(req: NextRequest): Record<string, string> {
  const tok = req.cookies.get("access_token")?.value;
  return tok ? { Authorization: `Bearer ${tok}` } : {};
}

/**
 * GET /api/ai-providers?active_only=true
 * Lists the current user's custom AI providers.
 */
export async function GET(request: NextRequest) {
  const url = new URL(request.url);
  const activeOnly = url.searchParams.get("active_only");
  const qs = activeOnly ? `?active_only=${encodeURIComponent(activeOnly)}` : "";
  try {
    const data = await backendFetch(`/api/v1/ai-providers${qs}`, {
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
 * POST /api/ai-providers
 * Create a new custom AI provider.
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const data = await backendFetch(`/api/v1/ai-providers`, {
      method: "POST",
      headers: { ...authHeaders(request), "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return NextResponse.json(data, { status: 201 });
  } catch (error) {
    if (error instanceof BackendApiError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}
