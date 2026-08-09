import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ApiError, type Collection, type EmbeddingJob, type FAQItem } from '../api/client'
import { fakeApiClient } from '../test/fakeApiClient'
import { KnowledgeView } from './KnowledgeView'

const collection: Collection = {
  id: 'collection-1',
  name: 'support',
  version: 1,
  status: 'ready',
  embedding_model: 'text-embedding-3-small',
  embedding_dimensions: 1536,
  created_at: '2026-08-09T12:00:00Z',
  updated_at: '2026-08-09T12:00:00Z',
  readiness: { ready: true, active_items: 1, pending_items: 0 },
}

const item: FAQItem = {
  id: 'item-1',
  collection_id: collection.id,
  question: 'How do I reset my password?',
  answer: 'Open account settings.',
  category: 'account',
  source_metadata: {},
  is_active: true,
  embedding_model: 'text-embedding-3-small',
  embedded_at: '2026-08-09T12:00:00Z',
  created_at: '2026-08-09T12:00:00Z',
  updated_at: '2026-08-09T12:00:00Z',
}

const queuedJob: EmbeddingJob = {
  job_id: 'job-1',
  status: 'queued',
  requested_count: 1,
  processed_count: 0,
  failed_count: 0,
  error_summary: null,
  created_at: '2026-08-09T12:00:00Z',
  started_at: null,
  completed_at: null,
}

function configuredClient(overrides = {}) {
  return fakeApiClient({
    listCollections: vi.fn().mockResolvedValue([collection]),
    listItems: vi.fn().mockResolvedValue([item]),
    collectionReadiness: vi.fn().mockResolvedValue(collection.readiness),
    ...overrides,
  })
}

describe('KnowledgeView', () => {
  it('creates the first collection from the empty state', async () => {
    const createCollection = vi.fn().mockResolvedValue(collection)
    const client = fakeApiClient({
      listCollections: vi.fn().mockResolvedValue([]),
      createCollection,
    })
    const user = userEvent.setup()
    render(
      <KnowledgeView
        client={client}
        jobs={[]}
        onJobQueued={vi.fn()}
        onSessionExpired={vi.fn()}
      />,
    )

    await user.click(await screen.findByRole('button', { name: 'Create collection' }))
    await user.type(screen.getByLabelText('Name'), 'support')
    await user.click(
      within(screen.getByRole('dialog', { name: 'New collection' })).getByRole('button', {
        name: 'Create collection',
      }),
    )

    await waitFor(() =>
      expect(createCollection).toHaveBeenCalledWith({
        name: 'support',
        embedding_model: 'text-embedding-3-small',
        embedding_dimensions: 1536,
      }),
    )
  })

  it('imports source JSON and launches embedding and activation actions', async () => {
    const importItems = vi.fn().mockResolvedValue({ changed_count: 1 })
    const queueEmbeddingJob = vi.fn().mockResolvedValue(queuedJob)
    const activateCollection = vi.fn().mockResolvedValue({ ...collection, status: 'active' })
    const onJobQueued = vi.fn()
    const client = configuredClient({ importItems, queueEmbeddingJob, activateCollection })
    const user = userEvent.setup()
    render(
      <KnowledgeView
        client={client}
        jobs={[]}
        onJobQueued={onJobQueued}
        onSessionExpired={vi.fn()}
      />,
    )

    expect(await screen.findByText('How do I reset my password?')).toBeVisible()
    await user.click(screen.getByTitle('Import JSON'))
    fireEvent.change(screen.getByLabelText('FAQ records'), {
      target: { value: JSON.stringify({
        knowledge_base_items: [
          { question: 'Why is Wi-Fi offline?', answer: 'Restart the router.', category: 'network' },
        ],
      }) },
    })
    await user.click(screen.getByRole('button', { name: 'Import records' }))

    await waitFor(() => expect(importItems).toHaveBeenCalledOnce())
    expect(importItems.mock.calls[0][1][0]).toMatchObject({
      question: 'Why is Wi-Fi offline?',
      source_metadata: {},
    })

    await user.click(screen.getByTitle('Embed updates'))
    await waitFor(() => expect(onJobQueued).toHaveBeenCalledWith(queuedJob, collection.id))
    await user.click(screen.getByRole('button', { name: 'Activate' }))
    await waitFor(() => expect(activateCollection).toHaveBeenCalledWith(collection.id))
  })

  it('keeps the editor open and reports an optimistic update conflict', async () => {
    const updateItem = vi
      .fn()
      .mockRejectedValue(new ApiError(409, 'conflict', 'FAQ item was modified', 'request-conflict'))
    const client = configuredClient({ updateItem })
    const user = userEvent.setup()
    render(
      <KnowledgeView
        client={client}
        jobs={[]}
        onJobQueued={vi.fn()}
        onSessionExpired={vi.fn()}
      />,
    )

    await user.click(await screen.findByTitle('Edit FAQ'))
    await user.clear(screen.getByLabelText('Question'))
    await user.type(screen.getByLabelText('Question'), 'Updated question')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('changed elsewhere')
    expect(screen.getByRole('dialog', { name: 'Edit FAQ' })).toBeVisible()
  })

  it('confirms soft deactivation and expires an unauthorized session', async () => {
    const deactivateItem = vi.fn().mockResolvedValue({ ...item, is_active: false })
    const onSessionExpired = vi.fn()
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const client = configuredClient({ deactivateItem })
    const user = userEvent.setup()
    const { unmount } = render(
      <KnowledgeView
        client={client}
        jobs={[]}
        onJobQueued={vi.fn()}
        onSessionExpired={onSessionExpired}
      />,
    )

    await user.click(await screen.findByTitle('Deactivate FAQ'))
    await waitFor(() => expect(deactivateItem).toHaveBeenCalledWith(collection.id, item.id))
    expect(confirm).toHaveBeenCalledWith('Deactivate “How do I reset my password?”?')
    unmount()

    render(
      <KnowledgeView
        client={fakeApiClient({
          listCollections: vi
            .fn()
            .mockRejectedValue(new ApiError(401, 'unauthorized', 'Authentication required.', 'auth-1')),
        })}
        jobs={[]}
        onJobQueued={vi.fn()}
        onSessionExpired={onSessionExpired}
      />,
    )

    await waitFor(() => expect(onSessionExpired).toHaveBeenCalledOnce())
    expect(screen.getByRole('alert')).toHaveTextContent('Authentication required.')
  })
})
