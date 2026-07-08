import { X } from "lucide-react";

export function Modal({
  title,
  open,
  children,
  onClose
}: {
  title: string;
  open: boolean;
  children: React.ReactNode;
  onClose: () => void;
}) {
  if (!open) {
    return null;
  }

  return (
    <div className="modalOverlay" role="presentation" onMouseDown={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} onMouseDown={(event) => event.stopPropagation()}>
        <div className="modalHeader">
          <h2>{title}</h2>
          <button className="iconButton" type="button" onClick={onClose} aria-label="Закрыть">
            <X size={18} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
