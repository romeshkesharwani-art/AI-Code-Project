export type Policy = {
  id: string;
  name?: string;
  policy_name?: string;
  filename?: string;
  category?: string;
  carrier?: string;
  status?: string;
  version?: number | string;
  policy_series_id?: string;
  effective_date?: string;
  expires_date?: string;
  created_at?: string;
};

export type PolicyListResponse = {
  items: Policy[];
  total: number;
  page: number;
  page_size: number;
};

export type IngestSourcesResponse = {
  ingested: number;
  skipped: number;
  failed: number;
  skipped_files: Array<string | { filename?: string; file?: string; path?: string }>;
  failed_files: Array<string | { filename?: string; file?: string; path?: string }>;
};

export type PolicyFilters = {
  category?: string;
  status?: string;
  carrier?: string;
  search?: string;
};

export type SearchFilters = {
  category?: string;
  carrier?: string;
  policy_id?: string;
};

export type SearchResult = {
  chunk_id: string;
  document_id: string;
  policy_name: string;
  filename: string;
  category: string;
  carrier: string;
  section: string;
  page_number: number;
  content: string;
  similarity_score: number;
};

export type SearchResponse = {
  query: string;
  results: SearchResult[];
  total: number;
};

export type AnswerResponse = {
  answer: string;
  abstained: boolean;
  sources: SearchResult[];
  query: string;
};
