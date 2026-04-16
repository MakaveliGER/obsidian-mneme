/** Mneme plugin settings stored in Obsidian's data.json */
export interface MnemeSettings {
  // Basic
  mnemePath: string;
  autoSearchMode: "off" | "smart" | "always";
  searchTopK: number;

  // Embedding
  embeddingDevice: "auto" | "cpu" | "cuda";
  embeddingDtype: "float16" | "bfloat16" | "float32";
  embeddingModel: string;
  embeddingBatchSize: number;

  // Chunking
  chunkMaxTokens: number;
  chunkOverlapTokens: number;

  // Search
  vectorWeight: number;
  bm25Weight: number;

  // Reranking
  rerankingEnabled: boolean;
  rerankingThreshold: number;

  // GARS
  garsEnabled: boolean;
  graphWeight: number;

  // Auto-Search
  hookMatchers: string[];

  // Query Expansion
  queryExpansion: boolean;

  // Server & Sync
  autoStartServer: boolean;
  reindexOnStart: boolean;
  reindexOnClose: boolean;

  // Health
  healthExcludePatterns: string[];

  // UI state
  showAdvanced: boolean;
}

export const DEFAULT_SETTINGS: MnemeSettings = {
  mnemePath: "mneme",
  autoSearchMode: "smart",
  searchTopK: 10,

  embeddingDevice: "auto",
  embeddingDtype: "float16",
  embeddingModel: "BAAI/bge-m3",
  embeddingBatchSize: 32,

  chunkMaxTokens: 1000,
  chunkOverlapTokens: 100,

  vectorWeight: 0.6,
  bm25Weight: 0.4,

  rerankingEnabled: false,
  rerankingThreshold: 0.3,

  garsEnabled: false,
  graphWeight: 0.3,

  hookMatchers: ["Read"],
  queryExpansion: false,
  autoStartServer: true,
  reindexOnStart: true,
  reindexOnClose: false,
  healthExcludePatterns: [],

  showAdvanced: false,
};

/** Search result from Mneme backend */
export interface SearchResult {
  path: string;
  title: string;
  heading_path: string;
  content: string;
  score: number;
  tags: string[];
}

/** Vault stats from Mneme backend */
export interface VaultStats {
  total_notes: number;
  total_chunks: number;
  last_indexed: string;
  embedding_model: string;
  db_size_mb: number;
}

/** Reindex result from Mneme backend */
export interface ReindexResult {
  indexed: number;
  skipped: number;
  deleted: number;
  duration_seconds: number;
}

/** Health report from Mneme backend */
export interface HealthReport {
  orphan_pages?: Array<{ path: string; title: string }>;
  weakly_linked?: Array<{
    path: string;
    title: string;
    suggestions: Array<{ path: string; title: string; score: number }>;
  }>;
  stale_notes?: Array<{ path: string; title: string; days_stale: number }>;
  near_duplicates?: Array<{
    path_a: string;
    path_b: string;
    similarity: number;
  }>;
}

/** Mneme config as returned by get-config */
export interface MnemeConfig {
  vault: { path: string; glob_patterns: string[]; exclude_patterns: string[] };
  embedding: {
    provider: string;
    model: string;
    device: string;
    batch_size: number;
    dtype: string;
  };
  chunking: { strategy: string; max_tokens: number; overlap_tokens: number };
  search: { vector_weight: number; bm25_weight: number; top_k: number };
  reranking: {
    enabled: boolean;
    model: string;
    top_k: number;
    threshold: number;
  };
  scoring: { gars_enabled: boolean; graph_weight: number };
  auto_search: {
    mode: string;
    claude_md_path: string;
    hook_matchers: string[];
  };
  health: { exclude_patterns: string[] };
}
