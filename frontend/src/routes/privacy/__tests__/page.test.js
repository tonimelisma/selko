// @ts-nocheck
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';

const { default: PrivacyPage } = await import('../+page.svelte');

describe('Privacy Policy Page', () => {
	it('renders without a signed-in user', () => {
		render(PrivacyPage);

		expect(screen.getByRole('heading', { level: 1, name: /privacy policy/i })).toBeInTheDocument();
	});

	it('carries the Google Limited Use disclosure', () => {
		render(PrivacyPage);

		// Google's OAuth review looks for this disclosure and the policy link.
		expect(screen.getByText(/including the Limited Use requirements/i)).toBeInTheDocument();
		expect(
			screen.getByRole('link', { name: /google api services user data policy/i })
		).toHaveAttribute('href', 'https://developers.google.com/terms/api-services-user-data-policy');
	});

	it('names every service provider that handles user data', () => {
		render(PrivacyPage);

		for (const provider of ['Supabase:', 'Render:', 'Anthropic:', 'Google:', 'Microsoft:']) {
			expect(screen.getByText(provider)).toBeInTheDocument();
		}
	});

	it('gives a way to request deletion', () => {
		render(PrivacyPage);

		const contacts = screen.getAllByRole('link', { name: 'toni.melisma@gmail.com' });
		expect(contacts[0]).toHaveAttribute('href', 'mailto:toni.melisma@gmail.com');
	});
});
