import { useState, useEffect, useCallback } from 'react';
import {
  Clock, Zap, Users, BarChart2, Eye, Video
} from 'lucide-react';
import {
  BarChart, Bar, Cell, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, LabelList
} from 'recharts';
import { ApiError, apiFetch, describeError, ALL_DAYS, daysLabel } from '../lib/api';
import { periodLabel } from '../lib/period';
import { ContextBar, ScopeTag, Segmented } from './ContextBar';
import type { AnalyticsSummary, Platform, OptimizerDraft } from '../types';
import TrendingPanel from './TrendingPanel';
import PublishingPlaybook from './PublishingPlaybook';
import PatternStore from './PatternStore';

interface DashboardViewProps {
  onNotify?: (title: string, desc?: string, type?: 'success' | 'info') => void;
  onCreateDraft?: (draft: OptimizerDraft) => void;
}

const REFRESH_MS = 60_000;
const DAYS_OPTIONS = [7, 30, 90, ALL_DAYS];
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
// Riyadh clock hour -> "12 ص", "1 ص" ... "12 م", "11 م" (the API's 0-23 read like a count, not a time).
function hourLabel(h: number): string {
  const twelve = h % 12 === 0 ? 12 : h % 12;
  return `${twelve} ${h < 12 ? 'ص' : 'م'}`;
}
function hourRange(h: number): string {
  return `${hourLabel(h)} – ${hourLabel((h + 1) % 24)}`;
}

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

// Turns a ratio-to-usual (1 = the account's typical post) into a sentence anyone can read.
function vsUsual(ratio: number): { text: string; tone: 'up' | 'down' | 'flat' } {
  if (ratio >= 1.95) return { text: `${ratio.toFixed(1)} ضعف المعتاد`, tone: 'up' };
  const pct = Math.round(Math.abs(ratio - 1) * 100);
  if (pct < 5) return { text: 'مثل المعتاد تقريباً', tone: 'flat' };
  return ratio > 1 ? { text: `أعلى من المعتاد بـ ${pct}%`, tone: 'up' } : { text: `أقل من المعتاد بـ ${pct}%`, tone: 'down' };
}
const TONE_CLASS = { up: 'text-emerald-700', down: 'text-rose-600', flat: 'text-slate-500' } as const;
const TONE_COLOR = { up: '#059669', down: '#e11d48', flat: '#94a3b8' } as const;

// What "reaching more" is measured with - each platform exposes a different main number.
const REACH_METRIC: Record<Platform, string> = {
  youtube: 'المشاهدات', x: 'مرات الظهور', instagram: 'الإعجابات والتعليقات (إنستغرام لا يكشف المشاهدات)',
};
function MetricNote({ platform }: { platform: Platform | 'all' }) {
  return (
    <p className="text-[11px] text-slate-500 font-arabic mt-0.5 mb-3 leading-relaxed">
      {platform === 'all'
        ? 'نقيس الوصول بالمشاهدات على يوتيوب، ومرات الظهور على إكس، والإعجابات والتعليقات على إنستغرام.'
        : `نقيس الوصول بـ${REACH_METRIC[platform]}.`}
      {' '}وكل منشور يُقارن بالمنشور المعتاد لحسابه نفسه، حتى لا يتفوق الحساب الكبير لمجرد حجمه.
    </p>
  );
}

