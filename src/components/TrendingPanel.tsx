import { useCallback, useEffect, useState } from 'react';
import { ExternalLink, Flame, RefreshCw, TrendingUp } from 'lucide-react';
import { ApiError, apiFetch, describeError } from '../lib/api';
import type { TrendingItem } from '../types';

const REFRESH_MS = 60_000;

const compact = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 });

function scoreColor(score: number): string {
  if (score >= 0.75) return 'bg-rose-500';
  if (score >= 0.5) return 'bg-amber-500';
  return 'bg-emerald-500';
}

interface TrendingPanelProps {
  hours?: number;
  limit?: number;
}

// What's trending across SBA's YouTube channels right now (Task 2). Fetches its own data.
export default function TrendingPanel({ hours = 24, limit = 10 }: TrendingPanelProps) {
  const [items, setItems] = useState<TrendingItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setItems(await apiFetch<TrendingItem[]>(`/api/trending?hours=${hours}&limit=${limit}`));
      setError(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return; // App switches to the login screen
      setError(describeError(err).title);
    } finally {
      setLoading(false);
    }
  }, [hours, limit]);

  useEffect(() => {
    load();
    const id = window.setInterval(load, REFRESH_MS);
    return () => window.clearInterval(id);
  }, [load]);

  return (
    <div className="bg-white border border-slate-200/90 rounded-2xl p-5 shadow-xs">
      <div className="flex items-center justify-between gap-3 mb-4">
        <div className="flex items-center gap-2">
          <div className="p-1.5 bg-rose-50 rounded-lg text-rose-600">
            <Flame className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-slate-900 font-arabic">الرائج الآن على يوتيوب الهيئة</h3>
            <p className="text-[11px] text-slate-500 font-arabic">
              مرتّب حسب احتمالية الانتشار · آخر {hours} ساعة
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

      {items === null && !error && (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-20 bg-slate-100 rounded-xl animate-pulse" />
          ))}
        </div>
      )}

      {error && items === null && (
        <p className="text-sm text-slate-500 font-arabic text-center py-8">{error}</p>
      )}

      {items !== null && items.length === 0 && (
        <p className="text-sm text-slate-500 font-arabic text-center py-8">
          لا توجد مقاطع بقياسات حديثة كافية في آخر {hours} ساعة.
        </p>
      )}

      {items !== null && items.length > 0 && (
        <ol className="space-y-3">
          {items.map((item, rank) => (
            <li key={item.video.video_id} className="flex gap-3 p-2.5 rounded-xl border border-slate-100 hover:border-slate-200 hover:bg-slate-50/60 transition-colors">
              <a href={item.video.url} target="_blank" rel="noopener noreferrer" className="relative shrink-0">
                <img
                  src={`https://i.ytimg.com/vi/${item.video.video_id}/mqdefault.jpg`}
                  alt=""
                  loading="lazy"
                  className="w-32 h-[72px] object-cover rounded-lg bg-slate-100"
                />
                <span className="absolute top-1 right-1 bg-slate-900/80 text-white text-[10px] font-bold rounded-md px-1.5">
                  {rank + 1}
                </span>
              </a>

              <div className="min-w-0 flex-1">
                <a
                  href={item.video.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group flex items-start gap-1 text-sm font-bold text-slate-900 font-arabic hover:text-emerald-700"
                  title={item.video.title}
                >
                  <span className="line-clamp-1">{item.video.title}</span>
                  <ExternalLink className="w-3 h-3 mt-1 shrink-0 opacity-0 group-hover:opacity-100" />
                </a>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1 text-[11px] text-slate-500 font-arabic">
                  <span>{item.video.channel_name_ar}</span>
                  <span className="flex items-center gap-1 text-slate-700 font-semibold">
                    <TrendingUp className="w-3 h-3" />
                    {compact.format(item.views_per_hour)} مشاهدة/ساعة
                  </span>
                  <span>أسرع من المعتاد بـ {item.velocity_index.toFixed(1)} مرة</span>
                  {item.predicted_views_7d !== null && (
                    <span>متوقع خلال 7 أيام: {compact.format(item.predicted_views_7d)}</span>
                  )}
                </div>

                <div className="flex items-center gap-2 mt-2" title={item.reason}>
                  <span className="text-[10px] text-slate-400 font-arabic whitespace-nowrap">احتمالية الانتشار</span>
                  <div className="h-1.5 flex-1 bg-slate-100 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full ${scoreColor(item.viral_score)}`}
                      style={{ width: `${Math.round(item.viral_score * 100)}%` }}
                    />
                  </div>
                  <span className="text-[11px] font-bold text-slate-700 w-8 text-left">
                    {Math.round(item.viral_score * 100)}%
                  </span>
                </div>
                <p className="text-[11px] text-slate-500 font-arabic mt-1 line-clamp-2">{item.reason}</p>
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
