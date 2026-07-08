import { AlertTriangle, CloudOff, Loader2 } from "lucide-react";

export function SkeletonGrid({ cards = 4 }: { cards?: number }) {
  return (
    <div className="skeletonGrid" aria-label="Загрузка">
      {Array.from({ length: cards }).map((_, index) => (
        <div className="skeletonCard" key={index}>
          <span />
          <strong />
          <p />
          <p />
        </div>
      ))}
    </div>
  );
}

export function LoadingPanel({ text = "Загружаем данные" }: { text?: string }) {
  return (
    <div className="statePanel">
      <Loader2 className="spin" size={22} />
      <span>{text}</span>
    </div>
  );
}

export function EmptyState({ title, text }: { title: string; text: string }) {
  return (
    <div className="statePanel">
      <CloudOff size={24} />
      <strong>{title}</strong>
      <span>{text}</span>
    </div>
  );
}

export function ErrorState({ title = "Ошибка загрузки", text }: { title?: string; text: string }) {
  return (
    <div className="statePanel stateError">
      <AlertTriangle size={24} />
      <strong>{title}</strong>
      <span>{text}</span>
    </div>
  );
}
