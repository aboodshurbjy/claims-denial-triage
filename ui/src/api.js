const BASE = "/api";

async function request(path, options) {
  const response = await fetch(BASE + path, options);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      // keep the status text
    }
    throw new Error(`${response.status}: ${detail}`);
  }
  return response.json();
}

export const fetchQueue = (workStatus) => request(`/queue?work_status=${workStatus}`);

export const fetchClaim = (claimId) => request(`/claims/${encodeURIComponent(claimId)}`);

export const postAction = (claimId, action, note) =>
  request(`/claims/${encodeURIComponent(claimId)}/actions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, note: note || null }),
  });
