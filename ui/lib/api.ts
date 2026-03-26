"use client";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const API_KEY = process.env.NEXT_PUBLIC_API_KEY || "dynafit_dev_secret_key_123";

class DynafitAPI {
  private baseUrl: string;

  constructor(baseUrl: string = API_URL) {
    this.baseUrl = baseUrl;
  }

  private async request<T>(path: string, options?: RequestInit): Promise<T> {
    const headers: Record<string, string> = {
      "x-api-key": API_KEY,
      ...((options?.headers as Record<string, string>) || {}),
    };
    // Only set Content-Type to JSON if there's no body or the body is a string (JSON)
    if (!options?.body || typeof options.body === "string") {
      headers["Content-Type"] = "application/json";
    }
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...options,
      headers,
    });
    if (!response.ok) {
      const text = await response.text().catch(() => response.statusText);
      throw new Error(`API Error ${response.status}: ${text}`);
    }
    return response.json();
  }

  // ── Health ────────────────────────────────────────────────────────────

  async checkBackendHealth(): Promise<boolean> {
    try {
      const res = await fetch(`${this.baseUrl}/health`, {
        signal: AbortSignal.timeout(3000),
      });
      if (!res.ok) return false;
      const data = await res.json();
      // Verify it's actually our DYNAFIT backend, not some random service
      return data?.status === "ok";
    } catch {
      return false;
    }
  }

  // ── Run Lifecycle ─────────────────────────────────────────────────────

  async createRun(
    files: File[]
  ): Promise<{ run_id: string; status: string; message: string }> {
    const formData = new FormData();
    for (const f of files) {
      formData.append("files", f);
    }
    const response = await fetch(`${this.baseUrl}/api/v1/runs`, {
      method: "POST",
      body: formData,
      headers: {
        "x-api-key": API_KEY,
      },
    });
    if (!response.ok) {
      const text = await response.text().catch(() => response.statusText);
      throw new Error(`Upload failed (${response.status}): ${text}`);
    }
    return response.json();
  }

  // ── SSE Progress Stream ───────────────────────────────────────────────

  connectToStream(
    runId: string,
    handlers: {
      onPhaseStart?: (phase: string) => void;
      onPhaseComplete?: (phase: string, stats: Record<string, unknown>) => void;
      onPipelinePaused?: (message: string) => void;
      onPipelineComplete?: () => void;
      onPipelineError?: (message: string) => void;
      onState?: (state: unknown) => void;
    }
  ): EventSource {
    const es = new EventSource(
      `${this.baseUrl}/api/v1/runs/${runId}/stream`
    );

    es.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data);

        switch (event.type) {
          case "state":
            handlers.onState?.(event);
            break;
          case "phase_start":
            handlers.onPhaseStart?.(event.phase);
            break;
          case "phase_complete":
            handlers.onPhaseComplete?.(event.phase, event.stats || {});
            break;
          case "pipeline_paused":
            handlers.onPipelinePaused?.(event.message || "Pipeline paused.");
            break;
          case "pipeline_complete":
            handlers.onPipelineComplete?.();
            break;
          case "pipeline_error":
            handlers.onPipelineError?.(event.message || "Pipeline failed.");
            es.close();
            break;
          case "done":
            es.close();
            break;
          case "keepalive":
            break;
        }
      } catch {
        // Ignore parse errors on SSE messages
      }
    };

    es.onerror = () => {
      es.close();
      handlers.onPipelineError?.(
        "Connection lost — is the FastAPI server running at localhost:8000?"
      );
    };

    return es;
  }

  // ── Run Status & Results ──────────────────────────────────────────────

  async getRunStatus(
    runId: string
  ): Promise<{
    run_id: string;
    status: string;
    current_phase: string | null;
    phases: Record<string, { status: string; stats: Record<string, unknown> }>;
  }> {
    return this.request(`/api/v1/runs/${runId}/status`);
  }

  async getRunResults(runId: string): Promise<{
    run_id: string;
    atoms: unknown[];
    classificationResults: unknown[];
    llmCostUsd: number;
    humanReviewRequired: string[];
  }> {
    return this.request(`/api/v1/runs/${runId}/results`);
  }

  // ── Human Review ──────────────────────────────────────────────────────

  async getReviewItems(runId: string): Promise<unknown> {
    return this.request(`/api/v1/runs/${runId}/review`);
  }

  async submitReview(runId: string, payload: Record<string, unknown>): Promise<unknown> {
    return this.request(`/api/v1/runs/${runId}/review`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  }

  // ── Export ────────────────────────────────────────────────────────────

  async downloadFitmentMatrix(runId: string): Promise<Blob> {
    const response = await fetch(
      `${this.baseUrl}/api/v1/runs/${runId}/export`
    );
    if (!response.ok) throw new Error("Export failed — file may not be generated yet.");
    return response.blob();
  }
}

export const api = new DynafitAPI();
export default api;
