import { useState, useEffect, useCallback } from 'react';
import {
  Clock, Zap, Users, BookOpen, BarChart2, Eye,
  Copy, Check, RefreshCw, Video, Award, Radio, Globe, ShieldCheck
} from 'lucide-react';
import {
  BarChart, Bar, Cell, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, ResponsiveContainer
} from 'recharts';
import { ApiError, apiFetch, describeError } from '../lib/api';
import type { AnalyticsSummary, Platform } from '../types';
import TrendingPanel from './TrendingPanel';
import AccuracyCard from './AccuracyCard';
import AlertsPanel from './AlertsPanel';

interface DashboardViewProps {
  onNotify?: (title: string, desc?: string, type?: 'success' | 'info') => void;
}

// Mirrors backend/schemas.py::Pattern.
interface ApiPattern {
  pattern_id: string;
  pattern: string;
  supporting_metric: string;
  confidence: number;
  affected_content_types: string[];
  dimension:
    | 'content_type' | 'timing' | 'topic_platform' | 'platform_reach_real' | 'awj_sada_real'
    // Added by Task 1 (backend/schemas.py::Pattern.dimension) for patterns scored on
    // real SBA YouTube/Instagram data (backend.agents.behavior_analysis_agent.analyze_real_data).
    | 'content_type_real' | 'timing_real' | 'topic_real' | 'channel_topic_real' | 'platform_content_real';
  slice_key: string;
  lift_pct: number;
  source: string;
}

const DIMENSION_META: Record<ApiPattern['dimension'], { label: string; icon: React.ReactNode; tagColor: string }> = {
  content_type: {
    label: 'نوع المحتوى',
    icon: <Video className="w-4 h-4 text-violet-600" />,
    tagColor: 'bg-violet-50 text-violet-700 border-violet-200',
  },
  timing: {
    label: 'توقيت',
    icon: <Clock className="w-4 h-4 text-amber-600" />,
    tagColor: 'bg-amber-50 text-amber-700 border-amber-200',
  },
  topic_platform: {
    label: 'الموضوع والمنصة',
    icon: <Award className="w-4 h-4 text-emerald-600" />,
    tagColor: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  },
  platform_reach_real: {
    label: 'منصات حج 1445هـ',
    icon: <Globe className="w-4 h-4 text-blue-600" />,
    tagColor: 'bg-blue-50 text-blue-700 border-blue-200',
  },
  awj_sada_real: {
    label: 'أوج | صدى',
    icon: <Radio className="w-4 h-4 text-rose-600" />,
    tagColor: 'bg-rose-50 text-rose-700 border-rose-200',
  },
  content_type_real: {
    label: 'نوع المحتوى (بيانات حقيقية)',
    icon: <Video className="w-4 h-4 text-violet-600" />,
    tagColor: 'bg-violet-50 text-violet-700 border-violet-200',
  },
  timing_real: {
    label: 'توقيت (بيانات حقيقية)',
    icon: <Clock className="w-4 h-4 text-amber-600" />,
    tagColor: 'bg-amber-50 text-amber-700 border-amber-200',
  },
  topic_real: {
    label: 'الموضوع (بيانات حقيقية)',
    icon: <BookOpen className="w-4 h-4 text-emerald-600" />,
    tagColor: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  },
  channel_topic_real: {
    label: 'الحساب والموضوع',
    icon: <Users className="w-4 h-4 text-teal-600" />,
    tagColor: 'bg-teal-50 text-teal-700 border-teal-200',
  },
  platform_content_real: {
    label: 'مقارنة بين المنصات',
    icon: <Globe className="w-4 h-4 text-blue-600" />,
    tagColor: 'bg-blue-50 text-blue-700 border-blue-200',
  },
};

const CATEGORY_TABS: { key: 'all' | 'content_type' | 'timing' | 'topic_platform' | 'real'; label: string }[] = [
  { key: 'all', label: 'الكل' },
  { key: 'content_type', label: 'نوع المحتوى' },
  { key: 'timing', label: 'توقيت' },
  { key: 'topic_platform', label: 'الموضوع والمنصة' },
  { key: 'real', label: 'بيانات حقيقية' },
];

