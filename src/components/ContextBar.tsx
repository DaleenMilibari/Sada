import type { ReactNode } from 'react';
import { Pin } from 'lucide-react';

export function Segmented<T extends string | number>({
  options, value, onChange,
}: { options: { key: T; label: string }[]; value: T; onChange: (v: T) => void }) {
  return (
    <div className="flex items-center gap-1 bg-slate-100 p-1 rounded-xl">
      {options.map((o) => (
        <button
          key={String(o.key)}
          onClick={() => onChange(o.key)}
          className={`px-3 py-1 rounded-lg text-xs font-bold font-arabic transition-all cursor-pointer ${
            value === o.key ? 'bg-white text-slate-900 shadow-2xs' : 'text-slate-600 hover:text-slate-900'
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

// Page filters, pinned under the app header while scrolling, with one line naming exactly what every
// number below is computed over - so a reader deep in the page still knows the platform and period.
export function ContextBar({ title, scope, detail, controls }: {
  title?: string;
  scope: string; // e.g. "يوتيوب · آخر 30 يوماً"
  detail?: ReactNode; // counts / freshness, shown after the scope
  controls: ReactNode;
}) {
  return (
    <div className="sticky top-16 z-30 -mx-7 px-7 py-3 bg-slate-50/95 backdrop-blur-md border-b border-slate-200/80">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          {title && <h2 className="text-sm font-bold text-slate-900 font-arabic">{title}</h2>}
          <p className="flex flex-wrap items-center gap-1.5 text-[11px] text-slate-500 font-arabic">
            <Pin className="w-3 h-3 text-emerald-700" />
            <span>الأرقام أدناه:</span>
            <strong className="text-emerald-800 bg-emerald-50 border border-emerald-200 rounded-full px-2 py-px">{scope}</strong>
            {detail && <span>· {detail}</span>}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">{controls}</div>
      </div>
    </div>
  );
}

// A card's own scope, shown when it differs from the page filters (e.g. always the full history).
export function ScopeTag({ children, fixed = false }: { children: ReactNode; fixed?: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1 text-[10px] font-bold font-arabic rounded-full px-2 py-0.5 border whitespace-nowrap ${
        fixed ? 'bg-amber-50 text-amber-800 border-amber-200' : 'bg-slate-50 text-slate-600 border-slate-200'
      }`}
      title={fixed ? 'هذا القسم لا يتبع فلتر الفترة أعلاه' : undefined}
    >
      {children}
    </span>
  );
}
