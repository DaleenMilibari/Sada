import { useCallback, useEffect, useState } from 'react';
import { ArrowDownRight, ArrowUpRight, Bell, RefreshCw } from 'lucide-react';
import { ApiError, apiFetch, describeError } from '../lib/api';
import type { Alert } from '../types';

const REFRESH_MS = 60_000;
const compact = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 });

interface AlertsPanelProps {
  compact?: boolean;
  days?: number;
  selectedId?: string | null;
  // Full view: clicking an alert hands it to the parent (runs the diagnosis).
  onSelect?: (alert: Alert) => void;
}

const PLATFORM_LABEL = { youtube: 'يوتيوب', instagram: 'إنستغرام', x: 'إكس' } as const;

// The sports channels (backend/sba_channels.py "riyadiya") are run by their own team, so their alerts are
// split from the rest of SBA's accounts.
const SPORTS_ENTITIES = new Set(['riyadiya']);
type AccountGroup = 'all' | 'sba' | 'sports';
const GROUPS: { key: AccountGroup; label: string }[] = [
  { key: 'all', label: 'كل الحسابات' },
  { key: 'sba', label: 'حسابات الهيئة' },
  { key: 'sports', label: 'الحسابات الرياضية' },
];
const inGroup = (a: Alert, g: AccountGroup) =>
  g === 'all' || (g === 'sports') === SPORTS_ENTITIES.has(a.video.entity_key);

// Spikes (green) and drops (red) detected on real SBA posts (Task 4). Fetches its own data.
export default function AlertsPanel({ compact: isCompact = false, days = isCompact ? 7 : 30, selectedId, onSelect }: AlertsPanelProps) {
  const [alerts, setAlerts] = useState<Alert[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [group, setGroup] = useState<AccountGroup>('all');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setAlerts(await apiFetch<Alert[]>(`/api/alerts?days=${days}`));
      setError(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return; // App switches to the login screen
      setError(describeError(err).title);
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => {
    load();
    const id = window.setInterval(load, REFRESH_MS);
    return () => window.clearInterval(id);
  }, [load]);

  const inScope = alerts?.filter((a) => inGroup(a, group)) ?? null;
  const shown = inScope ? (isCompact ? inScope.slice(0, 5) : inScope) : null;

  return (
    <div className="bg-white border border-slate-200/90 rounded-2xl p-5 shadow-xs">
      <div className="flex items-center justify-between gap-3 mb-4">
        <div className="flex items-center gap-2">
          <div className="p-1.5 bg-amber-50 rounded-lg text-amber-600">
            <Bell className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-slate-900 font-arabic">قفزات وانخفاضات الأداء</h3>
            <p className="text-[11px] text-slate-500 font-arabic">
              مقارنة بالمعتاد لنفس الحساب ونوع المحتوى · آخر {days} يوماً
              {inScope && !isCompact ? ` · ${inScope.length} تنبيه` : ''}
            </p>
          </div>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="p-2 rounded-lg text-slate-500 hover:text-slate-900 hover:bg-slate-100 disabled:opacity-50 transition-colors"
          aria-label="تحديث"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {!isCompact && (
        <div className="flex items-center gap-1 bg-slate-100 p-1 rounded-xl mb-4 w-fit" role="group" aria-label="الحسابات">
          {GROUPS.map((g) => {
            const count = alerts?.filter((a) => inGroup(a, g.key)).length;
            return (
              <button
                key={g.key}
                onClick={() => setGroup(g.key)}
                aria-pressed={group === g.key}
                className={`px-3 py-1 rounded-lg text-xs font-bold font-arabic transition-all cursor-pointer ${group === g.key ? 'bg-white text-slate-900 shadow-2xs' : 'text-slate-600 hover:text-slate-900'}`}
              >
                {g.label}{count != null && <span className="text-slate-400 font-normal"> {count}</span>}
              </button>
            );
          })}
        </div>
      )}

      {shown === null && !error && (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-14 bg-slate-100 rounded-xl animate-pulse" />
          ))}
        </div>
      )}

      {error && shown === null && <p className="text-sm text-slate-500 font-arabic text-center py-8">{error}</p>}

      {shown !== null && shown.length === 0 && (
        <p className="text-sm text-slate-500 font-arabic text-center py-8">
          {group === 'all'
            ? 'لا توجد قفزات أو انخفاضات تتجاوز الحد خلال هذه الفترة (أو أن عدد المنشورات المشابهة غير كافٍ للحكم).'
            : `لا توجد قفزات أو انخفاضات في ${group === 'sports' ? 'الحسابات الرياضية' : 'حسابات الهيئة'} خلال هذه الفترة.`}
        </p>
      )}

      {shown !== null && shown.length > 0 && (
        <ul className={`space-y-2 ${isCompact ? '' : 'max-h-[560px] overflow-y-auto pl-1'}`}>
          {shown.map((a) => {
            const spike = a.kind === 'spike';
            const selected = selectedId === a.alert_id;
            const tone = spike
              ? 'border-emerald-200 bg-emerald-50/60 hover:bg-emerald-50'
              : 'border-rose-200 bg-rose-50/60 hover:bg-rose-50';
            const Icon = spike ? ArrowUpRight : ArrowDownRight;
            const body = (
              <>
                <div className={`p-1.5 rounded-lg shrink-0 ${spike ? 'bg-emerald-600 text-white' : 'bg-rose-600 text-white'}`}>
                  <Icon className="w-4 h-4" />
                </div>
                <div className="min-w-0 flex-1 text-right">
                  <p className="text-xs font-bold text-slate-900 font-arabic line-clamp-1" title={a.video.title}>
                    {a.video.title}
                  </p>
                  <p className="text-[11px] text-slate-500 font-arabic mt-0.5">
                    {a.video.channel_name_ar} · {PLATFORM_LABEL[a.video.platform]}
                    {a.detection === 'velocity' ? ' · تغيّر مفاجئ في السرعة' : ''}
                  </p>
                  {!isCompact && <p className="text-[11px] text-slate-600 font-arabic mt-1 leading-relaxed">{a.explanation}</p>}
                </div>
                <div className="shrink-0 text-left w-28">
                  <p className={`text-xs font-black font-arabic ${spike ? 'text-emerald-700' : 'text-rose-700'}`}>
                    {spike
                      ? `${a.ratio >= 10 ? Math.round(a.ratio) : a.ratio.toFixed(1)} ضعف المعتاد`
                      : `أقل من المعتاد بـ ${Math.round((1 - a.ratio) * 100)}%`}
                  </p>
                  <p className="text-[10px] text-slate-400 font-arabic" title="القيمة الفعلية مقابل المعتاد لنفس الحساب ونوع المحتوى">
                    {compact.format(a.observed)} مقابل {compact.format(a.expected)} معتاد
                  </p>
                  {a.severity === 'high' && <p className="text-[10px] font-bold text-amber-700 font-arabic">أولوية عالية</p>}
                </div>
              </>
            );
            return (
              <li key={a.alert_id}>
                {onSelect ? (
                  <button
                    onClick={() => onSelect(a)}
                    className={`w-full flex items-start gap-3 p-3 rounded-xl border transition-colors cursor-pointer ${tone} ${selected ? 'ring-2 ring-slate-900/30' : ''}`}
                  >
                    {body}
                  </button>
                ) : (
                  <a
                    href={a.video.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={`flex items-start gap-3 p-3 rounded-xl border transition-colors ${tone}`}
                  >
                    {body}
                  </a>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
