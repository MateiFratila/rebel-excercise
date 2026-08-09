import { type FormEvent, useState } from 'react'
import { ArrowUp, BookOpen, ShieldCheck, Sparkles } from 'lucide-react'
import {
  ApiError,
  type AnswerResult,
  type AnswerSource,
  type ApiClient,
} from '../api/client'

const sourceDetails: Record<AnswerSource, { label: string; icon: typeof BookOpen }> = {
  local: { label: 'Knowledge base', icon: BookOpen },
  openai: { label: 'Support assistant', icon: Sparkles },
  compliance: { label: 'Scope policy', icon: ShieldCheck },
}

type AskViewProps = {
  client: Pick<ApiClient, 'askQuestion'>
  onSessionExpired: () => void
}

export function AskView({ client, onSessionExpired }: AskViewProps) {
  const [question, setQuestion] = useState('')
  const [result, setResult] = useState<AnswerResult | null>(null)
  const [error, setError] = useState<{ message: string; requestId: string | null } | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  async function submitQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const userQuestion = question.trim()
    if (!userQuestion || isLoading) return

    setIsLoading(true)
    setResult(null)
    setError(null)

    try {
      setResult(await client.askQuestion(userQuestion))
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) onSessionExpired()
      setError({
        message:
          caught instanceof ApiError
            ? caught.message
            : 'The assistant is unavailable right now. Try again shortly.',
        requestId: caught instanceof ApiError ? caught.requestId : null,
      })
    } finally {
      setIsLoading(false)
    }
  }

  const source = result ? sourceDetails[result.data.source] : null
  const SourceIcon = source?.icon

  return (
    <section className="workspace" aria-labelledby="ask-title">
      <div className="workspace-heading">
        <p className="eyebrow">Technical support</p>
        <h1 id="ask-title">What can we help you solve?</h1>
      </div>

      <form className="question-form" onSubmit={submitQuestion}>
        <label htmlFor="question">Your question</label>
        <textarea
          id="question"
          name="question"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Describe the issue, device, or account setting"
          rows={5}
          maxLength={2000}
          required
        />
        <div className="form-footer">
          <span>{question.length} / 2000</span>
          <button type="submit" disabled={!question.trim() || isLoading}>
            <span>{isLoading ? 'Checking' : 'Ask support'}</span>
            <ArrowUp size={18} aria-hidden="true" />
          </button>
        </div>
      </form>

      <div className="answer-region" aria-live="polite" aria-busy={isLoading}>
        {isLoading && (
          <div className="answer-loading">
            <span />
            <span />
            <span />
          </div>
        )}
        {error && (
          <div className="response-error" role="alert">
            <p>{error.message}</p>
            {error.requestId && <small>Request {error.requestId}</small>}
          </div>
        )}
        {result && source && SourceIcon && (
          <article className={`answer answer-${result.data.source}`}>
            <div className="answer-meta">
              <span>
                <SourceIcon size={14} aria-hidden="true" />
                {source.label}
              </span>
              {result.data.matched_question && <p>{result.data.matched_question}</p>}
            </div>
            <p>{result.data.answer}</p>
            {result.requestId && <small className="request-id">Request {result.requestId}</small>}
          </article>
        )}
      </div>
    </section>
  )
}
