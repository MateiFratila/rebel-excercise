import { useEffect, useState } from 'react'
import { ApiError, type ApiClient, type EmbeddingJob } from '../api/client'

export type TrackedJob = EmbeddingJob & { collectionId: string }

const terminalStatuses = new Set(['completed', 'partially_failed', 'failed'])

export function useEmbeddingJobs(
  client: Pick<ApiClient, 'getEmbeddingJob'>,
  onSessionExpired: () => void,
) {
  const [jobs, setJobs] = useState<TrackedJob[]>([])
  const [pollError, setPollError] = useState<string | null>(null)
  const pendingIds = jobs
    .filter((job) => !terminalStatuses.has(job.status))
    .map((job) => job.job_id)
    .sort()
    .join(',')

  useEffect(() => {
    const jobIds = pendingIds ? pendingIds.split(',') : []
    if (jobIds.length === 0) return

    let cancelled = false
    let delay = 500
    let timer: number | undefined

    async function poll() {
      try {
        const updates = await Promise.all(jobIds.map((jobId) => client.getEmbeddingJob(jobId)))
        if (cancelled) return
        setJobs((current) =>
          current.map((tracked) => {
            const update = updates.find((job) => job.job_id === tracked.job_id)
            return update ? { ...update, collectionId: tracked.collectionId } : tracked
          }),
        )
        setPollError(null)
        if (updates.some((job) => !terminalStatuses.has(job.status))) {
          delay = Math.min(delay * 2, 5000)
          timer = window.setTimeout(poll, delay)
        }
      } catch (error) {
        if (cancelled) return
        if (error instanceof ApiError && error.status === 401) onSessionExpired()
        setPollError('Job status is temporarily unavailable.')
        delay = Math.min(delay * 2, 5000)
        timer = window.setTimeout(poll, delay)
      }
    }

    timer = window.setTimeout(poll, delay)
    return () => {
      cancelled = true
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [client, onSessionExpired, pendingIds])

  function trackJob(job: EmbeddingJob, collectionId: string) {
    setJobs((current) => [
      { ...job, collectionId },
      ...current.filter((existing) => existing.job_id !== job.job_id),
    ])
  }

  return { jobs, pollError, trackJob }
}
