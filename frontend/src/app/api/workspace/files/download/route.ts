import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

function authHeaders(req: NextRequest): Record<string, string> {
  const tok = req.cookies.get("access_token")?.value;
  return tok ? { Authorization: `Bearer ${tok}` } : {};
}

/**
 * GET /api/workspace/files/download?path=...
 * Proxies the file download from the backend (binary stream).
 */
export async function GET(request: NextRequest) {
  const url = new URL(request.url);
  const path = url.searchParams.get("path");
  if (!path) {
    return NextResponse.json({ detail: "Missing path" }, { status: 400 });
  }
  const resp = await fetch(
    `${BACKEND_URL}/api/v1/workspace/files/download?path=${encodeURIComponent(path)}`,
    { headers: { ...authHeaders(request) } }
  );
  if (!resp.ok) {
    return NextResponse.json(
      { detail: `Backend error: ${resp.status}` },
      { status: resp.status }
    );
  }
  const headers = new Headers();
  headers.set(
    "Content-Type",
    resp.headers.get("content-type") || "application/octet-stream"
  );
  headers.set(
    "Content-Disposition",
    resp.headers.get("content-disposition") || "attachment"
  );
  if (resp.headers.get("content-length")) {
    headers.set("Content-Length", resp.headers.get("content-length")!);
  }
  return new NextResponse(resp.body, { status: 200, headers });
}
