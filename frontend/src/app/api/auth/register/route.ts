import { NextRequest, NextResponse } from "next/server";
import { backendFetch, BackendApiError } from "@/lib/server-api";
import { extractBackendErrorMessage } from "@/lib/backend-error";
import type { RegisterResponse } from "@/types";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    const data = await backendFetch<RegisterResponse>("/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify(body),
    });

    return NextResponse.json(data, { status: 201 });
  } catch (error) {
    if (error instanceof BackendApiError) {
      const detail = extractBackendErrorMessage(error.data, "Registration failed");
      return NextResponse.json({ detail }, { status: error.status });
    }
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}
