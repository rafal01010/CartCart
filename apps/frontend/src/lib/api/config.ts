import { env as publicEnv } from '$env/dynamic/public';

export const DEFAULT_BACKEND_BASE_URL = 'http://127.0.0.1:8000';

interface FrontendEnv {
	PUBLIC_CARTCART_API_BASE_URL?: string;
	PUBLIC_CARTCART_BACKEND_URL?: string;
}

export function normalizeBackendBaseUrl(value: string | undefined | null): string {
	const trimmed = value?.trim() ?? '';
	if (!trimmed) {
		return DEFAULT_BACKEND_BASE_URL;
	}

	return trimmed.replace(/\/+$/, '');
}

export function getBackendBaseUrl(env: FrontendEnv = import.meta.env): string {
	return normalizeBackendBaseUrl(
		env.PUBLIC_CARTCART_API_BASE_URL ??
			publicEnv.PUBLIC_CARTCART_API_BASE_URL ??
			env.PUBLIC_CARTCART_BACKEND_URL ??
			publicEnv.PUBLIC_CARTCART_BACKEND_URL,
	);
}

export function buildApiUrl(path: string, baseUrl = getBackendBaseUrl()): string {
	const normalizedBase = `${normalizeBackendBaseUrl(baseUrl)}/`;
	const normalizedPath = path.replace(/^\/+/, '');
	return new URL(normalizedPath, normalizedBase).toString();
}
