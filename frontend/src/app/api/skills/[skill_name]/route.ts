import { NextRequest, NextResponse } from "next/server";
import { backendFetch, BackendApiError } from "@/lib/server-api";

function authHeaders(req: NextRequest): Record<string, string> {
  const tok = req.cookies.get("access_token")?.value;
  return tok ? { Authorization: `Bearer ${tok}` } : {};
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ skill_name: string }> },
) {
  const { skill_name } = await params;
  try {
    const data = await backendFetch(`/api/v1/skills/${encodeURIComponent(skill_name)}`, {
      method: "DELETE",
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
