import type {
  AnswerResponse,
  IngestSourcesResponse,
  Policy,
  PolicyFilters,
  PolicyListResponse,
  SearchFilters,
  SearchResponse,
} from "@/types/policy";
import type {
  CustomerFilters,
  CustomerList,
  CustomerStats,
  DashboardStats,
} from "@/types/customer";

const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001/api/v1"
).replace(/\/+$/, "");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, init);
  } catch {
    throw new Error(
      `Unable to reach the policy API at ${API_BASE_URL}. Check that the backend is running and NEXT_PUBLIC_API_URL is correct.`,
    );
  }

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed (${response.status})`);
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function queryString(values: PolicyFilters) {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  const query = params.toString();
  return query ? `?${query}` : "";
}

export async function getPolicies(filters: PolicyFilters = {}) {
  const data = await request<Policy[] | PolicyListResponse | { policies: Policy[]; total?: number }>(
    `/policies${queryString(filters)}`,
  );
  if (Array.isArray(data)) return data;
  if ("items" in data) return data.items;
  return data.policies;
}

export function getCustomers(filters: CustomerFilters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== "") params.set(key, String(value));
  });
  const query = params.toString();
  return request<CustomerList>(`/customers${query ? `?${query}` : ""}`);
}

export function getCustomerStats() {
  return request<CustomerStats>("/customers/stats");
}

export function getDashboardStats() {
  return request<DashboardStats>("/policies/dashboard/stats");
}

export function ingestSources() {
  return request<IngestSourcesResponse>("/policies/ingest-sources", {
    method: "POST",
  });
}

export function getPolicy(id: string) {
  return request<Policy>(`/policies/${encodeURIComponent(id)}`);
}

export function getPolicyFileUrl(id: string) {
  return `${API_BASE_URL}/policies/${encodeURIComponent(id)}/file`;
}

export function archivePolicy(id: string) {
  return request<void>(`/policies/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export function uploadPolicy(
  file: File,
  fields: {
    name?: string;
    category?: string;
    carrier?: string;
    effective_date?: string;
    expires_date?: string;
  },
) {
  const formData = new FormData();
  formData.append("file", file);
  Object.entries(fields).forEach(([key, value]) => {
    if (value) formData.append(key, value);
  });
  return request<Policy>("/policies/upload", { method: "POST", body: formData });
}

export function searchPolicies(
  query: string,
  topK: number,
  filters: SearchFilters,
) {
  return request<SearchResponse>("/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, top_k: topK, filters }),
  });
}

export function answerQuestion(
  query: string,
  topK: number,
  filters: SearchFilters,
) {
  return request<AnswerResponse>("/answer", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, top_k: topK, filters }),
  });
}
