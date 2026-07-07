import { NextRequest, NextResponse } from "next/server";
import { backendFetch, BackendApiError } from "@/lib/server-api";

function authHeaders(req: NextRequest): Record<string, string> {
  const tok = req.cookies.get("access_token")?.value;
  return tok ? { Authorization: `Bearer ${tok}` } : {};
}

/**
 * Proxy for POST /api/v1/skills/upload.
 *
 * Accepts multipart/form-data with:
 *   - file: a .zip archive OR a SKILL.md markdown file
 *
 * Forwards the raw FormData to the backend so it can extract the skill
 * into the user's per-user skills directory.
 */
export async function POST(request: NextRequest) {
  try {
    const formData = await request.formData();
    const data = await backendFetch(`/api/v1/skills/upload`, {
      method: "POST",
      body: formData,
      headers: { ...authHeaders(request) },
    });
    return NextResponse.json(data, { status: 201 });
  } catch (error) {
    if (error instanceof BackendApiError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}
