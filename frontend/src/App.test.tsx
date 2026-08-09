import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'

describe('App', () => {
  afterEach(() => vi.restoreAllMocks())

  it('restores an authenticated session and navigates', async () => {
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify([]), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
    const user = userEvent.setup()
    render(<App />)

    expect(await screen.findByRole('heading', { name: 'What can we help you solve?' })).toBeVisible()

    await user.click(screen.getByRole('button', { name: 'Knowledge' }))

    expect(screen.getByRole('heading', { name: 'Knowledge base' })).toBeVisible()
  })

  it('logs in without writing credentials to Web Storage', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            error: { code: 'authentication_required', message: 'Authentication required', request_id: 'one' },
          }),
          { status: 401, headers: { 'Content-Type': 'application/json' } },
        ),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
    const storageWrite = vi.spyOn(Storage.prototype, 'setItem')
    const user = userEvent.setup()
    render(<App />)

    await user.type(await screen.findByLabelText('Shared password'), 'reviewer-password')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByRole('heading', { name: 'What can we help you solve?' })).toBeVisible()
    expect(fetchMock).toHaveBeenLastCalledWith(
      '/auth/session',
      expect.objectContaining({ credentials: 'include', method: 'POST' }),
    )
    expect(storageWrite).not.toHaveBeenCalled()
    await waitFor(() => expect(screen.queryByLabelText('Shared password')).not.toBeInTheDocument())
  })

  it('logs out and returns to the password view', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'Sign out' }))

    expect(await screen.findByLabelText('Shared password')).toBeVisible()
    expect(fetchMock).toHaveBeenLastCalledWith(
      '/auth/session',
      expect.objectContaining({ credentials: 'include', method: 'DELETE' }),
    )
  })
})
