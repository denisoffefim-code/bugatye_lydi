import type { Metric, Source } from "./types";

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
    return "любой источник";
  }
  return source === "previous_runs" ? "прошлые прогнозы" : "новые прогнозы";
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