const REFRESH_MS = 60_000;
const DAYS_OPTIONS = [7, 30, 60];
const PLATFORM_TABS: { key: Platform | 'all'; label: string }[] = [
  { key: 'all', label: 'الكل' },
  { key: 'youtube', label: 'يوتيوب' },
  { key: 'instagram', label: 'إنستغرام' },
  { key: 'x', label: 'إكس' },
];
const PLATFORM_LABEL: Record<Platform, string> = { youtube: 'يوتيوب', instagram: 'إنستغرام', x: 'إكس' };
const PLATFORM_COLOR: Record<Platform, string> = { youtube: '#ef4444', instagram: '#db2777', x: '#0f172a' };
const CONTENT_TYPE_LABEL: Record<string, string> = {
  short: 'مقطع قصير', video: 'فيديو', live: 'بث مباشر', image: 'صورة', carousel: 'ألبوم', text: 'نص',
};
// Sunday-first week, as used in Saudi Arabia.
const DAYS: { key: string; label: string }[] = [
  { key: 'sun', label: 'الأحد' }, { key: 'mon', label: 'الاثنين' }, { key: 'tue', label: 'الثلاثاء' },
  { key: 'wed', label: 'الأربعاء' }, { key: 'thu', label: 'الخميس' }, { key: 'fri', label: 'الجمعة' }, { key: 'sat', label: 'السبت' },
];
const HOURS = Array.from({ length: 24 }, (_, h) => h);

const compact = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 });
const percent = new Intl.NumberFormat('en', { style: 'percent', maximumFractionDigits: 2 });

function minutesAgoLabel(iso: string | null, now = Date.now()): string {
  if (!iso) return 'لا توجد عملية جمع ناجحة بعد';
  const minutes = Math.max(0, Math.floor((now - new Date(iso).getTime()) / 60_000));
  if (minutes < 1) return 'آخر تحديث للبيانات: الآن';
  if (minutes < 60) return `آخر تحديث للبيانات: قبل ${minutes} دقيقة`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `آخر تحديث للبيانات: قبل ${hours} ساعة`;
  return `آخر تحديث للبيانات: قبل ${Math.floor(hours / 24)} يوماً`;
}

// 1.0 = the account's usual level. Diverging scale around 1; opacity grows with distance.
function heatColor(pi: number): string {
  const strength = Math.min(1, Math.abs(Math.log2(Math.max(pi, 0.05))) / 1.5);
  return pi >= 1 ? `rgba(5, 150, 105, ${0.15 + 0.75 * strength})` : `rgba(225, 29, 72, ${0.15 + 0.6 * strength})`;
}

const CARD = 'bg-white border border-slate-200/90 rounded-2xl p-5 shadow-xs';

function Kpi({ icon, label, value, hint }: { icon: React.ReactNode; label: string; value: string; hint?: string }) {
  return (
    <div className={`${CARD} hover:shadow-sm transition-all`}>
      <div className="flex items-start justify-between mb-3">
        <div className="p-2.5 bg-slate-100 rounded-xl text-slate-600">{icon}</div>
        {hint && <span className="text-[10px] font-semibold text-slate-400 font-arabic">{hint}</span>}
      </div>
      <p className="text-3xl font-black text-slate-900 font-arabic" dir="ltr" style={{ textAlign: 'right' }}>{value}</p>
      <p className="text-xs font-semibold text-slate-500 font-arabic mt-1">{label}</p>
    </div>
  );
}

