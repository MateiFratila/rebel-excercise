import { type FormEvent, useCallback, useEffect, useState } from 'react'
import { Activity, BookOpen, LogOut, MessageSquareText, ShieldCheck } from 'lucide-react'
import { apiClient, type ApiClient } from './api/client'
import { useEmbeddingJobs } from './hooks/useEmbeddingJobs'
import { AskView } from './views/AskView'
import { JobsView } from './views/JobsView'
import { KnowledgeView } from './views/KnowledgeView'
import './App.css'

type View = 'ask' | 'knowledge' | 'jobs'

type SessionState = 'checking' | 'authenticated' | 'unauthenticated'

const navigation = [
  { id: 'ask', label: 'Ask', icon: MessageSquareText },
  { id: 'knowledge', label: 'Knowledge', icon: BookOpen },
  { id: 'jobs', label: 'Jobs', icon: Activity },
] as const

function LoginView({ client, onAuthenticated }: { client: ApiClient; onAuthenticated: () => void }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!password || isSubmitting) return
    setIsSubmitting(true)
    setError(null)
    try {
      await client.login(password)
      setPassword('')
      onAuthenticated()
    } catch {
      setError('The password was not accepted. Try again.')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <main className="login-page">
      <section className="login-panel" aria-labelledby="login-title">
        <div className="brand login-brand" aria-label="Rebel Dot Support">
          <span className="brand-mark">R.</span>
          <span className="brand-name">Support</span>
        </div>
        <p className="eyebrow">Private workspace</p>
        <h1 id="login-title">Sign in to support operations</h1>
        <form className="login-form" onSubmit={submit}>
          <label htmlFor="password">Shared password</label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            maxLength={1024}
            autoFocus
          />
          {error && <p className="error-message">{error}</p>}
          <button type="submit" disabled={!password || isSubmitting}>
            {isSubmitting ? 'Signing in' : 'Sign in'}
            <ShieldCheck size={18} aria-hidden="true" />
          </button>
        </form>
      </section>
    </main>
  )
}

function App({ client = apiClient }: { client?: ApiClient }) {
  const [view, setView] = useState<View>('ask')
  const [session, setSession] = useState<SessionState>('checking')
  const expireSession = useCallback(() => setSession('unauthenticated'), [])
  const { jobs, pollError, trackJob } = useEmbeddingJobs(client, expireSession)

  useEffect(() => {
    let active = true
    client
      .session()
      .then((authenticated) => {
        if (active) setSession(authenticated ? 'authenticated' : 'unauthenticated')
      })
      .catch(() => {
        if (active) setSession('unauthenticated')
      })
    return () => {
      active = false
    }
  }, [client])

  async function logout() {
    try {
      await client.logout()
    } finally {
      setSession('unauthenticated')
      setView('ask')
    }
  }

  if (session === 'checking') {
    return <main className="session-loading" aria-label="Restoring session" />
  }
  if (session === 'unauthenticated') {
    return <LoginView client={client} onAuthenticated={() => setSession('authenticated')} />
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand" aria-label="Rebel Dot Support">
          <span className="brand-mark">R.</span>
          <span className="brand-name">Support</span>
        </div>

        <nav aria-label="Primary navigation">
          {navigation.map(({ id, label, icon: Icon }) => (
            <button
              type="button"
              className={view === id ? 'nav-item active' : 'nav-item'}
              aria-current={view === id ? 'page' : undefined}
              onClick={() => setView(id)}
              key={id}
            >
              <Icon size={19} aria-hidden="true" />
              <span>{label}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="status-line">
            <ShieldCheck size={17} aria-hidden="true" />
            <span>Private session</span>
          </div>
          <button
            type="button"
            className="profile-button"
            aria-label="Sign out"
            title="Sign out"
            onClick={logout}
          >
            <LogOut size={19} aria-hidden="true" />
          </button>
        </div>
      </aside>

      <main>
        {view === 'ask' && (
          <AskView client={client} onSessionExpired={expireSession} />
        )}
        {view === 'knowledge' && (
          <KnowledgeView
            client={client}
            jobs={jobs}
            onJobQueued={trackJob}
            onSessionExpired={expireSession}
          />
        )}
        {view === 'jobs' && <JobsView jobs={jobs} pollError={pollError} />}
      </main>
    </div>
  )
}

export default App
