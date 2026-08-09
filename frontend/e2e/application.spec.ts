import { expect, test, type Page, type Route } from '@playwright/test'

const now = '2026-08-09T12:00:00Z'
const complianceAnswer =
  'This is not really what I was trained for, therefore I cannot answer. Try again.'

type ApiState = {
  imported: boolean
  jobQueued: boolean
  jobCompleted: boolean
  activated: boolean
  password: string | null
}

type FAQItemResponse = {
  id: string
  collection_id: string
  question: string
  answer: string
  category: string
  source_metadata: Record<string, unknown>
  is_active: boolean
  embedding_model: string | null
  embedded_at: string | null
  created_at: string
  updated_at: string
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

async function installApi(page: Page): Promise<ApiState> {
  const state: ApiState = {
    imported: false,
    jobQueued: false,
    jobCompleted: false,
    activated: false,
    password: null,
  }
  const items: FAQItemResponse[] = [
    {
      id: 'item-1',
      collection_id: 'collection-1',
      question: 'How do I reset my password?',
      answer: 'Open account settings.',
      category: 'account',
      source_metadata: {},
      is_active: true,
      embedding_model: 'text-embedding-3-small',
      embedded_at: now,
      created_at: now,
      updated_at: now,
    },
  ]

  function readiness() {
    return {
      ready: state.jobCompleted,
      active_items: items.length,
      pending_items: state.jobCompleted ? 0 : 1,
    }
  }

  function collection() {
    return {
      id: 'collection-1',
      name: 'support',
      version: 1,
      status: state.activated
        ? 'active'
        : state.jobCompleted
          ? 'ready'
          : state.jobQueued
            ? 'embedding'
            : 'draft',
      embedding_model: 'text-embedding-3-small',
      embedding_dimensions: 1536,
      created_at: now,
      updated_at: now,
      readiness: readiness(),
    }
  }

  await page.route('**/auth/session', async (route) => {
    const method = route.request().method()
    if (method === 'POST') {
      state.password = (route.request().postDataJSON() as { password: string }).password
      await route.fulfill({
        status: 204,
        headers: { 'Set-Cookie': 'faq_session=e2e-session; Path=/; HttpOnly; SameSite=Strict' },
      })
      return
    }
    if (method === 'DELETE') {
      await route.fulfill({
        status: 204,
        headers: { 'Set-Cookie': 'faq_session=; Path=/; HttpOnly; Max-Age=0; SameSite=Strict' },
      })
      return
    }
    if (route.request().headers().cookie?.includes('faq_session=e2e-session')) {
      await route.fulfill({ status: 204 })
      return
    }
    await fulfillJson(
      route,
      { error: { code: 'unauthorized', message: 'Authentication required.', request_id: 'auth-1' } },
      401,
    )
  })

  await page.route('**/ask-question', async (route) => {
    const { user_question: question } = route.request().postDataJSON() as {
      user_question: string
    }
    const isMarketing = question.toLowerCase().includes('marketing')
    const isVpn = question.toLowerCase().includes('vpn')
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: { 'X-Request-ID': 'answer-1' },
      body: JSON.stringify(
        isMarketing
          ? { source: 'compliance', matched_question: null, answer: complianceAnswer }
          : {
              source: 'local',
              matched_question: isVpn
                ? 'How do I reconnect the company VPN?'
                : 'How do I reset my password?',
              answer: isVpn ? 'Reconnect from the network menu.' : 'Open account settings.',
            },
      ),
    })
  })

  await page.route('**/admin/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    const method = route.request().method()
    if (path === '/admin/collections') {
      await fulfillJson(route, [collection()])
      return
    }
    if (path.endsWith('/readiness')) {
      await fulfillJson(route, readiness())
      return
    }
    if (path.endsWith('/items') && method === 'GET') {
      await fulfillJson(route, items)
      return
    }
    if (path.endsWith('/items') && method === 'POST') {
      const request = route.request().postDataJSON() as {
        items: Array<{ question: string; answer: string; category: string }>
      }
      const imported = request.items[0]
      items.push({
        ...imported,
        id: 'item-2',
        collection_id: 'collection-1',
        source_metadata: {},
        is_active: true,
        embedding_model: null,
        embedded_at: null,
        created_at: now,
        updated_at: now,
      })
      state.imported = true
      await fulfillJson(route, { changed_count: 1 })
      return
    }
    if (path.endsWith('/items/item-1') && method === 'PATCH') {
      await fulfillJson(
        route,
        { error: { code: 'conflict', message: 'FAQ item was modified.', request_id: 'conflict-1' } },
        409,
      )
      return
    }
    if (path.endsWith('/embedding-jobs') && method === 'POST') {
      state.jobQueued = true
      await fulfillJson(route, {
        job_id: 'job-1',
        status: 'queued',
        requested_count: items.length,
        processed_count: 0,
        failed_count: 0,
        error_summary: null,
        created_at: now,
        started_at: null,
        completed_at: null,
      })
      return
    }
    if (path === '/admin/jobs/job-1') {
      state.jobCompleted = true
      await fulfillJson(route, {
        job_id: 'job-1',
        status: 'completed',
        requested_count: items.length,
        processed_count: items.length,
        failed_count: 0,
        error_summary: null,
        created_at: now,
        started_at: now,
        completed_at: now,
      })
      return
    }
    if (path.endsWith('/activate') && method === 'POST') {
      state.activated = true
      await fulfillJson(route, collection())
      return
    }
    await fulfillJson(
      route,
      { error: { code: 'not_found', message: 'Not found.', request_id: 'missing-1' } },
      404,
    )
  })

  return state
}

