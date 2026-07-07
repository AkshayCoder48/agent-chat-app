import { NextRequest, NextResponse } from "next/server";
import { backendFetch, BackendApiError } from "@/lib/server-api";

function authHeaders(req: NextRequest): Record<string, string> {
  const tok = req.cookies.get("access_token")?.value;
  return tok ? { Authorization: `Bearer ${tok}` } : {};
}

/**
 * GET /api/custom-tools?enabled_only=true
 * Lists the current user's custom tools.
 */
export async function GET(request: NextRequest) {
  const url = new URL(request.url);
  const enabledOnly = url.searchParams.get("enabled_only");
  const qs = enabledOnly ? `?enabled_only=${encodeURIComponent(enabledOnly)}` : "";
  try {
    const data = await backendFetch(`/api/v1/custom-tools${qs}`, {
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
 * POST /api/custom-tools
 * Create a new custom tool.
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const data = await backendFetch(`/api/v1/custom-tools`, {
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

/* Note: The catalog endpoint lives at /api/custom-tools/catalog/route.ts.
   Next.js only allows HTTP verb exports (GET/POST/PUT/PATCH/DELETE/HEAD/OPTIONS)
   in route.ts files, so we MUST NOT export catalogGET here. */
