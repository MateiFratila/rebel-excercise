import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, type EmbeddingJob } from '../api/client'
import { useEmbeddingJobs } from './useEmbeddingJobs'

const queued: EmbeddingJob = {
  job_id: 'job-1',
  status: 'queued',
  requested_count: 2,
  processed_count: 0,
  failed_count: 0,
  error_summary: null,
  created_at: '2026-08-09T12:00:00Z',
  started_at: null,
  completed_at: null,
}

describe('useEmbeddingJobs', () => {
  afterEach(() => vi.useRealTimers())

  it('polls a queued job to its terminal state', async () => {
    vi.useFakeTimers()
    const getEmbeddingJob = vi.fn().mockResolvedValue({
      ...queued,
      status: 'completed',
      processed_count: 2,
      completed_at: '2026-08-09T12:01:00Z',
    })
    const { result } = renderHook(() =>
      useEmbeddingJobs({ getEmbeddingJob }, vi.fn()),
    )

    act(() => result.current.trackJob(queued, 'collection-1'))
    await act(async () => vi.advanceTimersByTimeAsync(500))

    expect(result.current.jobs[0]?.status).toBe('completed')
    expect(getEmbeddingJob).toHaveBeenCalledWith('job-1')
  })

  it('expires unauthorized sessions and retries with bounded backoff', async () => {
    vi.useFakeTimers()
    const onSessionExpired = vi.fn()
    const getEmbeddingJob = vi
      .fn()
      .mockRejectedValue(new ApiError(401, 'unauthorized', 'Authentication required.', 'auth-1'))
    const client = { getEmbeddingJob }
    const { result } = renderHook(() => useEmbeddingJobs(client, onSessionExpired))

    act(() => result.current.trackJob(queued, 'collection-1'))
    await act(async () => vi.advanceTimersByTimeAsync(500))

    expect(result.current.pollError).toBe('Job status is temporarily unavailable.')
    expect(onSessionExpired).toHaveBeenCalledOnce()
    expect(getEmbeddingJob).toHaveBeenCalledTimes(1)

    await act(async () => vi.advanceTimersByTimeAsync(999))
    expect(getEmbeddingJob).toHaveBeenCalledTimes(1)
    await act(async () => vi.advanceTimersByTimeAsync(1))
    expect(getEmbeddingJob).toHaveBeenCalledTimes(2)
  })
})