function IndexBars({ rows, category }: { rows: { label: string; value: number; sub: string; color?: string }[]; category: string }) {
  const max = Math.max(1.5, ...rows.map((r) => r.value));
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between text-[10px] font-bold text-slate-400 font-arabic border-b border-slate-100 pb-1">
        <span>{category}</span>
        <span>مقارنة بالمنشور المعتاد للحساب · عدد المنشورات</span>
      </div>
      {rows.map((r, i) => (
        <div key={`${i}-${r.label}`}>
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs font-bold text-slate-800 font-arabic">{r.label}</span>
            <span className="text-xs text-slate-500 font-arabic" title={`${r.value.toFixed(2)}× من المعتاد`}>
              <strong className={TONE_CLASS[vsUsual(r.value).tone]}>{vsUsual(r.value).text}</strong> · {r.sub}
            </span>
          </div>
          <div className="relative h-2 bg-slate-100 rounded-full overflow-hidden">
            <div className="h-full rounded-full transition-all duration-700" style={{ width: `${(r.value / max) * 100}%`, backgroundColor: r.color ?? TONE_COLOR[vsUsual(r.value).tone] }} />
            <div className="absolute top-0 bottom-0 w-px bg-slate-500/60" style={{ right: `${(1 / max) * 100}%` }} title="المعتاد (1×)" />
          </div>
        </div>
      ))}
      <div className="relative h-3 text-[9px] text-slate-400 font-arabic">
        <span className="absolute right-0" dir="ltr">0×</span>
        <span className="absolute translate-x-1/2 whitespace-nowrap" style={{ right: `${(1 / max) * 100}%` }}>
          <span dir="ltr">1×</span> = المعتاد
        </span>
        <span className="absolute left-0" dir="ltr">{max.toFixed(1)}×</span>
      </div>
    </div>
  );
}

