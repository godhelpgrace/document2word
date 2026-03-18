const corsHeaders = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET,POST,OPTIONS",
  "access-control-allow-headers": "Content-Type,Authorization",
};

function withCors(response) {
  const headers = new Headers(response.headers);
  Object.entries(corsHeaders).forEach(([key, value]) => {
    headers.set(key, value);
  });
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      ...corsHeaders,
    },
  });
}

export async function onRequest(context) {
  const { request, env } = context;
  if (request.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: corsHeaders });
  }

  const backendUrl = env.BACKEND_URL;
  if (!backendUrl) {
    return jsonResponse(
      {
        error: "BACKEND_URL 未配置",
        detail: "请为 Cloudflare Pages Functions 设置 BACKEND_URL 环境变量",
      },
      503
    );
  }

  const incomingUrl = new URL(request.url);
  const base = backendUrl.endsWith("/") ? backendUrl.slice(0, -1) : backendUrl;
  const targetUrl = base + incomingUrl.pathname + incomingUrl.search;
  const headers = new Headers(request.headers);
  headers.delete("host");

  const init = {
    method: request.method,
    headers,
  };

  if (!["GET", "HEAD"].includes(request.method)) {
    init.body = request.body;
  }

  const upstreamResponse = await fetch(targetUrl, init);
  return withCors(upstreamResponse);
}
