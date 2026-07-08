import { CloudSun } from "lucide-react";

export function Logo() {
  return (
    <div className="logo" aria-label="SkyCast">
      <span className="logoMark">
        <CloudSun size={32} strokeWidth={2.2} />
      </span>
      <span className="logoText">
        Sky<span>Cast</span>
      </span>
    </div>
  );
}
