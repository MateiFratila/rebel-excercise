export type AnswerSource = 'local' | 'openai' | 'compliance'
export type CollectionStatus = 'draft' | 'embedding' | 'ready' | 'active' | 'archived'
export type EmbeddingJobStatus =
  | 'queued'
  | 'running'
  | 'completed'
  | 'partially_failed'
  | 'failed'

export type AskQuestionResponse = {
  source: AnswerSource
  matched_question: string | null
  answer: string
}

export type CollectionReadiness = {
  ready: boolean
  active_items: number
  pending_items: number
}

export type Collection = {
  id: string
  name: string
  version: number
  status: CollectionStatus
  embedding_model: string
  embedding_dimensions: number
  created_at: string
  updated_at: string
  readiness: CollectionReadiness
}

export type FAQItemInput = {
  question: string
  answer: string
  category: string
  source_metadata: Record<string, unknown>
}

export type FAQItem = FAQItemInput & {
  id: string
  collection_id: string
  is_active: boolean
  embedding_model: string | null
  embedded_at: string | null
  created_at: string
  updated_at: string
}

export type EmbeddingJob = {
  job_id: string
  status: EmbeddingJobStatus
  requested_count: number
  processed_count: number
  failed_count: number
  error_summary: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
}

type ErrorResponse = {
  error: {
    code: string
    message: string
    request_id: string
  }
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly requestId: string | null

  constructor(
    status: number,
    code: string,
    message: string,
    requestId: string | null,
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.requestId = requestId
  }
}

export type AnswerResult = {
  data: AskQuestionResponse
  requestId: string | null
}

export interface ApiClient {
  session(): Promise<boolean>
  login(password: string): Promise<void>
  logout(): Promise<void>
  askQuestion(question: string): Promise<AnswerResult>
  listCollections(): Promise<Collection[]>
  createCollection(input: {
    name: string
    embedding_model: string
    embedding_dimensions: number
  }): Promise<Collection>
  collectionReadiness(collectionId: string): Promise<CollectionReadiness>
  listItems(collectionId: string): Promise<FAQItem[]>
  importItems(collectionId: string, items: FAQItemInput[]): Promise<{ changed_count: number }>
  updateItem(collectionId: string, item: FAQItem): Promise<FAQItem>
  deactivateItem(collectionId: string, itemId: string): Promise<FAQItem>
  queueEmbeddingJob(collectionId: string): Promise<EmbeddingJob>
  getEmbeddingJob(jobId: string): Promise<EmbeddingJob>
  activateCollection(collectionId: string): Promise<Collection>
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body !== undefined) headers.set('Content-Type', 'application/json')
  const response = await fetch(path, { ...init, credentials: 'include', headers })

  if (!response.ok) {
    let body: ErrorResponse | null = null
    try {
      body = (await response.json()) as ErrorResponse
    } catch {
      // The server contract is JSON, but proxy and network failures may not be.
    }
    throw new ApiError(
      response.status,
      body?.error.code ?? 'request_failed',
      body?.error.message ?? 'The request could not be completed.',
      body?.error.request_id ?? response.headers.get('X-Request-ID'),
    )
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const apiClient: ApiClient = {
  async session() {
    try {
      await request<void>('/auth/session')
      return true
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) return false
      throw error
    }
  },
  login: (password) =>
    request<void>('/auth/session', {
      method: 'POST',
      body: JSON.stringify({ password }),
    }),
  logout: () => request<void>('/auth/session', { method: 'DELETE' }),
  async askQuestion(question) {
    const headers = new Headers({ 'Content-Type': 'application/json' })
    const response = await fetch('/ask-question', {
      method: 'POST',
      credentials: 'include',
      headers,
      body: JSON.stringify({ user_question: question }),
    })
    if (!response.ok) {
      let body: ErrorResponse | null = null
      try {
        body = (await response.json()) as ErrorResponse
      } catch {
        // Preserve the same safe fallback as the shared request path.
      }
      throw new ApiError(
        response.status,
        body?.error.code ?? 'request_failed',
        body?.error.message ?? 'The request could not be completed.',
        body?.error.request_id ?? response.headers.get('X-Request-ID'),
      )
    }
    return {
      data: (await response.json()) as AskQuestionResponse,
      requestId: response.headers.get('X-Request-ID'),
    }
  },
  listCollections: () => request<Collection[]>('/admin/collections'),
  createCollection: (input) =>
    request<Collection>('/admin/collections', {
      method: 'POST',
      body: JSON.stringify(input),
    }),
  collectionReadiness: (collectionId) =>
    request<CollectionReadiness>(`/admin/collections/${collectionId}/readiness`),
  listItems: (collectionId) =>
    request<FAQItem[]>(`/admin/collections/${collectionId}/items`),
  importItems: (collectionId, items) =>
    request<{ changed_count: number }>(`/admin/collections/${collectionId}/items`, {
      method: 'POST',
      body: JSON.stringify({ items }),
    }),
  updateItem: (collectionId, item) =>
    request<FAQItem>(`/admin/collections/${collectionId}/items/${item.id}`, {
      method: 'PATCH',
      body: JSON.stringify({
        question: item.question,
        answer: item.answer,
        category: item.category,
        source_metadata: item.source_metadata,
        expected_updated_at: item.updated_at,
      }),
    }),
  deactivateItem: (collectionId, itemId) =>
    request<FAQItem>(`/admin/collections/${collectionId}/items/${itemId}`, {
      method: 'DELETE',
    }),
  queueEmbeddingJob: (collectionId) =>
    request<EmbeddingJob>(`/admin/collections/${collectionId}/embedding-jobs`, {
      method: 'POST',
    }),
  getEmbeddingJob: (jobId) => request<EmbeddingJob>(`/admin/jobs/${jobId}`),
  activateCollection: (collectionId) =>
    request<Collection>(`/admin/collections/${collectionId}/activate`, { method: 'POST' }),
}
