// @ts-nocheck
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';

const { default: PrivacyPage } = await import('../+page.svelte');

describe('Privacy Policy Page', () => {
	// Validates: SEL-735
	it('renders without a signed-in user', () => {
		render(PrivacyPage);

		expect(screen.getByRole('heading', { level: 1, name: /privacy policy/i })).toBeInTheDocument();
	});

	// Validates: SEL-738
	it('carries the Google Limited Use disclosure', () => {
		render(PrivacyPage);

		// Google's OAuth review looks for this disclosure and the policy link.
		expect(screen.getByText(/including the Limited Use requirements/i)).toBeInTheDocument();
		expect(
			screen.getByRole('link', { name: /google api services user data policy/i })
		).toHaveAttribute('href', 'https://developers.google.com/terms/api-services-user-data-policy');
	});

	// Validates: SEL-736
	it('names every service provider that handles user data', () => {
		render(PrivacyPage);

		for (const provider of ['Google Cloud:', 'Anthropic:', 'Google:', 'Microsoft:']) {
			expect(screen.getByText(provider)).toBeInTheDocument();
		}
	});

	// Validates: SEL-736
	it('names no provider Selko no longer uses', () => {
		const { container } = render(PrivacyPage);

		// Selko runs on its own server with its own database and sign-in.
		for (const gone of ['Supabase', 'Render']) {
			expect(container.textContent).not.toContain(gone);
		}
	});

	// Validates: SEL-737
	it('names no AI provider besides Anthropic', () => {
		const { container } = render(PrivacyPage);

		// Production runs Claude only (LLM_FALLBACK_PROVIDER=none); a backup
		// model must be added here before it is configured.
		expect(container.textContent).not.toMatch(/gemini|qwen|openai|alibaba/i);
	});

	// Validates: SEL-739
	it('gives a way to request deletion', () => {
		render(PrivacyPage);

		const contacts = screen.getAllByRole('link', { name: 'toni.melisma@gmail.com' });
		expect(contacts[0]).toHaveAttribute('href', 'mailto:toni.melisma@gmail.com');
	});
});
