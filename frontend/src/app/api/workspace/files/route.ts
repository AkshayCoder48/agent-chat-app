import { NextRequest, NextResponse } from "next/server";
import { backendFetch, BackendApiError } from "@/lib/server-api";

function authHeaders(req: NextRequest): Record<string, string> {
  const tok = req.cookies.get("access_token")?.value;
  return tok ? { Authorization: `Bearer ${tok}` } : {};
}

/**
 * GET /api/workspace/files?path=...
 * Lists entries in the calling user's workspace directory.
 * Backend route: GET /api/v1/files/workspace/list?path=...
 */
export async function GET(request: NextRequest) {
  const url = new URL(request.url);
  const path = url.searchParams.get("path") || ".";
  try {
    const data = await backendFetch(
      `/api/v1/files/workspace/list?path=${encodeURIComponent(path)}`,
      { headers: { ...authHeaders(request) } }
    );
    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}
