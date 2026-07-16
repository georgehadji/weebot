import { NextRequest, NextResponse } from "next/server";

const API_BASE = process.env.BACKEND_URL || "http://localhost:8000/api";

async function handler(
  request: NextRequest, 
  { params }: { params: { path?: string[] } }
) {
  const path = params.path?.join("/") || "";
  const url = new URL(request.url);
  const searchParams = url.search;
  
  const targetUrl = `${API_BASE}/${path}${searchParams}`;
  
  try {
    // Forward auth headers from the client request
    const proxyHeaders: Record<string, string> = {
      "Content-Type": "application/json",
    };
    const apiKey = request.headers.get("x-api-key");
    if (apiKey) {
      proxyHeaders["X-API-Key"] = apiKey;
    }

    const response = await fetch(targetUrl, {
      method: request.method,
      headers: proxyHeaders,
      body: request.method !== "GET" && request.method !== "HEAD" 
        ? await request.text() 
        : undefined,
    });

    const data = await response.json().catch(() => null);
    
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    console.error("API proxy error:", error);
    return NextResponse.json(
      { error: "Failed to connect to backend. Make sure the backend is running on port 8000" },
      { status: 503 }
    );
  }
}

export const GET = handler;
export const POST = handler;
export const PUT = handler;
export const DELETE = handler;
export const PATCH = handler;
