import { type FormEvent, type ReactNode, useCallback, useEffect, useState } from 'react'
import {
  Archive,
  BookOpen,
  Braces,
  Check,
  DatabaseZap,
  FilePenLine,
  Plus,
  RefreshCw,
  Upload,
  X,
} from 'lucide-react'
import {
  ApiError,
  type ApiClient,
  type Collection,
  type CollectionReadiness,
  type EmbeddingJob,
  type FAQItem,
  type FAQItemInput,
} from '../api/client'
import type { TrackedJob } from '../hooks/useEmbeddingJobs'

type KnowledgeViewProps = {
  client: ApiClient
  jobs: TrackedJob[]
  onJobQueued: (job: EmbeddingJob, collectionId: string) => void
  onSessionExpired: () => void
}

type EditorState = { mode: 'create'; item: FAQItemInput } | { mode: 'edit'; item: FAQItem }

const emptyItem: FAQItemInput = {
  question: '',
  answer: '',
  category: '',
  source_metadata: {},
}

export function KnowledgeView({
  client,
  jobs,
  onJobQueued,
  onSessionExpired,
}: KnowledgeViewProps) {
  const [collections, setCollections] = useState<Collection[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [items, setItems] = useState<FAQItem[]>([])
  const [readiness, setReadiness] = useState<CollectionReadiness | null>(null)
  const [revision, setRevision] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [operation, setOperation] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [showImport, setShowImport] = useState(false)
  const [editor, setEditor] = useState<EditorState | null>(null)
  const [importText, setImportText] = useState('')

  const handleError = useCallback(
    (caught: unknown, fallback: string) => {
      if (caught instanceof ApiError && caught.status === 401) onSessionExpired()
      setError(caught instanceof ApiError ? caught.message : fallback)
    },
    [onSessionExpired],
  )

  useEffect(() => {
    let cancelled = false
    client
      .listCollections()
      .then((loaded) => {
        if (cancelled) return
        setCollections(loaded)
        if (loaded.length === 0) {
          setItems([])
          setReadiness(null)
        }
        setSelectedId((current) => {
          if (current && loaded.some((collection) => collection.id === current)) return current
          return (
            loaded.find((collection) => collection.status === 'active')?.id ??
            loaded[0]?.id ??
            null
          )
        })
        setError(null)
      })
      .catch((caught) => handleError(caught, 'Collections are temporarily unavailable.'))
      .finally(() => {
        if (!cancelled) setIsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [client, handleError, revision])

  useEffect(() => {
    if (!selectedId) return
    let cancelled = false
    Promise.all([client.listItems(selectedId), client.collectionReadiness(selectedId)])
      .then(([loadedItems, loadedReadiness]) => {
        if (cancelled) return
        setItems(loadedItems)
        setReadiness(loadedReadiness)
        setError(null)
      })
      .catch((caught) => handleError(caught, 'Collection details are temporarily unavailable.'))
    return () => {
      cancelled = true
    }
  }, [client, handleError, selectedId, revision])

  const selected = collections.find((collection) => collection.id === selectedId) ?? null
  const selectedJobStatus = jobs.find((job) => job.collectionId === selectedId)?.status

  useEffect(() => {
    if (
      !selectedId ||
      !selectedJobStatus ||
      !['completed', 'partially_failed', 'failed'].includes(selectedJobStatus)
    ) return
    let cancelled = false
    Promise.all([
      client.listCollections(),
      client.listItems(selectedId),
      client.collectionReadiness(selectedId),
    ]).then(([loadedCollections, loadedItems, loadedReadiness]) => {
      if (cancelled) return
      setCollections(loadedCollections)
      setItems(loadedItems)
      setReadiness(loadedReadiness)
    }).catch((caught) => handleError(caught, 'Collection details are temporarily unavailable.'))
    return () => {
      cancelled = true
    }
  }, [client, handleError, selectedId, selectedJobStatus])

  async function createCollection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    setOperation('create')
    setError(null)
    try {
      const created = await client.createCollection({
        name: String(form.get('name') ?? '').trim(),
        embedding_model: String(form.get('embedding_model') ?? ''),
        embedding_dimensions: Number(form.get('embedding_dimensions')),
      })
      setSelectedId(created.id)
      setShowCreate(false)
      setNotice(`Created ${created.name} v${created.version}.`)
      setRevision((value) => value + 1)
    } catch (caught) {
      handleError(caught, 'The collection could not be created.')
    } finally {
      setOperation(null)
    }
  }

  async function importItems() {
    if (!selectedId) return
    setOperation('import')
    setError(null)
    try {
      const records = parseImport(JSON.parse(importText) as unknown)
      const result = await client.importItems(selectedId, records)
      setShowImport(false)
      setImportText('')
      setNotice(`${result.changed_count} item${result.changed_count === 1 ? '' : 's'} changed.`)
      setRevision((value) => value + 1)
    } catch (caught) {
      if (caught instanceof SyntaxError || caught instanceof TypeError) {
        setError('Import JSON must contain valid FAQ records.')
      } else {
        handleError(caught, 'The import could not be completed.')
      }
    } finally {
      setOperation(null)
    }
  }

  async function saveItem(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selectedId || !editor) return
    const form = new FormData(event.currentTarget)
    const values: FAQItemInput = {
      question: String(form.get('question') ?? '').trim(),
      answer: String(form.get('answer') ?? '').trim(),
      category: String(form.get('category') ?? '').trim(),
      source_metadata: editor.item.source_metadata,
    }
    setOperation('item')
    setError(null)
    try {
      if (editor.mode === 'create') await client.importItems(selectedId, [values])
      else await client.updateItem(selectedId, { ...editor.item, ...values })
      setEditor(null)
      setNotice(editor.mode === 'create' ? 'FAQ item added.' : 'FAQ item updated.')
      setRevision((value) => value + 1)
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        const refreshed = await Promise.all([
            client.listItems(selectedId),
            client.collectionReadiness(selectedId),
          ]).catch(() => null)
        if (refreshed) {
          const [loadedItems, loadedReadiness] = refreshed
          setItems(loadedItems)
          setReadiness(loadedReadiness)
        }
        setError('This item changed elsewhere. Close and reopen it before retrying.')
      } else {
        handleError(caught, 'The FAQ item could not be saved.')
      }
    } finally {
      setOperation(null)
    }
  }

  async function deactivate(item: FAQItem) {
    if (!selectedId || !window.confirm(`Deactivate “${item.question}”?`)) return
    setOperation(item.id)
    try {
      await client.deactivateItem(selectedId, item.id)
      setNotice('FAQ item deactivated.')
      setRevision((value) => value + 1)
    } catch (caught) {
      handleError(caught, 'The FAQ item could not be deactivated.')
    } finally {
      setOperation(null)
    }
  }

  async function queueJob() {
    if (!selectedId) return
    setOperation('embedding')
    try {
      const job = await client.queueEmbeddingJob(selectedId)
      onJobQueued(job, selectedId)
      setNotice(
        job.status === 'completed' ? 'Embeddings are already current.' : 'Embedding job queued.',
      )
      setRevision((value) => value + 1)
    } catch (caught) {
      handleError(caught, 'The embedding job could not be started.')
    } finally {
      setOperation(null)
    }
  }

  async function activate() {
    if (!selectedId) return
    setOperation('activate')
    try {
      await client.activateCollection(selectedId)
      setNotice('Collection activated.')
      setRevision((value) => value + 1)
    } catch (caught) {
      handleError(caught, 'The collection is not ready for activation.')
    } finally {
      setOperation(null)
    }
  }

  return (
    <section className="workspace workspace-wide" aria-labelledby="knowledge-title">
      <div className="workspace-heading admin-heading">
        <div>
          <p className="eyebrow">Administration</p>
          <h1 id="knowledge-title">Knowledge base</h1>
        </div>
        <button className="secondary-button" type="button" onClick={() => setShowCreate(true)}>
          <Plus size={17} aria-hidden="true" /> New collection
        </button>
      </div>
      {error && <p className="inline-alert" role="alert">{error}</p>}
      {notice && <p className="inline-notice" role="status">{notice}</p>}

      {isLoading ? (
        <div className="empty-state"><RefreshCw className="spin" size={25} aria-hidden="true" /></div>
      ) : collections.length === 0 ? (
        <div className="empty-state">
          <BookOpen size={28} aria-hidden="true" /><h2>No collections yet</h2>
          <button className="text-button" type="button" onClick={() => setShowCreate(true)}>Create collection</button>
        </div>
      ) : selected ? (
        <>
          <div className="collection-toolbar">
            <label htmlFor="collection">Collection</label>
            <select id="collection" value={selected.id} onChange={(event) => setSelectedId(event.target.value)}>
              {collections.map((collection) => (
                <option value={collection.id} key={collection.id}>{collection.name} · v{collection.version}</option>
              ))}
            </select>
            <span className={`status-badge status-${selected.status}`}>{selected.status}</span>
            <div className="toolbar-actions">
              <button type="button" title="Import JSON" onClick={() => setShowImport(true)}><Upload size={17} /></button>
              <button type="button" title="Add FAQ" onClick={() => setEditor({ mode: 'create', item: emptyItem })}><Plus size={17} /></button>
              <button type="button" title="Embed updates" disabled={operation !== null} onClick={queueJob}><DatabaseZap size={17} /></button>
              <button type="button" className="activate-button" disabled={!readiness?.ready || operation !== null} onClick={activate}><Check size={17} /> Activate</button>
            </div>
          </div>
          <div className="readiness-strip">
            <Metric value={readiness?.active_items ?? 0} label="Active items" />
            <Metric value={readiness?.pending_items ?? 0} label="Pending vectors" />
            <Metric value={selected.embedding_dimensions} label="Dimensions" />
            <Metric value={selectedJobStatus?.replace('_', ' ') ?? 'idle'} label="Latest job" />
          </div>
          {items.length === 0 ? (
            <div className="empty-state compact-empty">
              <Braces size={26} aria-hidden="true" /><h2>No FAQ items</h2>
              <button className="text-button" type="button" onClick={() => setShowImport(true)}>Import JSON</button>
            </div>
          ) : (
            <div className="item-list">
              {items.map((item) => (
                <article className={item.is_active ? 'item-row' : 'item-row inactive'} key={item.id}>
                  <div className="item-copy">
                    <div className="item-meta"><span>{item.category}</span>{!item.is_active && <span>Inactive</span>}</div>
                    <h2>{item.question}</h2><p>{item.answer}</p>
                  </div>
                  <div className="row-actions">
                    <button type="button" title="Edit FAQ" onClick={() => setEditor({ mode: 'edit', item })}><FilePenLine size={17} /></button>
                    {item.is_active && <button type="button" title="Deactivate FAQ" disabled={operation === item.id} onClick={() => deactivate(item)}><Archive size={17} /></button>}
                  </div>
                </article>
              ))}
            </div>
          )}
        </>
      ) : null}

      {showCreate && (
        <Modal title="New collection" onClose={() => setShowCreate(false)}>
          <form className="dialog-form" onSubmit={createCollection}>
            <label>Name<input name="name" required maxLength={200} autoFocus /></label>
            <label>Embedding model<select name="embedding_model" defaultValue="text-embedding-3-small"><option>text-embedding-3-small</option><option>text-embedding-3-large</option></select></label>
            <label>Dimensions<input name="embedding_dimensions" type="number" min="1" max="3072" defaultValue="1536" required /></label>
            <button className="primary-button" type="submit" disabled={operation === 'create'}>Create collection</button>
          </form>
        </Modal>
      )}
      {showImport && (
        <Modal title="Import FAQ JSON" onClose={() => setShowImport(false)}>
          <label className="field-label" htmlFor="import-json">FAQ records</label>
          <textarea id="import-json" className="json-input" value={importText} onChange={(event) => setImportText(event.target.value)} autoFocus />
          <button className="primary-button" type="button" disabled={!importText.trim() || operation === 'import'} onClick={importItems}>Import records</button>
        </Modal>
      )}
      {editor && (
        <Modal title={editor.mode === 'create' ? 'Add FAQ' : 'Edit FAQ'} onClose={() => setEditor(null)}>
          <form className="dialog-form" onSubmit={saveItem}>
            <label>Question<textarea name="question" defaultValue={editor.item.question} maxLength={4000} required autoFocus /></label>
            <label>Answer<textarea name="answer" defaultValue={editor.item.answer} maxLength={16000} required /></label>
            <label>Category<input name="category" defaultValue={editor.item.category} maxLength={100} required /></label>
            <button className="primary-button" type="submit" disabled={operation === 'item'}>{editor.mode === 'create' ? 'Add FAQ' : 'Save changes'}</button>
          </form>
        </Modal>
      )}
    </section>
  )
}

function Metric({ value, label }: { value: string | number; label: string }) {
  return <div><strong>{value}</strong><span>{label}</span></div>
}

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
      <section className="dialog" role="dialog" aria-modal="true" aria-labelledby="dialog-title">
        <header><h2 id="dialog-title">{title}</h2><button type="button" title="Close" onClick={onClose}><X size={18} /></button></header>
        {children}
      </section>
    </div>
  )
}

function parseImport(value: unknown): FAQItemInput[] {
  const records = Array.isArray(value)
    ? value
    : isRecord(value) && Array.isArray(value.knowledge_base_items)
      ? value.knowledge_base_items
      : isRecord(value) && Array.isArray(value.items)
        ? value.items
        : null
  if (!records || records.length === 0) throw new TypeError('FAQ records are required')
  return records.map((record) => {
    if (
      !isRecord(record) ||
      typeof record.question !== 'string' ||
      typeof record.answer !== 'string' ||
      typeof record.category !== 'string'
    ) {
      throw new TypeError('Invalid FAQ record')
    }
    return {
      question: record.question,
      answer: record.answer,
      category: record.category,
      source_metadata: isRecord(record.source_metadata) ? record.source_metadata : {},
    }
  })
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}
