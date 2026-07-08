import type { Metric, Source, StationSeriesItem } from "./types";

export const metricLabels: Record<Metric, string> = {
  avg_temp: "Средняя температура",
  min_temp: "Минимальная температура",
  max_temp: "Максимальная температура",
  precipitation: "Осадки"
};

export const metricUnits: Record<Metric, string> = {
  avg_temp: "°C",
  min_temp: "°C",
  max_temp: "°C",
  precipitation: "мм"
};

export function sourceLabel(source: Source | null | undefined) {
  if (!source) {
    return "все прогнозы";
  }
  return "прогноз";
}

export function statusLabel(status: string | null | undefined) {
  const normalized = (status || "").toLowerCase();
  if (!normalized) {
    return "нет данных";
  }
  if (normalized.includes("success") || normalized.includes("ok") || normalized.includes("done") || normalized.includes("complete")) {
    return "готово";
  }
  if (normalized.includes("partial")) {
    return "частично";
  }
  if (normalized.includes("pending") || normalized.includes("running") || normalized.includes("progress")) {
    return "в работе";
  }
  if (normalized.includes("failed") || normalized.includes("error")) {
    return "ошибка";
  }
  return normalized.replace(/[_-]+/g, " ");
}

export function roleLabel(role: string | null | undefined) {
  const normalized = (role || "").toLowerCase();
  if (normalized === "admin") {
    return "управляет доступом";
  }
  if (normalized === "analyst") {
    return "работает с анализом";
  }
  return "пользователь";
}

export function isPrivilegedRole(role: string | null | undefined) {
  const normalized = (role || "").toLowerCase();
  return normalized === "admin" || normalized === "analyst";
}

export function coverageLabel(key: string) {
  const labels: Record<string, string> = {
    forecast_rows: "Прогнозных записей",
    actual_rows: "Фактических записей",
    weather_rows: "Фактических записей",
    station_count: "Станций",
    stations: "Станций",
    returned: "Показано",
    run_count: "Проверок",
    avg_temp_rows: "Средняя температура",
    min_temp_rows: "Минимальная температура",
    max_temp_rows: "Максимальная температура",
    precipitation_rows: "Осадки",
    max_wind_speed_rows: "Ветер"
  };
  return labels[key] || key.replace(/[_-]+/g, " ");
}

export function defaultRange(days = 30) {
  const end = new Date();
  const start = new Date();
  start.setDate(end.getDate() - days);
  return {
    start: toInputDate(start),
    end: toInputDate(end)
  };
}

export function toInputDate(date: Date) {
  return date.toISOString().slice(0, 10);
}

export function formatDate(value: string | null | undefined) {
  if (!value) {
    return "нет данных";
  }
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "short",
    year: "numeric"
  }).format(new Date(value));
}

export function formatDateTime(value: string | null | undefined) {
  if (!value) {
    return "нет данных";
  }
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

export function formatNumber(value: number | string | null | undefined, digits = 0) {
  if (value === null || value === undefined || value === "") {
    return "нет данных";
  }
  const numeric = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(numeric)) {
    return String(value);
  }
  return new Intl.NumberFormat("ru-RU", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits
  }).format(numeric);
}

export function signed(value: number | null | undefined, unit = "") {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "нет данных";
  }
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${formatNumber(value, 1)}${unit}`;
}

export function isRoleAtLeast(role: string | undefined, target: "viewer" | "analyst" | "admin") {
  const ranks: Record<string, number> = { viewer: 1, user: 1, analyst: 2, admin: 3 };
  return (ranks[(role || "viewer").toLowerCase()] || 0) >= ranks[target];
}

export interface MetricSeriesPoint {
  date: string;
  actual: number | null;
  forecast: number | null;
  error: number | null;
  model: string | null;
  horizonDays: number | null;
  runAt: string | null;
  source: Source | null;
}

const metricSeriesMap: Record<
  Metric,
  {
    actual: keyof StationSeriesItem;
    forecast: keyof StationSeriesItem;
    error: keyof StationSeriesItem;
  }
> = {
  avg_temp: {
    actual: "actual_avg_temp",
    forecast: "forecast_avg_temp",
    error: "error_avg_temp"
  },
  min_temp: {
    actual: "actual_min_temp",
    forecast: "forecast_min_temp",
    error: "error_min_temp"
  },
  max_temp: {
    actual: "actual_max_temp",
    forecast: "forecast_max_temp",
    error: "error_max_temp"
  },
  precipitation: {
    actual: "actual_precipitation",
    forecast: "forecast_precipitation",
    error: "error_precipitation"
  }
};

export function collapseSeriesRows(items: StationSeriesItem[], metric: Metric): MetricSeriesPoint[] {
  const fields = metricSeriesMap[metric];
  const rows: MetricSeriesPoint[] = [];
  const seenDates = new Set<string>();

  for (const item of items) {
    const actual = item[fields.actual] as number | null;
    const forecast = item[fields.forecast] as number | null;
    const error = item[fields.error] as number | null;

    if (actual === null && forecast === null) {
      continue;
    }
    if (seenDates.has(item.observation_date)) {
      continue;
    }

    seenDates.add(item.observation_date);
    rows.push({
      date: item.observation_date,
      actual,
      forecast,
      error,
      model: item.model,
      horizonDays: item.horizon_days,
      runAt: item.run_at,
      source: item.source
    });
  }

  return rows;
}

export function averageAbsoluteError(points: MetricSeriesPoint[]) {
  const values = points
    .map((point) => point.error)
    .filter((value): value is number => value !== null && value !== undefined && !Number.isNaN(value))
    .map((value) => Math.abs(value));

  if (!values.length) {
    return null;
  }

  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

export function maxAbsoluteErrorPoint(points: MetricSeriesPoint[]) {
  const withErrors = points.filter((point) => point.error !== null && point.error !== undefined && !Number.isNaN(point.error));
  if (!withErrors.length) {
    return null;
  }
  return withErrors.reduce((current, point) =>
    Math.abs(Number(point.error)) > Math.abs(Number(current.error)) ? point : current
  );
}

export function biasSummary(bias: number | null | undefined, metric: Metric) {
  if (bias === null || bias === undefined || Number.isNaN(bias)) {
    return "Системное смещение пока не определяется.";
  }

  const absolute = Math.abs(bias);
  const quietThreshold = metric === "precipitation" ? 0.5 : 0.3;

  if (absolute <= quietThreshold) {
    return "Системное смещение почти не заметно.";
  }

  return bias > 0
    ? `Прогноз чаще завышает показатель «${metricLabels[metric].toLowerCase()}».`
    : `Прогноз чаще занижает показатель «${metricLabels[metric].toLowerCase()}».`;
}
