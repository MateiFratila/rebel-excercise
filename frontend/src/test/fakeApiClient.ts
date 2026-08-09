import type { ApiClient } from '../api/client'

export function fakeApiClient(overrides: Partial<ApiClient> = {}): ApiClient {
  return {
    session: async () => true,
    login: async () => undefined,
    logout: async () => undefined,
    askQuestion: async () => ({
      data: { source: 'compliance', matched_question: null, answer: 'Unavailable' },
      requestId: null,
    }),
    listCollections: async () => [],
    createCollection: async () => { throw new Error('Not implemented') },
    collectionReadiness: async () => ({ ready: false, active_items: 0, pending_items: 0 }),
    listItems: async () => [],
    importItems: async () => ({ changed_count: 0 }),
    updateItem: async (_collectionId, item) => item,
    deactivateItem: async () => { throw new Error('Not implemented') },
    queueEmbeddingJob: async () => { throw new Error('Not implemented') },
    getEmbeddingJob: async () => { throw new Error('Not implemented') },
    activateCollection: async () => { throw new Error('Not implemented') },
    ...overrides,
  }
}