function Heatmap({ summary, platform }: { summary: AnalyticsSummary; platform: Platform }) {
  const cells = new Map(
    summary.best_times.filter((c) => c.platform === platform).map((c) => [`${c.day_of_week}-${c.hour}`, c]),
  );
  if (cells.size === 0) {
    return <p className="text-xs text-slate-400 font-arabic text-center py-10">لا توجد أوقات بعدد منشورات كافٍ (5 على الأقل) للحكم عليها بعد.</p>;
  }
  const top = [...cells.values()].sort((a, b) => b.median_performance_index - a.median_performance_index).slice(0, 3);
  const rank = new Map(top.map((c, i) => [`${c.day_of_week}-${c.hour}`, i + 1]));
  const dayLabel = (key: string) => DAYS.find((d) => d.key === key)?.label;
  return (
    <div>
      <div className="flex flex-wrap gap-2 mb-4">
        {top.map((c, i) => (
          <div key={`${c.day_of_week}-${c.hour}`} className="flex items-center gap-2 px-3 py-2 rounded-xl bg-emerald-50 border border-emerald-100">
            <span className="w-5 h-5 rounded-full bg-emerald-600 text-white text-[10px] font-black flex items-center justify-center">{i + 1}</span>
            <span className="text-xs font-bold text-slate-800 font-arabic">{dayLabel(c.day_of_week)} · {hourRange(c.hour)}</span>
            <span className="text-[11px] text-emerald-700 font-arabic">{vsUsual(c.median_performance_index).text} · {c.n} منشوراً</span>
          </div>
        ))}
      </div>
      <div className="overflow-x-auto">
        <table className="border-separate border-spacing-0.5 w-full min-w-[860px]" dir="ltr">
          <thead>
            <tr>
              <th />
              <th colSpan={24} className="text-[10px] font-arabic font-bold text-slate-600 pb-1" dir="rtl">الساعة (بتوقيت الرياض)</th>
            </tr>
            <tr>
              <th className="text-[10px] font-arabic font-bold text-slate-600 text-right whitespace-nowrap pl-1" dir="rtl">اليوم</th>
              {HOURS.map((h) => (
                <th key={h} className="text-[9px] font-arabic font-semibold text-slate-500 whitespace-nowrap px-0.5" dir="rtl">
                  {hourLabel(h)}
                </th>
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
                      className="h-5 rounded-sm text-center text-[10px] font-black text-white"
                      style={{ backgroundColor: c ? heatColor(c.median_performance_index) : '#f1f5f9' }}
                      title={c ? `${d.label} ${hourRange(h)} — ${vsUsual(c.median_performance_index).text} (${c.n} منشوراً)` : `${d.label} ${hourRange(h)}: منشورات قليلة - لا يمكن الحكم`}
                    >
                      {rank.get(`${d.key}-${h}`) ?? ''}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 mt-3 text-[11px] text-slate-500 font-arabic">
        <span>1–3 = أفضل الأوقات · مرّر الفأرة على أي مربع للتفاصيل</span>
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-3 rounded-sm" style={{ backgroundColor: heatColor(0.4) }} /> أقل من المعتاد
          <span className="w-3 h-3 rounded-sm mr-2" style={{ backgroundColor: heatColor(2) }} /> أعلى من المعتاد
          <span className="w-3 h-3 rounded-sm bg-slate-100 mr-2" /> منشورات قليلة (أقل من 5)
        </span>
      </div>
    </div>
  );
}

export default function DashboardView({ onNotify, onCreateDraft }: DashboardViewProps) {
  const [days, setDays] = useState(ALL_DAYS);
  const [platform, setPlatform] = useState<Platform | 'all'>('all');
  const [heatPlatform, setHeatPlatform] = useState<Platform>('youtube');
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now());

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

  const heatChoices = platform === 'all' ? PLATFORM_TABS.filter((t) => t.key !== 'all') : [];
  const empty = summary !== null && summary.totals.posts === 0;
  // Accounts are compared on reach per 1,000 followers, within one platform (views and impressions differ).
  const channelPlatform: Platform = platform === 'all' ? heatPlatform : platform;
  const channelRows = (summary?.by_channel ?? [])
    .filter((c) => c.platform === channelPlatform && c.median_per_1k_followers !== null)
    .map((c) => ({ name: c.name_ar, index: c.median_per_1k_followers as number, platform: c.platform, posts: c.posts }))
    .sort((a, b) => b.index - a.index);
  const reachUnit = channelPlatform === 'youtube' ? 'مشاهدة' : channelPlatform === 'x' ? 'مرة ظهور' : 'تفاعل';
  const heatShown: Platform = platform === 'all' ? heatPlatform : platform;
  const heatCoverage = summary?.best_times_coverage?.find((c) => c.platform === heatShown);
  // How far back "كل الفترة" actually reaches (the longest platform history).
  const spanDays = summary?.best_times_coverage?.length ? Math.max(...summary.best_times_coverage.map((c) => c.days)) : null;

  return (
    <div className="animate-fade-in space-y-6">
      {/* ── Filters, pinned while scrolling, + what the numbers cover ── */}
      <ContextBar
        scope={`${platform === 'all' ? 'كل المنصات' : PLATFORM_LABEL[platform]} · ${periodLabel(days, spanDays)}`}
        detail={summary ? (
          <>
            {summary.totals.posts.toLocaleString('en')} منشوراً عمرها {summary.min_post_age_days} أيام فأكثر · {minutesAgoLabel(summary.data_as_of, now)}
          </>
        ) : 'جارٍ التحميل...'}
        controls={(
          <>
            <Segmented options={PLATFORM_TABS} value={platform} onChange={setPlatform} />
            <Segmented options={DAYS_OPTIONS.map((d) => ({ key: d, label: daysLabel(d) }))} value={days} onChange={setDays} />
          </>
        )}
      />

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
                <h3 className="text-sm font-bold text-slate-900 font-arabic">أي الحسابات تصل لجمهورها أكثر؟</h3>
                {platform === 'all' && <div className="mr-auto"><Segmented options={heatChoices as { key: Platform; label: string }[]} value={heatPlatform} onChange={setHeatPlatform} /></div>}
              </div>
              <p className="text-[11px] text-slate-400 font-arabic mb-3">مقسوماً على حجم الجمهور، فيقارن الحسابات بعدل مهما كان حجمها</p>
              <p className="text-[10px] font-bold text-slate-500 font-arabic text-right mb-1">الحساب</p>
              {/* dir="ltr": in the RTL page the SVG tick text would run back over the bars and be clipped. */}
              <div dir="ltr" style={{ height: Math.max(220, channelRows.length * 34 + 40) }} className="w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={channelRows} layout="vertical" margin={{ top: 0, right: 10, left: 10, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" horizontal={false} />
                    <XAxis type="number" domain={[0, (max: number) => Math.ceil(max * 1.15)]} tickFormatter={(v: number) => compact.format(v)} tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={false} tickLine={false} />
                    <YAxis type="category" dataKey="name" width={150} orientation="right" tick={{ fontSize: 11, fill: '#475569', fontFamily: 'Tajawal, sans-serif' }} axisLine={false} tickLine={false} />
                    <Tooltip
                      contentStyle={{ borderRadius: 16, fontFamily: 'Tajawal, sans-serif', direction: 'rtl', textAlign: 'right' }}
                      formatter={(v: number) => [`${v.toFixed(1)} ${reachUnit} لكل 1000 متابع`, 'المنشور المعتاد']}
                    />
                    <Bar dataKey="index" radius={[0, 4, 4, 0]}>
                      {channelRows.map((r) => <Cell key={r.name} fill={PLATFORM_COLOR[r.platform]} />)}
                      <LabelList dataKey="index" position="right" formatter={(v: number) => v.toFixed(1)} style={{ fontSize: 11, fill: '#334155', fontWeight: 700 }} />
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <p className="text-[10px] font-bold text-slate-500 font-arabic text-center mt-1">{reachUnit} للمنشور المعتاد لكل 1000 متابع</p>
            </div>

            <div className={`lg:col-span-2 ${CARD}`}>
              <h3 className="text-sm font-bold text-slate-900 font-arabic mb-3">المنصات</h3>
              <div className="flex items-center justify-between text-[10px] font-bold text-slate-400 font-arabic border-b border-slate-100 pb-1 mb-2">
                <span>المنصة</span>
                <span>عدد المنشورات</span>
              </div>
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
                  <p className="text-[11px] text-slate-400 font-arabic">أداء المنشور مقارنة بالمعتاد لنفس الحساب، حسب يوم وساعة النشر</p>
                </div>
                {heatCoverage && (
                  <ScopeTag fixed>
                    {PLATFORM_LABEL[heatShown]} · كل الفترة ({heatCoverage.days} يوماً، {heatCoverage.posts.toLocaleString('en')} منشوراً)
                  </ScopeTag>
                )}
              </div>
              {heatChoices.length > 0 && <Segmented options={heatChoices as { key: Platform; label: string }[]} value={heatPlatform} onChange={setHeatPlatform} />}
            </div>
            <Heatmap summary={summary} platform={heatShown} />
          </div>

          {/* ── Topic & content type ── */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <div className={CARD}>
              <h3 className="text-sm font-bold text-slate-900 font-arabic">أي المواضيع تصل لجمهور أكبر من المعتاد؟</h3>
              <MetricNote platform={platform} />
              <IndexBars category="الموضوع" rows={summary.by_topic.map((t) => ({ label: t.label_ar, value: t.median_performance_index, sub: `${t.posts} منشور` }))} />
            </div>
            <div className={CARD}>
              <h3 className="text-sm font-bold text-slate-900 font-arabic">أي أشكال المحتوى تصل لجمهور أكبر من المعتاد؟</h3>
              <MetricNote platform={platform} />
              <IndexBars
                category="نوع المحتوى"
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

      {/* ── Embedded agent panels: each has its own window, independent of the filters above ── */}
      <div className="flex items-center gap-3 pt-2">
        <span className="h-px flex-1 bg-slate-200" />
        <span className="text-[11px] font-bold text-slate-500 font-arabic">الأقسام التالية لها نطاقها الزمني الخاص ولا تتبع الفلتر أعلاه</span>
        <span className="h-px flex-1 bg-slate-200" />
      </div>
      {/* Prediction accuracy is hidden until there is enough history to backtest (AccuracyCard);
          spikes and drops live on the diagnosis page, where each one can be diagnosed. */}
      <TrendingPanel limit={5} />

      {/* ── Publishing playbook: the patterns below combined into one decision per topic ── */}
      <PublishingPlaybook onCreateDraft={onCreateDraft} onNotify={onNotify} />

      {/* ── Shared Pattern Store: the evidence behind the playbook ── */}
      <PatternStore onNotify={onNotify} />
    </div>
  );
}