async function signIn(page: Page) {
  await page.goto('/')
  await page.getByLabel('Shared password').fill('browser-only-password')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'What can we help you solve?' })).toBeVisible()
}

test('restores an HttpOnly session and presents local and compliance answers', async ({
  page,
  context,
}) => {
  const state = await installApi(page)
  await signIn(page)

  expect(state.password).toBe('browser-only-password')
  const cookie = (await context.cookies()).find((candidate) => candidate.name === 'faq_session')
  expect(cookie).toMatchObject({ value: 'e2e-session', httpOnly: true, sameSite: 'Strict' })

  await page.reload()
  await expect(page.getByRole('heading', { name: 'What can we help you solve?' })).toBeVisible()

  await page.getByLabel('Your question').fill('How can I reset my password?')
  await page.getByRole('button', { name: 'Ask support' }).click()
  await expect(page.getByText('Knowledge base')).toBeVisible()
  await expect(page.getByText('Open account settings.')).toBeVisible()
  await expect(page.getByText('Request answer-1')).toBeVisible()

  await page.getByLabel('Your question').fill('Write a marketing slogan')
  await page.getByRole('button', { name: 'Ask support' }).click()
  await expect(page.getByText('Scope policy')).toBeVisible()
  await expect(page.getByText(complianceAnswer)).toBeVisible()

  const storage = await page.evaluate(() => ({
    local: Object.values(localStorage),
    session: Object.values(sessionStorage),
  }))
  expect(storage).toEqual({ local: [], session: [] })
})

test('imports, embeds, activates, retrieves, handles conflict, and logs out', async ({ page }) => {
  const state = await installApi(page)
  await signIn(page)
  await page.getByRole('button', { name: 'Knowledge' }).click()
  await expect(page.getByRole('heading', { name: 'Knowledge base' })).toBeVisible()

  await page.getByTitle('Import JSON').click()
  await page.getByLabel('FAQ records').fill(
    JSON.stringify([
      {
        question: 'How do I reconnect the company VPN?',
        answer: 'Reconnect from the network menu.',
        category: 'network',
      },
    ]),
  )
  await page.getByRole('button', { name: 'Import records' }).click()
  await expect(page.getByText('1 item changed.')).toBeVisible()
  expect(state.imported).toBe(true)

  await page.getByTitle('Embed updates').click()
  await expect(page.getByText('completed')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Activate', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: 'Activate', exact: true }).click()
  await expect(page.getByText('Collection activated.')).toBeVisible()
  expect(state.activated).toBe(true)

  const item = page.locator('article').filter({ hasText: 'How do I reset my password?' })
  await item.getByTitle('Edit FAQ').click()
  await page.getByLabel('Question').fill('Updated reset question')
  await page.getByRole('button', { name: 'Save changes' }).click()
  await expect(page.getByRole('alert')).toContainText('changed elsewhere')
  await expect(page.getByRole('dialog', { name: 'Edit FAQ' })).toBeVisible()
  await page.getByTitle('Close').click()

  await page.getByRole('button', { name: 'Ask' }).click()
  await page.getByLabel('Your question').fill('How do I reconnect my VPN?')
  await page.getByRole('button', { name: 'Ask support' }).click()
  await expect(page.getByText('Reconnect from the network menu.')).toBeVisible()

  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page.getByLabel('Shared password')).toBeVisible()
  await expect(page.context().cookies()).resolves.not.toContainEqual(
    expect.objectContaining({ name: 'faq_session' }),
  )
})
