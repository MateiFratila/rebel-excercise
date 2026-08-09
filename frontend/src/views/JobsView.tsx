import { Activity, AlertTriangle, CheckCircle2, Clock3, XCircle } from 'lucide-react'
import type { TrackedJob } from '../hooks/useEmbeddingJobs'

const statusIcon = {
  queued: Clock3,
  running: Activity,
  completed: CheckCircle2,
  partially_failed: AlertTriangle,
  failed: XCircle,
} as const

export function JobsView({ jobs, pollError }: { jobs: TrackedJob[]; pollError: string | null }) {
  return (
    <section className="workspace workspace-wide" aria-labelledby="jobs-title">
      <div className="workspace-heading compact-heading">
        <p className="eyebrow">Embedding pipeline</p>
        <h1 id="jobs-title">Jobs</h1>
      </div>
      {pollError && <p className="inline-alert">{pollError}</p>}
      {jobs.length === 0 ? (
        <div className="empty-state">
          <Activity size={28} aria-hidden="true" />
          <h2>No embedding jobs</h2>
          <p>Jobs started in this session will appear here.</p>
        </div>
      ) : (
        <div className="job-list">
          {jobs.map((job) => {
            const StatusIcon = statusIcon[job.status]
            const completed = job.processed_count + job.failed_count
            const progress =
              job.requested_count === 0 ? 100 : (completed / job.requested_count) * 100
            return (
              <article className="job-row" key={job.job_id}>
                <StatusIcon size={20} aria-hidden="true" />
                <div className="job-main">
                  <div className="job-heading">
                    <strong>{job.status.replace('_', ' ')}</strong>
                    <span>
                      {completed} / {job.requested_count}
                    </span>
                  </div>
                  <div className="progress-track" aria-label={`${Math.round(progress)}% complete`}>
                    <span style={{ width: `${Math.min(progress, 100)}%` }} />
                  </div>
                  {job.error_summary && <p>{job.error_summary}</p>}
                </div>
                <time dateTime={job.created_at}>
                  {new Date(job.created_at).toLocaleTimeString()}
                </time>
              </article>
            )
          })}
        </div>
      )}
    </section>
  )
}
