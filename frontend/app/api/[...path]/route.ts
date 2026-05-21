import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.BACKEND_URL || "http://server:19777";
const API_KEY = process.env.NEXT_PUBLIC_API_KEY || "admin_dev";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  const pathname = "/api/" + path.join("/");
  const search = request.nextUrl.search;
  const target = `${BACKEND}${pathname}${search}`;

  try {
    const res = await fetch(target, {
      headers: { "X-API-Key": API_KEY },
      cache: "no-store",
    });

    const body = await res.text();
    return new NextResponse(body, {
      status: res.status,
      headers: {
        "Content-Type": res.headers.get("Content-Type") || "application/json",
      },
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: "Proxy failed", message: msg }, { status: 502 });
  }
}
