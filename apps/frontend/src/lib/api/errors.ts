import type { ErrorEnvelope, JsonValue } from './types.js';

export class ApiError extends Error {
	readonly status: number;
	readonly code: string;
	readonly requestId: string | null;
	readonly details: JsonValue | undefined;
	readonly envelope: ErrorEnvelope | null;

	constructor(params: {
		status: number;
		message: string;
		code?: string;
		requestId?: string | null;
		details?: JsonValue;
		envelope?: ErrorEnvelope | null;
	}) {
		super(params.message);
		this.name = 'ApiError';
		this.status = params.status;
		this.code = params.code ?? `http_${params.status}`;
		this.requestId = params.requestId ?? null;
		this.details = params.details;
		this.envelope = params.envelope ?? null;
	}
}

export async function apiErrorFromResponse(response: Response): Promise<ApiError> {
	const requestId = response.headers.get('x-request-id');
	const envelope = await readErrorEnvelope(response);
	if (envelope) {
		return new ApiError({
			status: response.status,
			message: envelope.error.message,
			code: envelope.error.code,
			requestId: envelope.error.request_id || requestId,
			details: envelope.error.details,
			envelope,
		});
	}

	return new ApiError({
		status: response.status,
		message: response.statusText || `Request failed with HTTP ${response.status}.`,
		requestId,
	});
}

async function readErrorEnvelope(response: Response): Promise<ErrorEnvelope | null> {
	try {
		const body: unknown = await response.json();
		if (isErrorEnvelope(body)) {
			return body;
		}
	} catch {
		return null;
	}

	return null;
}

function isErrorEnvelope(value: unknown): value is ErrorEnvelope {
	if (!value || typeof value !== 'object' || !('error' in value)) {
		return false;
	}

	const error = (value as { error: unknown }).error;
	if (!error || typeof error !== 'object') {
		return false;
	}

	return (
		typeof (error as { code?: unknown }).code === 'string' &&
		typeof (error as { message?: unknown }).message === 'string' &&
		typeof (error as { request_id?: unknown }).request_id === 'string'
	);
}
