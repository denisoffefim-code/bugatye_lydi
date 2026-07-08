import { statusLabel } from "../utils";

export function StatusBadge({ status }: { status: string | null | undefined }) {
  const normalized = (status || "unknown").toLowerCase();
  const tone =
    normalized.includes("success") || normalized.includes("ok")
      ? "good"
      : normalized.includes("partial") || normalized.includes("pending")
        ? "warn"
        : normalized.includes("failed")
          ? "bad"
          : "neutral";

  return <span className={`statusBadge ${tone}`}>{statusLabel(status)}</span>;
}

export function AccuracyBadge({ value }: { value: number | null }) {
  if (value === null || Number.isNaN(value)) {
    return <span className="statusBadge neutral">нет данных</span>;
  }
  const tone = value <= 1 ? "good" : value <= 3 ? "warn" : "bad";
  const label = tone === "good" ? "точно" : tone === "warn" ? "заметно" : "сильно";
  return <span className={`statusBadge ${tone}`}>{label}</span>;
}
