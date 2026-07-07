import { NextRequest, NextResponse } from "next/server";
import { backendFetch, BackendApiError } from "@/lib/server-api";

function authHeaders(req: NextRequest): Record<string, string> {
  const tok = req.cookies.get("access_token")?.value;
  return tok ? { Authorization: `Bearer ${tok}` } : {};
}

/**
 * POST /api/files/upload
 *
 * Multipart upload — re-stream the FormData straight to the backend. The
 * backend's /files/upload route stores the file as a ChatFile row and
 * returns FileUploadResponse (id, filename, mime_type, size, file_type).
 *
 * If the user has a Hopx API key set, the backend ALSO mirrors the file into
 * their Hopx sandbox so the agent can read it via the workspace tools. That
 * mirroring is handled server-side to keep the auth token off the client.
 */
export async function POST(request: NextRequest) {
  try {
    const formData = await request.formData();
    const data = await backendFetch(`/api/v1/files/upload`, {
      method: "POST",
      body: formData,
      headers: { ...authHeaders(request) },
    });
    return NextResponse.json(data, { status: 201 });
  } catch (error) {
    if (error instanceof BackendApiError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    const msg = error instanceof Error ? error.message : "Internal server error";
    return NextResponse.json({ detail: msg }, { status: 500 });
  }
}
