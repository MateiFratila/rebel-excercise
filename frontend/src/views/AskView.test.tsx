import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ApiError, type ApiClient } from '../api/client'
import { AskView } from './AskView'

describe('AskView', () => {
  it('renders a canonical local answer with its request ID', async () => {
    const askQuestion = vi.fn<Pick<ApiClient, 'askQuestion'>['askQuestion']>().mockResolvedValue({
      data: {
        source: 'local',
        matched_question: 'How can I restore my account settings?',
        answer: "Go to settings and click on 'restore default'.",
      },
      requestId: 'request-local',
    })
    const user = userEvent.setup()
    render(<AskView client={{ askQuestion }} onSessionExpired={vi.fn()} />)

    await user.type(screen.getByLabelText('Your question'), 'How do I reset my account?')
    await user.click(screen.getByRole('button', { name: 'Ask support' }))

    expect(await screen.findByText("Go to settings and click on 'restore default'.")).toBeVisible()
    expect(screen.getByText('How can I restore my account settings?')).toBeVisible()
    expect(screen.getByText('Knowledge base')).toBeVisible()
    expect(screen.getByText('Request request-local')).toBeVisible()
  })

  it('renders the compliance route without a matched question', async () => {
    const askQuestion = vi.fn<Pick<ApiClient, 'askQuestion'>['askQuestion']>().mockResolvedValue({
      data: {
        source: 'compliance',
        matched_question: null,
        answer: 'This is not really what I was trained for, therefore I cannot answer. Try again.',
      },
      requestId: 'request-compliance',
    })
    const user = userEvent.setup()
    render(<AskView client={{ askQuestion }} onSessionExpired={vi.fn()} />)

    await user.type(screen.getByLabelText('Your question'), 'Write a poem')
    await user.click(screen.getByRole('button', { name: 'Ask support' }))

    expect(await screen.findByText('Scope policy')).toBeVisible()
    expect(screen.queryByText('How can I restore my account settings?')).not.toBeInTheDocument()
  })

  it('shows a safe API error and expires an invalid session', async () => {
    const askQuestion = vi
      .fn<Pick<ApiClient, 'askQuestion'>['askQuestion']>()
      .mockRejectedValue(new ApiError(401, 'authentication_required', 'Authentication required', 'request-401'))
    const onSessionExpired = vi.fn()
    const user = userEvent.setup()
    render(<AskView client={{ askQuestion }} onSessionExpired={onSessionExpired} />)

    await user.type(screen.getByLabelText('Your question'), 'Help')
    await user.click(screen.getByRole('button', { name: 'Ask support' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Authentication required')
    expect(screen.getByText('Request request-401')).toBeVisible()
    expect(onSessionExpired).toHaveBeenCalledOnce()
  })
})
