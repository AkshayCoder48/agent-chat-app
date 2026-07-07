import { NextRequest, NextResponse } from "next/server";
import { backendFetch, BackendApiError } from "@/lib/server-api";
import { extractBackendErrorMessage } from "@/lib/backend-error";

type BackendFetchOptions = Parameters<typeof backendFetch>[1];

/**
 * Authenticated proxy helpers for Next.js API routes.
 *
 * The frontend stores the access_token as an httpOnly cookie (15-minute
 * expiry) and the refresh_token as another httpOnly cookie (7-day expiry).
 * When the access_token expires, the user's next request would 401 —
 * which used to silently fail every save in the Settings UI with a
 * generic "Failed to save" toast and no path forward short of reloading
 * the page.
 *
 * These helpers wrap `backendFetch` with a silent refresh-and-retry:
 * on 401 from the backend, we hit `/api/auth/me` (which uses the
 * refresh_token cookie to mint a new access_token, sets it as a fresh
 * cookie, and returns it in the body). We then re-issue the original
 * request with the new token and forward the new cookie to the browser.
 *
 * The shape mirrors `backendFetch` so existing routes can swap
 * `backendFetch` → `authedBackendFetch` with minimal changes.
 */

function authHeaders(req: NextRequest): Record<string, string> {
  const tok = req.cookies.get("access_token")?.value;
  return tok ? { Authorization: `Bearer ${tok}` } : {};
}

const ACCESS_COOKIE_OPTS = {
  httpOnly: true,
  secure: process.env.NODE_ENV === "production",
  sameSite: "lax" as const,
  maxAge: 60 * 15,
  path: "/",
};

async function tryRefreshAccessToken(): Promise<string | null> {
  try {
    const me = await fetch(
      `${process.env.NEXT_PUBLIC_SITE_URL ?? ""}/api/auth/me`,
      { credentials: "include" },
    );
    if (!me.ok) return null;
    const data = (await me.json()) as { access_token?: string };
    return data.access_token ?? null;
  } catch {
    return null;
  }
}

interface AuthedFetchOpts {
  method?: string;
  body?: string;
  headers?: Record<string, string>;
}

/**
 * Make an authenticated request to the backend, refreshing the access
 * token once if the first attempt 401s. Returns:
 *   - `{ ok: true, data, response }` on success
 *   - `{ ok: false, status, message }` on failure (message is the
 *     extracted backend error string, never a generic "Failed to …")
 */
export async function authedBackendFetch<T>(
  req: NextRequest,
  endpoint: string,
  opts: AuthedFetchOpts = {},
): Promise<
  | { ok: true; data: T; response: NextResponse }
  | { ok: false; status: number; message: string }
> {
  const baseHeaders = opts.headers ?? {};
  const fetchOpts: BackendFetchOptions = {
    method: opts.method,
    body: opts.body,
    headers: { ...baseHeaders, ...authHeaders(req) },
  };

  try {
    const data = await backendFetch<T>(endpoint, fetchOpts);
    return { ok: true, data, response: NextResponse.json(data) };
  } catch (error) {
    if (!(error instanceof BackendApiError)) {
      return {
        ok: false,
        status: 500,
        message: "Internal server error — please try again.",
      };
    }

    // Non-401 → surface the real backend message.
    if (error.status !== 401) {
      return {
        ok: false,
        status: error.status,
        message: extractBackendErrorMessage(error.data, "Request failed"),
      };
    }

    // 401 → silent refresh + one retry.
    const fresh = await tryRefreshAccessToken();
    if (!fresh) {
      return {
        ok: false,
        status: 401,
        message: "Your session has expired. Please log in again and retry.",
      };
    }

    try {
      const retryOpts: BackendFetchOptions = {
        method: opts.method,
        body: opts.body,
        headers: { ...baseHeaders, Authorization: `Bearer ${fresh}` },
      };
      const data = await backendFetch<T>(endpoint, retryOpts);
      const response = NextResponse.json(data);
      response.cookies.set("access_token", fresh, ACCESS_COOKIE_OPTS);
      return { ok: true, data, response };
    } catch (retryError) {
      if (retryError instanceof BackendApiError) {
        return {
          ok: false,
          status: retryError.status,
          message: extractBackendErrorMessage(
            retryError.data,
            "Failed to save — please try again.",
          ),
        };
      }
      return {
        ok: false,
        status: 500,
        message: "Internal server error after token refresh.",
      };
    }
  }
}
