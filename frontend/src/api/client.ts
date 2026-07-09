import type {
  AnalyticsSummaryResponse,
  AuthTokenResponse,
  ForecastCoverageResponse,
  ForecastRunsResponse,
  Metric,
  Source,
  StationDetailsResponse,
  StationSeriesResponse,
  StationsResponse,
  TopErrorsResponse,
  User,
  WorstStationsResponse
} from "../types";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

export const authStorage = {
  token: "skycast.token",
  expiresAt: "skycast.expiresAt"
};

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : `Не удалось получить ответ сервиса. Код: ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

type QueryValue = string | number | boolean | null | undefined;
type QueryParams = Record<string, QueryValue>;

function buildUrl(path: string, params?: QueryParams) {
  const url = new URL(`${API_BASE_URL}${path}`, window.location.origin);
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, String(value));
    }
  });
  return url.toString();
}

async function request<T>(path: string, options: RequestInit = {}, params?: QueryParams): Promise<T> {
  const token = localStorage.getItem(authStorage.token);
  const headers = new Headers(options.headers);

  if (!(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(buildUrl(path, params), {
    ...options,
    headers
  });

  if (response.status === 204) {
    return undefined as T;
  }

  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();

  if (!response.ok) {
    const detail =
      typeof payload === "object" && payload
        ? payload.detail
        : typeof payload === "string" && payload.trim()
          ? payload
          : response.status >= 500
            ? "Сервис недоступен. Проверьте, что backend запущен, и повторите попытку."
            : `Не удалось получить ответ сервиса. Код: ${response.status}`;
    if (response.status === 401) {
      localStorage.removeItem(authStorage.token);
      localStorage.removeItem(authStorage.expiresAt);
      window.dispatchEvent(new CustomEvent("skycast:unauthorized"));
    }
    throw new ApiError(response.status, detail);
  }

  return payload as T;
}

export const api = {
  register(payload: { email: string; full_name: string; password: string }) {
    return request<User>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify(payload)
    });
  },
  login(payload: { email: string; password: string }) {
    return request<AuthTokenResponse>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify(payload)
    });
  },
  logout() {
    return request<void>("/api/auth/logout", { method: "POST" });
  },
  me() {
    return request<User>("/api/auth/me");
  },
  stations(params?: { limit?: number; with_coordinates_only?: boolean; missing_coordinates_only?: boolean }) {
    return request<StationsResponse>("/api/stations", {}, params);
  },
  stationDetails(stationId: number) {
    return request<StationDetailsResponse>(`/api/stations/${stationId}/details`);
  },
  forecastRuns(params?: {
    limit?: number;
    status?: string;
    model?: string;
    source?: Source;
    horizon_days?: number;
  }) {
    return request<ForecastRunsResponse>("/api/forecast-runs", {}, params);
  },
  summary(params: {
    start_date: string;
    end_date: string;
    model?: string;
    source?: Source;
    horizon_days?: number;
    only_with_coordinates?: boolean;
  }) {
    return request<AnalyticsSummaryResponse>("/api/analytics/summary", {}, params);
  },
  topErrors(params: {
    start_date: string;
    end_date: string;
    metric?: Metric;
    limit?: number;
    model?: string;
    source?: Source;
    horizon_days?: number;
    only_with_coordinates?: boolean;
  }) {
    return request<TopErrorsResponse>("/api/analytics/top-errors", {}, params);
  },
  worstStations(params: {
    start_date: string;
    end_date: string;
    metric?: Metric;
    limit?: number;
    model?: string;
    source?: Source;
    horizon_days?: number;
  }) {
    return request<WorstStationsResponse>("/api/analytics/worst-stations", {}, params);
  },
  stationSeries(params: {
    start_date: string;
    end_date: string;
    station_id?: number;
    wmo_index?: string;
    model?: string;
    source?: Source;
    horizon_days?: number;
    include_forecast?: boolean;
  }) {
    return request<StationSeriesResponse>("/api/analytics/station-series", {}, params);
  },
  forecastCoverage(params?: {
    start_date?: string;
    end_date?: string;
    model?: string;
    source?: Source;
    horizon_days?: number;
  }) {
    return request<ForecastCoverageResponse>("/api/analytics/forecast-coverage", {}, params);
  },
  coverage() {
    return request<Record<string, number | string | null>>("/api/analytics/coverage");
  }
};

export function formatApiError(error: unknown) {
  if (error instanceof ApiError) {
    return humanError(error.detail);
  }
  if (error instanceof Error) {
    return humanError(error.message);
  }
  return "Не удалось выполнить запрос.";
}

function humanError(detail: unknown) {
  const text = typeof detail === "string" ? detail : JSON.stringify(detail);
  const normalized = text.toLowerCase();
  if (normalized.includes("invalid email or password")) {
    return "Неверная почта или пароль.";
  }
  if (normalized.includes("password must be at least")) {
    return "Пароль должен быть не короче 8 символов.";
  }
  if (normalized.includes("password must be at most")) {
    return "Пароль слишком длинный.";
  }
  if (normalized.includes("already") && normalized.includes("email")) {
    return "Аккаунт с такой почтой уже существует.";
  }
  if (normalized.includes("unauthorized") || normalized.includes("not authenticated")) {
    return "Войдите в аккаунт еще раз.";
  }
  if (normalized.includes("failed to fetch")) {
    return "Не удалось связаться с сервисом. Проверьте подключение и попробуйте снова.";
  }
  if (normalized.includes("econnrefused") || normalized.includes("socket hang up") || normalized.includes("backend")) {
    return "Сервис недоступен. Проверьте, что backend запущен, и повторите попытку.";
  }
  return text || "Не удалось выполнить запрос.";
}
