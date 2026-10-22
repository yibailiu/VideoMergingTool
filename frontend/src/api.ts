export async function api<T = any>(
  path: string,
  payload?: unknown,
): Promise<T> {
  const response = await fetch(path, {
    method: payload === undefined ? "GET" : "POST",
    headers: {
      "Content-Type": "application/json",
      "X-VideoMergingTool-Token": window.__VMT__.token,
    },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  const result = await response.json();
  if (!response.ok || result.error)
    throw new Error(result.error || result.message || response.statusText);
  return result;
}
