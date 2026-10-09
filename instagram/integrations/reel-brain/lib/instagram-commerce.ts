/** Forward authenticated Meta events to the isolated Instagram conversation engine. */
export async function forwardInstagramCommerce(payload: unknown) {
  const backend = process.env.COMMERCE_BACKEND_URL;
  const token = process.env.COMMERCE_API_TOKEN;
  if (!backend || !token) throw new Error("Commerce is not configured");
  const response = await fetch(backend + "/instagram/events", {
    method: "POST",
    headers: { "x-commerce-token": token, "content-type": "application/json" },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(10_000),
  });
  if (!response.ok) throw new Error("Instagram commerce is temporarily unavailable");
  return response.json() as Promise<{ received: boolean; queued: number }>;
}