function Segmented<T extends string | number>({
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

function IndexBars({ rows }: { rows: { label: string; value: number; sub: string; color?: string }[] }) {
  const max = Math.max(1.5, ...rows.map((r) => r.value));
  return (
    <div className="space-y-3">
      {rows.map((r) => (
        <div key={r.label}>
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs font-bold text-slate-800 font-arabic">{r.label}</span>
            <span className="text-xs text-slate-500 font-arabic">
              <strong className="text-slate-900">{r.value.toFixed(2)}×</strong> · {r.sub}
            </span>
          </div>
          <div className="relative h-2 bg-slate-100 rounded-full overflow-hidden">
            <div className="h-full rounded-full transition-all duration-700" style={{ width: `${(r.value / max) * 100}%`, backgroundColor: r.color ?? '#059669' }} />
            <div className="absolute top-0 bottom-0 w-px bg-slate-500/50" style={{ right: `${100 - (1 / max) * 100}%` }} title="المعتاد (1×)" />
          </div>
        </div>
      ))}
    </div>
  );
}

function Heatmap({ summary, platform }: { summary: AnalyticsSummary; platform: Platform }) {
  const cells = new Map(
    summary.best_times.filter((c) => c.platform === platform).map((c) => [`${c.day_of_week}-${c.hour}`, c]),
  );
  if (cells.size === 0) {
    return <p className="text-xs text-slate-400 font-arabic text-center py-10">لا توجد خلايا بعدد منشورات كافٍ (٣ على الأقل) لعرض أفضل الأوقات.</p>;
  }
  const best = [...cells.values()].sort((a, b) => b.median_performance_index - a.median_performance_index)[0];
  return (
    <div>
      <div className="overflow-x-auto">
        <table className="border-separate border-spacing-0.5 w-full min-w-[640px]" dir="ltr">
          <thead>
            <tr>
              <th />
              {HOURS.map((h) => (
                <th key={h} className="text-[9px] font-semibold text-slate-400 font-normal">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {DAYS.map((d) => (
              <tr key={d.key}>
                <td className="text-[10px] font-arabic font-bold text-slate-600 pl-1 text-right whitespace-nowrap" dir="rtl">{d.label}</td>
                {HOURS.map((h) => {
                  const c = cells.get(`${d.key}-${h}`);
                  return (
                    <td
                      key={h}
                      className="h-5 rounded-sm text-center"
                      style={{ backgroundColor: c ? heatColor(c.median_performance_index) : '#f1f5f9' }}
                      title={c ? `${d.label} ${h}:00 — ${c.median_performance_index.toFixed(2)}× المعتاد (n=${c.n})` : 'بيانات غير كافية'}
                    />
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 mt-3 text-[11px] text-slate-500 font-arabic">
        <span>
          الأفضل: {DAYS.find((d) => d.key === best.day_of_week)?.label} {best.hour}:00 بتوقيت الرياض ({best.median_performance_index.toFixed(2)}× المعتاد، n={best.n})
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-sm" style={{ backgroundColor: heatColor(0.4) }} /> أقل من المعتاد
          <span className="w-3 h-3 rounded-sm mr-2" style={{ backgroundColor: heatColor(2) }} /> أعلى من المعتاد
          <span className="w-3 h-3 rounded-sm bg-slate-100 mr-2" /> بيانات غير كافية
        </span>
      </div>
    </div>
  );
}

export default function DashboardView({ onNotify }: DashboardViewProps) {
  const [days, setDays] = useState(30);
  const [platform, setPlatform] = useState<Platform | 'all'>('all');
  const [heatPlatform, setHeatPlatform] = useState<Platform>('youtube');
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now());
  const [activeCategory, setActiveCategory] = useState<typeof CATEGORY_TABS[number]['key']>('all');
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isLoadingPatterns, setIsLoadingPatterns] = useState(true);
  const [patterns, setPatterns] = useState<ApiPattern[]>([]);

  const loadSummary = useCallback(async () => {
    try {
      const qs = new URLSearchParams({ days: String(days) });
      if (platform !== 'all') qs.set('platform', platform);
      setSummary(await apiFetch<AnalyticsSummary>(`/api/analytics/summary?${qs}`));
      setSummaryError(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return; // App switches to the login screen
      setSummaryError(describeError(err).title);
    } finally {
      setNow(Date.now());
    }
  }, [days, platform]);

  // Reload on filter change, then every 60 s. The tick also keeps "قبل X دقيقة" current.
  useEffect(() => {
    setSummary(null);
    loadSummary();
    const id = window.setInterval(loadSummary, REFRESH_MS);
    return () => window.clearInterval(id);
  }, [loadSummary]);

  useEffect(() => {
    if (platform !== 'all') setHeatPlatform(platform);
  }, [platform]);

  useEffect(() => {
    (async () => {
      try {
        setPatterns(await apiFetch<ApiPattern[]>('/api/patterns'));
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) return; // App switches to the login screen
        onNotify?.('تعذر تحميل مخزن الأنماط', describeError(err).desc, 'info');
      } finally {
        setIsLoadingPatterns(false);
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    })();
  }, []);

  const filteredPatterns = patterns.filter((p) => {
    if (activeCategory === 'all') return true;
    if (activeCategory === 'real') return p.source.startsWith('real_');
    return p.dimension === activeCategory || p.dimension === `${activeCategory}_real`;
  });

  const handleCopy = (id: string, text: string) => {
    navigator.clipboard?.writeText(text);
    setCopiedId(id);
    onNotify?.('تم نسخ النمط إلى الحافظة', '', 'success');
    setTimeout(() => setCopiedId(null), 2000);
  };

  const handleRefresh = async () => {
    setIsRefreshing(true);
    try {
      const fresh = await apiFetch<ApiPattern[]>('/api/patterns/refresh', { method: 'POST' });
      setPatterns(fresh);
      onNotify?.('تم تحديث مخزن الأنماط', `${fresh.length} نمط محدّث من بيانات حقيقية ومركّبة`, 'info');
    } catch (err) {
      onNotify?.('تعذر تحديث مخزن الأنماط', describeError(err).desc, 'info');
    } finally {
      setIsRefreshing(false);
    }
  };

  const heatChoices = platform === 'all' ? PLATFORM_TABS.filter((t) => t.key !== 'all') : [];
  const empty = summary !== null && summary.totals.posts === 0;
  const channelRows = summary?.by_channel.map((c) => ({
    name: `${c.name_ar}${platform === 'all' ? ` (${PLATFORM_LABEL[c.platform]})` : ''}`,
    index: c.median_performance_index,
    platform: c.platform,
    posts: c.posts,
  })) ?? [];

  return (
    <div className="animate-fade-in space-y-6">
      {/* ── Filters + data freshness ── */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-bold text-slate-700 font-arabic">مؤشرات الأداء الرئيسية</h3>
          <p className="text-[11px] text-slate-400 font-arabic mt-0.5">
            {summary ? minutesAgoLabel(summary.data_as_of, now) : 'جارٍ التحميل...'}
            {summary && ` · منشورات عمرها ${summary.min_post_age_days} أيام فأكثر`}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Segmented options={PLATFORM_TABS} value={platform} onChange={setPlatform} />
          <Segmented options={DAYS_OPTIONS.map((d) => ({ key: d, label: `${d} يوماً` }))} value={days} onChange={setDays} />
        </div>
      </div>

      {summaryError && summary === null && (
        <div className={`${CARD} text-center`}>
          <p className="text-sm text-slate-600 font-arabic mb-3">{summaryError}</p>
          <button onClick={loadSummary} className="px-4 py-1.5 rounded-lg bg-slate-900 text-white text-xs font-bold font-arabic cursor-pointer">إعادة المحاولة</button>
        </div>
      )}

      {summary === null && !summaryError && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-5">
          {Array.from({ length: 4 }).map((_, i) => <div key={i} className="h-32 bg-slate-100 rounded-2xl animate-pulse" />)}
        </div>
      )}

      {empty && (
        <div className={`${CARD} text-center`}>
          <p className="text-sm text-slate-600 font-arabic">لا توجد منشورات مجمّعة في هذه الفترة والمنصة. جرّب فترة أطول أو منصة أخرى.</p>
        </div>
      )}

      {summary && !empty && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-5">
            <Kpi icon={<Video className="w-5 h-5" />} label="عدد المنشورات" value={summary.totals.posts.toLocaleString('en')} />
            <Kpi
              icon={<Eye className="w-5 h-5" />}
              label={platform === 'x' ? 'مرات الظهور' : 'المشاهدات'}
              value={platform === 'instagram' ? '—' : compact.format(summary.totals.views)}
              hint={platform === 'instagram' ? 'غير متاحة على إنستغرام' : platform === 'x' ? 'إكس فقط' : 'يوتيوب فقط'}
            />
            <Kpi icon={<Users className="w-5 h-5" />} label="الإعجابات + التعليقات" value={compact.format(summary.totals.likes + summary.totals.comments)} />
            <Kpi
              icon={<Zap className="w-5 h-5" />}
              label="معدل التفاعل"
              value={summary.totals.engagement_rate === null ? '—' : percent.format(summary.totals.engagement_rate)}
              hint={platform === 'x' ? '(إعجابات + ردود) ÷ مرات الظهور' : '(إعجابات + تعليقات) ÷ مشاهدات'}
            />
          </div>

          {/* ── Channel comparison + platform split ── */}
          <div className="grid grid-cols-1 lg:grid-cols-5 gap-5">
            <div className={`lg:col-span-3 ${CARD}`}>
              <div className="flex items-center gap-2 mb-1">
                <div className="p-1.5 bg-slate-100 rounded-lg text-slate-700"><BarChart2 className="w-4 h-4" /></div>
                <h3 className="text-sm font-bold text-slate-900 font-arabic">مقارنة القنوات (مؤشر الأداء)</h3>
              </div>
              <p className="text-[11px] text-slate-400 font-arabic mb-3">وسيط أداء المنشور مقسوماً على المعتاد لنفس الحساب ونوع المحتوى (1× = المعتاد)</p>
              <div style={{ height: Math.max(220, channelRows.length * 34 + 40) }} className="w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={channelRows} layout="vertical" margin={{ top: 0, right: 10, left: 10, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" horizontal={false} />
                    <XAxis type="number" tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
                    <YAxis type="category" dataKey="name" width={150} orientation="right" tick={{ fontSize: 11, fill: '#475569', fontFamily: 'Tajawal, sans-serif' }} axisLine={false} tickLine={false} />
                    <Tooltip
                      contentStyle={{ borderRadius: 16, fontFamily: 'Tajawal, sans-serif', direction: 'rtl', textAlign: 'right' }}
                      formatter={(v: number) => [`${v.toFixed(2)}×`, 'وسيط مؤشر الأداء']}
                    />
                    <ReferenceLine x={1} stroke="#64748b" strokeDasharray="4 4" />
                    <Bar dataKey="index" radius={[0, 6, 6, 0]}>
                      {channelRows.map((r) => <Cell key={r.name} fill={PLATFORM_COLOR[r.platform]} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className={`lg:col-span-2 ${CARD}`}>
              <h3 className="text-sm font-bold text-slate-900 font-arabic mb-4">المنصات</h3>
              <div className="space-y-3.5">
                {summary.by_platform.map((p) => {
                  const maxPosts = Math.max(1, ...summary.by_platform.map((x) => x.posts));
                  return (
                    <div key={p.platform} className="p-2 rounded-xl hover:bg-slate-50 transition-colors">
                      <div className="flex items-center justify-between mb-1.5">
                        <div className="flex items-center gap-2">
                          <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: PLATFORM_COLOR[p.platform] }} />
                          <span className="text-xs font-bold text-slate-800 font-arabic">{PLATFORM_LABEL[p.platform]}</span>
                        </div>
                        <span className="text-xs font-black text-slate-900">{p.posts.toLocaleString('en')} منشور</span>
                      </div>
                      <div className="w-full h-2 bg-slate-100 rounded-full overflow-hidden">
                        <div className="h-full rounded-full transition-all duration-700" style={{ width: `${(p.posts / maxPosts) * 100}%`, backgroundColor: PLATFORM_COLOR[p.platform] }} />
                      </div>
                      <p className="text-[11px] text-slate-400 font-arabic mt-1.5">
                        {p.accounts} حساب · {compact.format(p.followers)} متابع · {compact.format(p.likes)} إعجاب · {compact.format(p.comments)} تعليق
                      </p>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          {/* ── Best-time heatmap ── */}
          <div className={CARD}>
            <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
              <div className="flex items-center gap-2">
                <div className="p-1.5 bg-amber-50 rounded-lg text-amber-600"><Clock className="w-4 h-4" /></div>
                <div>
                  <h3 className="text-sm font-bold text-slate-900 font-arabic">أفضل أوقات النشر</h3>
                  <p className="text-[11px] text-slate-400 font-arabic">اليوم × الساعة (بتوقيت الرياض) · وسيط مؤشر الأداء</p>
                </div>
              </div>
              {heatChoices.length > 0 && <Segmented options={heatChoices as { key: Platform; label: string }[]} value={heatPlatform} onChange={setHeatPlatform} />}
            </div>
            <Heatmap summary={summary} platform={platform === 'all' ? heatPlatform : platform} />
          </div>

          {/* ── Topic & content type ── */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <div className={CARD}>
              <h3 className="text-sm font-bold text-slate-900 font-arabic mb-4">الأداء حسب الموضوع</h3>
              <IndexBars rows={summary.by_topic.map((t) => ({ label: t.label_ar, value: t.median_performance_index, sub: `${t.posts} منشور` }))} />
            </div>
            <div className={CARD}>
              <h3 className="text-sm font-bold text-slate-900 font-arabic mb-4">الأداء حسب نوع المحتوى</h3>
              <IndexBars
                rows={summary.by_content_type.map((t) => ({
                  label: `${CONTENT_TYPE_LABEL[t.content_type] ?? t.content_type}${platform === 'all' ? ` · ${PLATFORM_LABEL[t.platform]}` : ''}`,
                  value: t.median_performance_index,
                  sub: `${t.posts} منشور`,
                  color: PLATFORM_COLOR[t.platform],
                }))}
              />
            </div>
          </div>
        </>
      )}

      {/* ── Embedded agent panels ── */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        <div className="xl:col-span-2 space-y-5">
          <TrendingPanel />
        </div>
        <div className="space-y-5">
          <AccuracyCard />
          <AlertsPanel compact />
        </div>
      </div>

      {/* ── Shared Pattern Store ── */}
      <div className="bg-white border border-slate-200/90 rounded-2xl p-6 shadow-xs">
        <div className="flex flex-wrap items-center justify-between gap-4 mb-5">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-emerald-50 text-emerald-700 rounded-xl border border-emerald-200/60">
              <BookOpen className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-black text-slate-900 font-arabic">
                مخزن الأنماط المشترك
              </h3>
              <p className="text-xs text-slate-400 font-arabic">
                أنماط مستخرجة آلياً لدعم قرارات النشر
              </p>
            </div>
          </div>

          {/* Filter Pills + Refresh */}
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1 bg-slate-100 p-1 rounded-xl">
              {CATEGORY_TABS.map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => setActiveCategory(tab.key)}
                  className={`px-3 py-1 rounded-lg text-xs font-bold font-arabic transition-all cursor-pointer ${
                    activeCategory === tab.key
                      ? 'bg-white text-slate-900 shadow-2xs'
                      : 'text-slate-600 hover:text-slate-900'
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            <button
              onClick={handleRefresh}
              className="p-2 rounded-xl border border-slate-200 text-slate-600 hover:bg-slate-50 hover:text-slate-900 transition-colors cursor-pointer"
              title="تحديث"
            >
              <RefreshCw className={`w-4 h-4 ${isRefreshing ? 'animate-spin text-emerald-600' : ''}`} />
            </button>
          </div>
        </div>

        {/* Pattern Cards Grid */}
        {isLoadingPatterns ? (
          <p className="text-xs text-slate-400 font-arabic text-center py-8">جارٍ تحميل الأنماط من الخادم...</p>
        ) : filteredPatterns.length === 0 ? (
          <p className="text-xs text-slate-400 font-arabic text-center py-8">لا توجد أنماط في هذا التصنيف حالياً.</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {filteredPatterns.map((pattern) => {
              const meta = DIMENSION_META[pattern.dimension] ?? DIMENSION_META.content_type;
              const isReal = pattern.source.startsWith('real_');
              return (
                <div
                  key={pattern.pattern_id}
                  className="flex flex-col justify-between p-4 bg-slate-50/70 hover:bg-white rounded-2xl border border-slate-200/80 hover:border-emerald-300 transition-all duration-200"
                >
                  <div>
                    <div className="flex items-center justify-between mb-2.5">
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${meta.tagColor} font-arabic`}>
                        {meta.label}
                      </span>
                      <div className="flex items-center gap-1.5">
                        {isReal && (
                          <span
                            title="مبني على بيانات حقيقية موثّقة"
                            className="flex items-center gap-0.5 text-[9px] font-bold text-emerald-700 bg-emerald-50 border border-emerald-200 px-1.5 py-0.5 rounded-full font-arabic"
                          >
                            <ShieldCheck className="w-3 h-3" />
                            حقيقي
                          </span>
                        )}
                        <div className="p-1.5 rounded-lg bg-white border border-slate-200/70 shadow-2xs">
                          {meta.icon}
                        </div>
                      </div>
                    </div>
                    <p className="text-xs text-slate-800 font-arabic leading-relaxed text-right font-medium">
                      {pattern.pattern}
                    </p>
                  </div>

                  <div className="mt-4 pt-2.5 border-t border-slate-200/70 flex items-center justify-between">
                    <span className="text-[10px] text-slate-400 font-arabic">
                      الثقة: <strong className="text-slate-700">{Math.round(pattern.confidence * 100)}%</strong>
                    </span>

                    <button
                      onClick={() => handleCopy(pattern.pattern_id, pattern.pattern)}
                      className="flex items-center gap-1 text-xs font-bold text-slate-600 hover:text-emerald-700 transition-colors cursor-pointer font-arabic p-1 rounded-md hover:bg-emerald-50"
                    >
                      {copiedId === pattern.pattern_id ? (
                        <>
                          <Check className="w-3.5 h-3.5 text-emerald-600" />
                          <span className="text-emerald-600">تم</span>
                        </>
                      ) : (
                        <>
                          <Copy className="w-3.5 h-3.5" />
                          <span>نسخ</span>
                        </>
                      )}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
