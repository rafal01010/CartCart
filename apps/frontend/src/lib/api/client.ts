import { buildApiUrl, getBackendBaseUrl } from './config.js';
import { ApiError, apiErrorFromResponse } from './errors.js';
import type {
	CreateRefinementRequest,
	CreateGuidedSessionRequest,
	CreateSessionRequest,
	CreateUserAddedProductRequest,
	GuidedAnswerSubmission,
	GuidedIntakeState,
	GuidedReanswerRequest,
	GuidedSessionResponse,
	RefinementRunResponse,
	RegionSetupSubmission,
	RunId,
	SessionId,
	SessionResultsResponse,
	SessionStateResponse,
	ShoppingRunRecord,
	UpdateShoppingBriefRequest,
} from './types.js';

export type FetchLike = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export interface ApiClientOptions {
	baseUrl?: string;
	fetch?: FetchLike;
	requestId?: string;
}

export class CartCartApiClient {
	readonly baseUrl: string;
	private readonly fetchImpl: FetchLike;
	private readonly requestId: string | undefined;

	constructor(options: ApiClientOptions = {}) {
		this.baseUrl = options.baseUrl ?? getBackendBaseUrl();
		this.fetchImpl = options.fetch ?? fetch.bind(globalThis);
		this.requestId = options.requestId;
	}

	createSession(request: CreateSessionRequest): Promise<SessionStateResponse> {
		return this.request('/api/sessions', {
			method: 'POST',
			body: request,
		});
	}

	createGuidedSession(request: CreateGuidedSessionRequest): Promise<GuidedSessionResponse> {
		return this.request('/api/sessions/guided', {
			method: 'POST',
			body: request,
		});
	}

	getSession(sessionId: SessionId): Promise<SessionStateResponse> {
		return this.request(`/api/sessions/${encodeURIComponent(sessionId)}`);
	}

	getGuideState(sessionId: SessionId): Promise<GuidedIntakeState> {
		return this.request(`/api/sessions/${encodeURIComponent(sessionId)}/guide`);
	}

	submitGuidedAnswer(
		sessionId: SessionId,
		request: GuidedAnswerSubmission,
	): Promise<GuidedIntakeState> {
		return this.request(`/api/sessions/${encodeURIComponent(sessionId)}/answers`, {
			method: 'POST',
			body: request,
		});
	}

	skipGuidedQuestion(sessionId: SessionId): Promise<GuidedIntakeState> {
		return this.request(`/api/sessions/${encodeURIComponent(sessionId)}/guide/skip`, {
			method: 'POST',
		});
	}

	skipAllGuidedQuestions(sessionId: SessionId): Promise<GuidedIntakeState> {
		return this.request(`/api/sessions/${encodeURIComponent(sessionId)}/guide/skip-all`, {
			method: 'POST',
		});
	}

	reanswerGuidedQuestion(
		sessionId: SessionId,
		request: GuidedReanswerRequest,
	): Promise<GuidedIntakeState> {
		return this.request(`/api/sessions/${encodeURIComponent(sessionId)}/guide/reanswer`, {
			method: 'POST',
			body: request,
		});
	}

	submitGuidedRegionSetup(
		sessionId: SessionId,
		request: RegionSetupSubmission,
	): Promise<GuidedIntakeState> {
		return this.request(`/api/sessions/${encodeURIComponent(sessionId)}/guide/region`, {
			method: 'POST',
			body: request,
		});
	}

	updateSessionBrief(
		sessionId: SessionId,
		request: UpdateShoppingBriefRequest,
	): Promise<SessionStateResponse> {
		return this.request(`/api/sessions/${encodeURIComponent(sessionId)}/brief`, {
			method: 'PATCH',
			body: request,
		});
	}

	addUserProduct(
		sessionId: SessionId,
		request: CreateUserAddedProductRequest,
	): Promise<SessionStateResponse> {
		return this.request(`/api/sessions/${encodeURIComponent(sessionId)}/products`, {
			method: 'POST',
			body: request,
		});
	}

	createRun(sessionId: SessionId): Promise<ShoppingRunRecord> {
		return this.request(`/api/sessions/${encodeURIComponent(sessionId)}/runs`, {
			method: 'POST',
		});
	}

	getRun(sessionId: SessionId, runId: RunId): Promise<ShoppingRunRecord> {
		return this.request(
			`/api/sessions/${encodeURIComponent(sessionId)}/runs/${encodeURIComponent(runId)}`,
		);
	}

	getResults(sessionId: SessionId): Promise<SessionResultsResponse> {
		return this.request(`/api/sessions/${encodeURIComponent(sessionId)}/results`);
	}

	createRefinement(
		sessionId: SessionId,
		request: CreateRefinementRequest,
	): Promise<RefinementRunResponse> {
		return this.request(`/api/sessions/${encodeURIComponent(sessionId)}/refinements`, {
			method: 'POST',
			body: request,
		});
	}

	runEventsUrl(sessionId: SessionId, runId: RunId): string {
		return buildRunEventsUrl(sessionId, runId, this.baseUrl);
	}

	private async request<T>(
		path: string,
		options: { method?: string; body?: unknown } = {},
	): Promise<T> {
		const headers = new Headers({
			Accept: 'application/json',
		});
		if (options.body !== undefined) {
			headers.set('Content-Type', 'application/json');
		}
		if (this.requestId) {
			headers.set('X-Request-ID', this.requestId);
		}

		let response: Response;
		try {
			response = await this.fetchImpl(buildApiUrl(path, this.baseUrl), {
				method: options.method ?? 'GET',
				headers,
				body: options.body === undefined ? undefined : JSON.stringify(options.body),
			});
		} catch (error) {
			throw new ApiError({
				status: 0,
				code: 'network_error',
				message: error instanceof Error ? error.message : 'Network request failed.',
			});
		}

		if (!response.ok) {
			throw await apiErrorFromResponse(response);
		}

		if (response.status === 204) {
			return undefined as T;
		}

		return (await response.json()) as T;
	}
}

export function buildRunEventsUrl(sessionId: SessionId, runId: RunId, baseUrl?: string): string {
	return buildApiUrl(
		`/api/sessions/${encodeURIComponent(sessionId)}/runs/${encodeURIComponent(runId)}/events`,
		baseUrl,
	);
}

export function createApiClient(options?: ApiClientOptions): CartCartApiClient {
	return new CartCartApiClient(options);
}
