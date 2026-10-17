import { useState, useEffect, useCallback, useRef } from 'react';
import {
  BookOpen, Copy, Check, RefreshCw, TrendingUp, TrendingDown, Lightbulb, Info, ShieldCheck, Search, X, AlertTriangle,
} from 'lucide-react';
import { Cell, Tooltip, ResponsiveContainer, PieChart, Pie } from 'recharts';
import { ApiError, apiFetch, describeError } from '../lib/api';

// Mirrors backend/schemas.py::Pattern.
interface ApiPattern {
  pattern_id: string;
  pattern: string;
  supporting_metric: string;
  confidence: number;
  affected_content_types: string[];
  dimension: string;
  slice_key: string;
  lift_pct: number;
  source: string;
  sample_size?: number | null; // posts (or episodes) the finding is based on
  q_value?: number | null; // FDR-adjusted p-value (per-post patterns only)
  typical_ratio?: number | null; // typical post in the slice / typical post outside it
  title?: string | null; // e.g. "قناة السعودية · وثائقي وثقافة"
  platform?: string | null;
  metric_ar?: string | null; // what was measured, e.g. "مرات الظهور"
  n_rest?: number | null;
  share_pct?: number | null; // Hajj platform-share patterns only
  computed_at?: string | null;
}

type CategoryKey = 'topic' | 'account' | 'content_type' | 'timing' | 'platform' | 'season';
type Filter = CategoryKey | 'all';

// Tabs group findings by the publishing decision they answer.
// Colors: validated categorical palette (dataviz reference slots 1-5, 7), fixed per category.
const CATEGORIES: { key: CategoryKey; label: string; dims: string[]; color: string; question: string }[] = [
  { key: 'topic', label: 'المواضيع', dims: ['topic_real'], color: '#1baf7a', question: 'أي المواضيع تحقق أكثر من المعتاد؟' },
  { key: 'account', label: 'الحساب والموضوع', dims: ['channel_topic_real'], color: '#eda100', question: 'أي موضوع يناسب أي حساب؟' },
  { key: 'content_type', label: 'شكل المحتوى', dims: ['content_type_real'], color: '#2a78d6', question: 'أي شكل محتوى يحقق أكثر؟' },
  { key: 'timing', label: 'وقت النشر', dims: ['timing_real'], color: '#eb6834', question: 'متى أنشر؟' },
  { key: 'platform', label: 'مقارنة المنصات', dims: ['platform_content_real'], color: '#e87ba4', question: 'أي شكل على أي منصة هو الأقوى؟' },
  { key: 'season', label: 'الحج والبودكاست', dims: ['platform_reach_real', 'awj_sada_real'], color: '#6250d6', question: 'ماذا حدث في موسم الحج والبودكاست؟' },
];
const categoryOf = (p: ApiPattern) => CATEGORIES.find((c) => c.dims.includes(p.dimension));

const PLATFORM_AR: Record<string, string> = {
  youtube: 'يوتيوب', x: 'إكس', instagram: 'إنستغرام', meta: 'ميتا', tiktok: 'تيك توك',
};
const PLATFORM_FILTERS = ['youtube', 'x', 'instagram'] as const;
const SHARE_COLOR: Record<string, string> = { youtube: '#2a78d6', x: '#eb6834', meta: '#1baf7a', tiktok: '#6250d6' };

const CARDS_PER_COLUMN = 4;
const UP = '#059669';
const DOWN = '#e11d48';

// One line on what to do with a finding. Only for post-level comparisons - season totals describe the past.
const ACTION: Partial<Record<CategoryKey, { up: string; down: string }>> = {
  topic: {
    up: 'أعطِ هذا الموضوع مساحة أكبر في خطة النشر على هذه المنصة.',
    down: 'راجع طريقة تقديم هذا الموضوع (العنوان، الصورة، أول ثانيتين) قبل زيادة كميته.',
  },
  account: {
    up: 'هذا الحساب مناسب لهذا الموضوع، فأكثِر منه هنا.',
    down: 'راجع طريقة تقديمه في هذا الحساب، أو انشره على حساب يحقق فيه نتائج أفضل.',
  },
  content_type: {
    up: 'استخدم هذا الشكل أكثر على هذه المنصة.',
    down: 'لا تعتمد عليه وحده، وجرّب تحويل أفضل لحظاته إلى مقاطع قصيرة.',
  },
  timing: {
    up: 'انشر المحتوى المهم في هذا الوقت.',
    down: 'تجنّب هذا الوقت للمحتوى المهم.',
  },
  platform: {
    up: 'هذا الشكل على هذه المنصة من أقوى ما تملكه الهيئة، فاجعله أولوية.',
    down: 'هذا الشكل أضعف على هذه المنصة، فوجّه جهده لمنصة أخرى.',
  },
};

// ── Wording ───────────────────────────────────────────────────────────────

// A label that reads on its own, without the tab it sits under:
// "موضوع «اقتصاد»", "«رياضة» في قناة الإخبارية", "النشر في نهاية الأسبوع"...
function labelOf(p: ApiPattern): string {
  const t = p.title ?? p.slice_key;
  switch (categoryOf(p)?.key) {
    case 'topic': return `موضوع ${t}`;
    case 'account': {
      const [account, topic] = t.split(' · ');
      return topic ? `«${topic}» في ${account}` : t;
    }
    case 'timing': return `النشر في ${t}`;
    case 'platform': return `${t} مقارنةً بكل المنصات`;
    default: return t;
  }
}

// Typical post in the slice / typical post outside it (1 = no difference).
function ratioOf(p: ApiPattern): number {
  return p.typical_ratio ?? 1 + p.lift_pct / 100;
}
const isUp = (p: ApiPattern) => p.lift_pct > 0;
const isCompared = (p: ApiPattern) => p.typical_ratio != null; // post-level test vs season totals

function signedPct(value: number): string {
  if (value === 0) return '0%';
  return `${value > 0 ? '+' : '−'}${Math.abs(value)}%`;
}
// The one number on the card: "+30%", "−26%", "2.0×", or a platform's share "87%".
function headline(p: ApiPattern): string {
  if (p.share_pct != null) return `${p.share_pct < 10 ? p.share_pct.toFixed(1) : Math.round(p.share_pct)}%`;
  const r = ratioOf(p);
  return r >= 1.95 ? `${r.toFixed(1)}×` : signedPct(Math.round((r - 1) * 100));
}
function headlineCaption(p: ApiPattern): string {
  if (p.share_pct != null) return 'من إجمالي الموسم';
  const r = ratioOf(p);
  // Post-level findings compare with the account's usual post; season totals with the other platforms/podcasts.
  const base = isCompared(p) ? 'المعتاد' : 'الباقي';
  if (r >= 1.95) return `ضعف ${base}`;
  return r > 1 ? `أعلى من ${base}` : `أقل من ${base}`;
}

function sampleLabel(p: ApiPattern): string | null {
  if (p.sample_size == null) return null;
  const n = p.sample_size.toLocaleString('en');
  if (p.dimension === 'awj_sada_real') return `مبني على ${n} فقط (عينة صغيرة)`;
  return `مبني على ${n} منشوراً`;
}
function reliability(p: ApiPattern): { label: string; tone: 'good' | 'weak'; hint: string } {
  if (p.q_value == null) {
    return { label: 'أرقام وصفية', tone: 'weak', hint: 'أرقام إجمالية منشورة، لم يُجرَ عليها اختبار إحصائي' };
  }
  const hint = `احتمال أن يكون الفرق صدفة: ${chanceLabel(p.q_value)}`;
  if (p.q_value < 0.001) return { label: 'موثوقية عالية جداً', tone: 'good', hint };
  if (p.q_value < 0.01) return { label: 'موثوقية عالية', tone: 'good', hint };
  return { label: 'موثوقية جيدة', tone: 'good', hint };
}
function chanceLabel(q: number): string {
  if (q < 0.001) return 'أقل من 1 في الألف';
  if (q < 0.01) return 'أقل من 1%';
  return `حوالي ${Math.max(1, Math.round(q * 100))}%`;
}
function computedAgo(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const minutes = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 60_000));
  if (Number.isNaN(minutes)) return null;
  if (minutes < 1) return 'حُسبت الآن';
  if (minutes < 60) return `حُسبت قبل ${minutes} دقيقة`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `حُسبت قبل ${hours} ساعة`;
  return `حُسبت قبل ${Math.floor(hours / 24)} يوماً`;
}
// Search ignores hamza/alef forms, ta marbuta, alef maqsura and diacritics: "الاخبارية" finds "الإخبارية".
function normalizeAr(s: string): string {
  return s
    .replace(/[ً-ْـ]/g, '')
    .replace(/[أإآ]/g, 'ا')
    .replace(/ة/g, 'ه')
    .replace(/ى/g, 'ي')
    .toLowerCase();
}

// What gets copied: the finding plus the numbers behind it, ready to paste into a report.
function copyText(p: ApiPattern): string {
  const parts = [p.pattern, sampleLabel(p), reliability(p).label].filter(Boolean);
  return parts.join(' · ');
}

const TOOLTIP_STYLE = { borderRadius: 12, fontFamily: 'Tajawal, sans-serif', direction: 'rtl' as const, textAlign: 'right' as const, fontSize: 12 };

// ── Charts ────────────────────────────────────────────────────────────────

function CategoryDonut({ patterns, active, onPick }: { patterns: ApiPattern[]; active: Filter; onPick: (k: Filter) => void }) {
  const data = CATEGORIES.map((c) => ({ ...c, value: patterns.filter((p) => c.dims.includes(p.dimension)).length }))
    .filter((d) => d.value > 0);
  const toggle = (k: CategoryKey) => onPick(active === k ? 'all' : k);
  return (
    <div className="flex items-center gap-4">
      <div className="w-32 h-32 shrink-0 relative" role="img" aria-label={`توزيع ${patterns.length} نتيجة حسب نوع القرار`}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data} dataKey="value" nameKey="label" innerRadius={38} outerRadius={60}
              stroke="#ffffff" strokeWidth={2} isAnimationActive={false}
              onClick={(d: { key: CategoryKey }) => toggle(d.key)}
            >
              {data.map((d) => (
                <Cell key={d.key} fill={d.color} opacity={active === 'all' || active === d.key ? 1 : 0.25} className="cursor-pointer" />
              ))}
            </Pie>
            <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v: number, name: string) => [`${v} نتيجة`, name]} />
          </PieChart>
        </ResponsiveContainer>
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
          <span className="text-xl font-black text-slate-900">{patterns.length}</span>
          <span className="text-[10px] text-slate-500 font-arabic">نتيجة</span>
        </div>
      </div>
      <ul className="space-y-0.5 flex-1 min-w-0">
        {data.map((d) => (
          <li key={d.key}>
            <button
              onClick={() => toggle(d.key)}
              aria-pressed={active === d.key}
              className={`w-full flex items-center gap-2 px-1.5 py-1 rounded-md text-right cursor-pointer transition-colors ${active === d.key ? 'bg-white shadow-2xs' : 'hover:bg-white/70'}`}
            >
              <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ backgroundColor: d.color }} />
              <span className="text-[11px] font-bold text-slate-700 font-arabic truncate">{d.label}</span>
              <span className="text-[11px] font-bold text-slate-500 mr-auto">{d.value}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

// Diverging bars in plain HTML: Arabic labels and «» quotes keep their direction (SVG ticks garble them).
// Each row is a button that jumps to its card.
function EffectBars({ patterns, onPick }: { patterns: ApiPattern[]; onPick: (p: ApiPattern) => void }) {
  const rows = patterns
    .filter(isCompared)
    .map((p) => ({ p, value: Math.round((ratioOf(p) - 1) * 100) }))
    .sort((a, b) => b.value - a.value);
  if (rows.length === 0) {
    return (
      <p className="text-xs text-slate-400 font-arabic text-center py-10">
        هذه النتائج أرقام إجمالية للموسم وليست مقارنة بين منشورات، لذلك تظهر في البطاقات أدناه.
      </p>
    );
  }
  const extent = Math.max(40, ...rows.map((r) => Math.abs(r.value)));
  return (
    <div>
      <div className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] gap-3 px-1.5 pb-1 text-[10px] font-bold text-slate-400 font-arabic">
        <span>النتيجة</span>
        <div className="grid grid-cols-2">
          <span className="text-right">أقل من المعتاد</span>
          <span className="text-left">أعلى من المعتاد</span>
        </div>
      </div>
      <ul className="space-y-0.5">
        {rows.map(({ p, value }) => {
          const cat = categoryOf(p);
          const width = `${(Math.abs(value) / extent) * 78}%`; // leaves room for the value label
          const color = value >= 0 ? UP : DOWN;
          const valueEl = <span className="text-[10px] font-black shrink-0" style={{ color }} dir="ltr">{signedPct(value)}</span>;
          return (
            <li key={p.pattern_id} className="group relative">
              <button
                onClick={() => onPick(p)}
                aria-label={`${p.pattern} اضغط لعرض البطاقة.`}
                className="w-full grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] items-center gap-3 px-1.5 py-1 rounded-lg hover:bg-slate-50 focus-visible:bg-slate-50 focus-visible:outline-2 focus-visible:outline-sky-400 cursor-pointer text-right"
              >
                <span className="flex items-center gap-1.5 min-w-0">
                  <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: cat?.color ?? '#94a3b8' }} />
                  <span className="text-[11px] font-bold text-slate-700 font-arabic truncate">{labelOf(p)}</span>
                  {p.platform && (
                    <span className="text-[9px] font-bold text-slate-500 font-arabic shrink-0 px-1.5 rounded-full bg-slate-100">
                      {PLATFORM_AR[p.platform] ?? p.platform}
                    </span>
                  )}
                </span>
                {/* RTL: the right half is "less than usual", the left half "more" - growth follows the reading direction. */}
                <span className="grid grid-cols-2 items-center h-5">
                  <span className="flex justify-end items-center gap-1 h-full border-l border-slate-400">
                    {value < 0 && <>{valueEl}<span className="block h-3.5 rounded-r" style={{ width, backgroundColor: color }} /></>}
                  </span>
                  <span className="flex justify-start items-center gap-1 h-full">
                    {value >= 0 && <><span className="block h-3.5 rounded-l" style={{ width, backgroundColor: color }} />{valueEl}</>}
                  </span>
                </span>
              </button>
              <div className="pointer-events-none absolute z-20 hidden group-hover:block group-focus-within:block top-full right-1/4 mt-1 w-80 bg-white border border-slate-200 rounded-xl shadow-md p-2.5 font-arabic">
                <p className="text-[11px] text-slate-700 leading-relaxed">{p.pattern}</p>
                <p className="text-[10px] text-slate-400 mt-1">{[sampleLabel(p), reliability(p).label].filter(Boolean).join(' · ')} · اضغط لعرض البطاقة</p>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function ShareDonut({ title, patterns }: { title: string; patterns: ApiPattern[] }) {
  const data = patterns
    .filter((p) => p.share_pct != null && p.platform)
    .map((p) => ({ key: p.platform as string, label: PLATFORM_AR[p.platform as string] ?? (p.platform as string), value: p.share_pct as number }))
    .sort((a, b) => b.value - a.value);
  // Platforms whose share was too close to an even split aren't stored as findings - show them as one slice.
  const rest = Math.round((100 - data.reduce((s, d) => s + d.value, 0)) * 10) / 10;
  if (rest >= 1) data.push({ key: 'other', label: 'منصات أخرى', value: rest });
  if (data.length < 2) return null;
  const fmt = (v: number) => `${v < 10 ? v.toFixed(1) : Math.round(v)}%`;
  return (
    <div>
      <p className="text-xs font-bold text-slate-800 font-arabic mb-2">{title}</p>
      <div className="flex items-center gap-3">
        <div className="w-24 h-24 shrink-0" role="img" aria-label={`${title}: ${data.map((d) => `${d.label} ${fmt(d.value)}`).join('، ')}`}>
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={data} dataKey="value" nameKey="label" innerRadius={26} outerRadius={46} stroke="#ffffff" strokeWidth={2} isAnimationActive={false}>
                {data.map((d) => <Cell key={d.key} fill={SHARE_COLOR[d.key] ?? '#cbd5e1'} />)}
              </Pie>
              <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v: number, name: string) => [fmt(v), name]} />
            </PieChart>
          </ResponsiveContainer>
        </div>
        <ul className="space-y-1">
          {data.map((d) => (
            <li key={d.key} className="flex items-center gap-2 text-[11px] font-arabic">
              <span className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: SHARE_COLOR[d.key] ?? '#cbd5e1' }} />
              <span className="font-bold text-slate-700">{d.label}</span>
              <span className="text-slate-500">{fmt(d.value)}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

// ── Card ──────────────────────────────────────────────────────────────────

function PatternCard({ p, copied, highlighted, onCopy }: { p: ApiPattern; copied: boolean; highlighted: boolean; onCopy: () => void }) {
  const cat = categoryOf(p);
  const up = isUp(p);
  const tone = up ? UP : DOWN;
  const rel = reliability(p);
  const sample = sampleLabel(p);
  const action = cat && ACTION[cat.key] ? ACTION[cat.key]![up ? 'up' : 'down'] : null;
  const r = ratioOf(p);
  const maxBar = Math.max(1, r);
  return (
    <article
      id={`pattern-${p.pattern_id}`}
      className={`scroll-mt-24 flex flex-col p-4 bg-white rounded-2xl border transition-all ${
        highlighted ? 'border-sky-400 ring-4 ring-sky-100' : 'border-slate-200/80 hover:border-slate-300 hover:shadow-sm'
      }`}
    >
      <div className="flex items-start gap-3">
        <div className="shrink-0 text-center min-w-[76px]">
          <div className="flex items-center justify-center gap-1" style={{ color: tone }}>
            {up ? <TrendingUp className="w-4 h-4" aria-hidden /> : <TrendingDown className="w-4 h-4" aria-hidden />}
            <span className="text-2xl font-black" dir="ltr">{headline(p)}</span>
          </div>
          <span className="text-[10px] font-bold font-arabic" style={{ color: tone }}>{headlineCaption(p)}</span>
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5 mb-1">
            {cat && (
              <span className="text-[10px] font-bold px-2 py-0.5 rounded-full font-arabic text-slate-700 bg-slate-100 flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: cat.color }} />
                {cat.label}
              </span>
            )}
            {p.platform && (
              <span className="text-[10px] font-bold px-2 py-0.5 rounded-full font-arabic text-slate-600 border border-slate-200">
                {PLATFORM_AR[p.platform] ?? p.platform}
              </span>
            )}
          </div>
          <h4 className="text-sm font-black text-slate-900 font-arabic leading-snug">{labelOf(p)}</h4>
        </div>
      </div>

      <p className="text-xs text-slate-700 font-arabic leading-relaxed mt-3">{p.pattern}</p>

      {isCompared(p) && (
        <div className="mt-3 space-y-1.5">
          {[
            { label: 'هذه المنشورات', value: r, color: tone },
            { label: 'المنشور المعتاد', value: 1, color: '#94a3b8' },
          ].map((b) => (
            <div key={b.label} className="flex items-center gap-2">
              <span className="text-[10px] text-slate-500 font-arabic w-24 shrink-0">{b.label}</span>
              <div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden">
                <div className="h-full rounded-full" style={{ width: `${(b.value / maxBar) * 100}%`, backgroundColor: b.color }} />
              </div>
              <span className="text-[10px] font-bold text-slate-600 w-8 text-left" dir="ltr">{Math.round(b.value * 100)}</span>
            </div>
          ))}
          <p className="text-[10px] text-slate-400 font-arabic">
            {p.metric_ar ? `المقياس: ${p.metric_ar}` : 'المقياس: الأداء'} · المنشور المعتاد = 100
          </p>
        </div>
      )}

      <div className="flex flex-wrap gap-1.5 mt-3">
        {sample && (
          <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full font-arabic border ${
            p.dimension === 'awj_sada_real' ? 'text-amber-700 bg-amber-50 border-amber-200' : 'text-slate-600 bg-slate-50 border-slate-200'
          }`}>
            {sample}
          </span>
        )}
        <span
          title={rel.hint}
          className={`text-[10px] font-bold px-2 py-0.5 rounded-full font-arabic border flex items-center gap-1 ${
            rel.tone === 'good' ? 'text-emerald-700 bg-emerald-50 border-emerald-200' : 'text-slate-500 bg-slate-50 border-slate-200'
          }`}
        >
          <ShieldCheck className="w-3 h-3" aria-hidden /> {rel.label}
        </span>
      </div>

      {action && (
        <div className="mt-3 flex items-start gap-1.5 p-2 rounded-xl bg-amber-50/50 border border-amber-100">
          <Lightbulb className="w-3.5 h-3.5 text-amber-500 shrink-0 mt-0.5" aria-hidden />
          <p className="text-[11px] text-slate-700 font-arabic leading-relaxed"><strong>المقترح:</strong> {action}</p>
        </div>
      )}

      <div className="mt-auto pt-3 flex items-center justify-between gap-2">
        <details className="min-w-0">
          <summary className="text-[10px] text-slate-400 font-arabic cursor-pointer hover:text-slate-600">
            كيف حُسبت؟{p.q_value != null ? ` · ${rel.hint}` : ''}
          </summary>
          <p className="mt-1 text-[10px] text-slate-500 font-arabic leading-relaxed">{p.supporting_metric}</p>
        </details>
        <button
          onClick={onCopy}
          aria-label="نسخ النتيجة مع أرقامها"
          className="shrink-0 flex items-center gap-1 text-xs font-bold text-slate-500 hover:text-emerald-700 transition-colors cursor-pointer font-arabic p-1 rounded-md hover:bg-emerald-50"
        >
          {copied
            ? <><Check className="w-3.5 h-3.5 text-emerald-600" aria-hidden /><span className="text-emerald-600">تم النسخ</span></>
            : <><Copy className="w-3.5 h-3.5" aria-hidden /><span>نسخ</span></>}
        </button>
      </div>
    </article>
  );
}

function ShowMore({ open, total, onToggle }: { open: boolean; total: number; onToggle: () => void }) {
  if (total <= CARDS_PER_COLUMN) return null;
  return (
    <button
      onClick={onToggle}
      aria-expanded={open}
      className="mt-3 w-full py-2 rounded-xl border border-slate-200 text-xs font-bold text-slate-600 hover:bg-slate-50 font-arabic cursor-pointer"
    >
      {open ? 'عرض أقل' : `عرض كل النتائج (${total})`}
    </button>
  );
}

function Skeleton() {
  return (
    <div className="space-y-5" aria-busy="true" aria-label="جارٍ تحميل الأنماط">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <div className="h-64 bg-slate-100 rounded-2xl animate-pulse" />
        <div className="lg:col-span-2 h-64 bg-slate-100 rounded-2xl animate-pulse" />
      </div>
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
        {Array.from({ length: 4 }).map((_, i) => <div key={i} className="h-48 bg-slate-100 rounded-2xl animate-pulse" />)}
      </div>
    </div>
  );
}

// ── Store ─────────────────────────────────────────────────────────────────

export default function PatternStore({ onNotify }: {
  onNotify?: (title: string, desc?: string, type?: 'success' | 'info') => void;
}) {
  const [patterns, setPatterns] = useState<ApiPattern[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [active, setActive] = useState<Filter>('all');
  const [platform, setPlatform] = useState<string>('all');
  const [query, setQuery] = useState('');
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [highlightId, setHighlightId] = useState<string | null>(null);
  const highlightTimer = useRef<number>();

  const load = useCallback(async () => {
    setIsLoading(true);
    setLoadError(null);
    try {
      setPatterns(await apiFetch<ApiPattern[]>('/api/patterns'));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return; // App switches to the login screen
      setLoadError(describeError(err).title);
    } finally {
      setIsLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  // A new filter starts collapsed, so "عرض الكل" never hides what a filter just selected.
  useEffect(() => { setExpanded({}); }, [active, platform, query]);

  // After jumping from a bar, scroll its card into view once it has rendered.
  useEffect(() => {
    if (!highlightId) return;
    document.getElementById(`pattern-${highlightId}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, [highlightId, expanded]);
  useEffect(() => () => window.clearTimeout(highlightTimer.current), []);

  const handleRefresh = async () => {
    if (isRefreshing) return;
    setIsRefreshing(true);
    try {
      const fresh = await apiFetch<ApiPattern[]>('/api/patterns/refresh', { method: 'POST' });
      setPatterns(fresh);
      setLoadError(null);
      onNotify?.('تم تحديث مخزن الأنماط', `${fresh.length} نتيجة محسوبة من أحدث البيانات`, 'success');
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return;
      onNotify?.('تعذر تحديث مخزن الأنماط', describeError(err).desc, 'info');
    } finally {
      setIsRefreshing(false);
    }
  };

  const handleCopy = async (p: ApiPattern) => {
    try {
      await navigator.clipboard.writeText(copyText(p));
      setCopiedId(p.pattern_id);
      setTimeout(() => setCopiedId((id) => (id === p.pattern_id ? null : id)), 2000);
    } catch {
      onNotify?.('تعذر النسخ', 'المتصفح لم يسمح بالوصول إلى الحافظة', 'info');
    }
  };

  const real = patterns.filter((p) => p.source.startsWith('real_')); // never show synthetic/demo patterns
  // Under "الكل", a cross-platform finding that repeats a same-platform one (e.g. live on YouTube) is not drawn
  // twice; it stays counted and listed under its own tab.
  const repeats = (p: ApiPattern) => p.dimension === 'platform_content_real'
    && real.some((o) => o.dimension === 'content_type_real' && o.platform === p.platform && o.title === p.title);
  const q = normalizeAr(query.trim());
  const matches = (p: ApiPattern) => !q || normalizeAr(`${labelOf(p)} ${p.pattern}`).includes(q);
  const shown = real.filter((p) =>
    (active === 'all' ? !repeats(p) : categoryOf(p)?.key === active)
    && (platform === 'all' || p.platform === platform)
    && matches(p));
  const byEffect = (a: ApiPattern, b: ApiPattern) => Math.abs(ratioOf(b) - 1) - Math.abs(ratioOf(a) - 1);
  // Post-level comparisons drive the two columns; season totals (Hajj, podcast) are descriptive and sit apart.
  const working = shown.filter((p) => isCompared(p) && isUp(p)).sort(byEffect);
  const review = shown.filter((p) => isCompared(p) && !isUp(p)).sort(byEffect);
  const season = shown.filter((p) => !isCompared(p)).sort(byEffect);
  const hajjShares = real.filter((p) => p.share_pct != null);
  const showShares = hajjShares.length > 0 && (active === 'all' || active === 'season') && platform === 'all' && !q;
  const activeCat = CATEGORIES.find((c) => c.key === active);
  const platformsPresent = PLATFORM_FILTERS.filter((k) => real.some((p) => p.platform === k));
  const filtered = active !== 'all' || platform !== 'all' || q !== '';
  const freshness = computedAgo(real[0]?.computed_at);

  const jumpTo = (p: ApiPattern) => {
    const col = !isCompared(p) ? 'season' : isUp(p) ? 'up' : 'down';
    const list = col === 'season' ? season : col === 'up' ? working : review;
    if (list.findIndex((x) => x.pattern_id === p.pattern_id) >= CARDS_PER_COLUMN) setExpanded((e) => ({ ...e, [col]: true }));
    setHighlightId(p.pattern_id);
    window.clearTimeout(highlightTimer.current);
    highlightTimer.current = window.setTimeout(() => setHighlightId(null), 2500);
  };
  const clearFilters = () => { setActive('all'); setPlatform('all'); setQuery(''); };

  const renderCards = (list: ApiPattern[], key: string, gridClass: string) => {
    const open = !!expanded[key];
    return (
      <>
        <div className={gridClass}>
          {(open ? list : list.slice(0, CARDS_PER_COLUMN)).map((p) => (
            <PatternCard
              key={p.pattern_id} p={p}
              copied={copiedId === p.pattern_id} highlighted={highlightId === p.pattern_id}
              onCopy={() => handleCopy(p)}
            />
          ))}
        </div>
        <ShowMore open={open} total={list.length} onToggle={() => setExpanded((e) => ({ ...e, [key]: !open }))} />
      </>
    );
  };

  return (
    <section className="bg-white border border-slate-200/90 rounded-2xl p-6 shadow-xs" aria-labelledby="pattern-store-title">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4 mb-4">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-emerald-50 text-emerald-700 rounded-xl border border-emerald-200/60">
            <BookOpen className="w-5 h-5" aria-hidden />
          </div>
          <div>
            <h3 id="pattern-store-title" className="text-base font-black text-slate-900 font-arabic">مخزن الأنماط المشترك</h3>
            <p className="text-xs text-slate-500 font-arabic">
              ما الذي ينجح وما الذي يحتاج مراجعة في محتوى الهيئة، محسوب من منشورات حقيقية
              {freshness && <span className="text-slate-400"> · {freshness}</span>}
            </p>
          </div>
        </div>
        <button
          onClick={handleRefresh}
          disabled={isRefreshing}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-slate-200 text-xs font-bold text-slate-600 hover:bg-slate-50 hover:text-slate-900 transition-colors cursor-pointer disabled:cursor-wait disabled:opacity-70 font-arabic"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin text-emerald-600' : ''}`} aria-hidden />
          {isRefreshing ? 'جارٍ إعادة الحساب...' : 'إعادة الحساب'}
        </button>
      </div>

      {/* How to read */}
      <div className="flex items-start gap-2 p-3 mb-4 rounded-xl bg-sky-50/60 border border-sky-100">
        <Info className="w-4 h-4 text-sky-600 shrink-0 mt-0.5" aria-hidden />
        <p className="text-[11px] text-slate-700 font-arabic leading-relaxed">
          <strong>كيف تقرأ الأرقام؟</strong> نقارن كل منشور بالمنشور المعتاد <em className="not-italic font-bold">لحسابه</em>، حتى لا يتفوق الحساب الكبير لمجرد حجمه.
          {' '}<strong className="text-emerald-700" dir="ltr">+30%</strong> تعني أن هذه المنشورات تحصل عادةً على أكثر من المعتاد بـ 30%،
          {' '}و<strong className="text-rose-600" dir="ltr">−26%</strong> تعني أقل بـ 26%.
          {' '}المقياس: المشاهدات على يوتيوب، ومرات الظهور على إكس، والإعجابات والتعليقات على إنستغرام.
        </p>
      </div>

      {isLoading ? (
        <Skeleton />
      ) : loadError ? (
        <div className="text-center py-10" role="alert">
          <AlertTriangle className="w-6 h-6 text-amber-500 mx-auto mb-2" aria-hidden />
          <p className="text-sm text-slate-700 font-arabic mb-3">تعذر تحميل الأنماط: {loadError}</p>
          <button onClick={load} className="px-4 py-1.5 rounded-lg bg-slate-900 text-white text-xs font-bold font-arabic cursor-pointer">إعادة المحاولة</button>
        </div>
      ) : real.length === 0 ? (
        <div className="text-center py-10">
          <p className="text-sm text-slate-600 font-arabic mb-3">لا توجد أنماط بعد. احسبها من البيانات المجمّعة.</p>
          <button onClick={handleRefresh} disabled={isRefreshing} className="px-4 py-1.5 rounded-lg bg-slate-900 text-white text-xs font-bold font-arabic cursor-pointer disabled:opacity-70">
            {isRefreshing ? 'جارٍ الحساب...' : 'احسب الأنماط الآن'}
          </button>
        </div>
      ) : (
        <>
          {/* Filters: one row above everything they affect */}
          <div className="flex flex-wrap items-center gap-2 mb-5">
            <div className="flex flex-wrap items-center gap-1 bg-slate-100 p-1 rounded-xl" role="group" aria-label="نوع القرار">
              {[{ key: 'all' as const, label: 'الكل' }, ...CATEGORIES].map((tab) => {
                const count = tab.key === 'all' ? real.length : real.filter((p) => categoryOf(p)?.key === tab.key).length;
                if (count === 0) return null;
                return (
                  <button
                    key={tab.key}
                    onClick={() => setActive(tab.key)}
                    aria-pressed={active === tab.key}
                    className={`px-3 py-1 rounded-lg text-xs font-bold font-arabic transition-all cursor-pointer ${active === tab.key ? 'bg-white text-slate-900 shadow-2xs' : 'text-slate-600 hover:text-slate-900'}`}
                  >
                    {tab.label} <span className="text-slate-400 font-normal">{count}</span>
                  </button>
                );
              })}
            </div>
            {platformsPresent.length > 1 && (
              <div className="flex items-center gap-1 bg-slate-100 p-1 rounded-xl" role="group" aria-label="المنصة">
                {[{ key: 'all', label: 'كل المنصات' }, ...platformsPresent.map((k) => ({ key: k, label: PLATFORM_AR[k] }))].map((o) => (
                  <button
                    key={o.key}
                    onClick={() => setPlatform(o.key)}
                    aria-pressed={platform === o.key}
                    className={`px-3 py-1 rounded-lg text-xs font-bold font-arabic transition-all cursor-pointer ${platform === o.key ? 'bg-white text-slate-900 shadow-2xs' : 'text-slate-600 hover:text-slate-900'}`}
                  >
                    {o.label}
                  </button>
                ))}
              </div>
            )}
            <label className="relative flex-1 min-w-[180px] max-w-xs">
              <span className="sr-only">ابحث عن حساب أو موضوع</span>
              <Search className="w-3.5 h-3.5 text-slate-400 absolute right-2.5 top-1/2 -translate-y-1/2" aria-hidden />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="ابحث عن حساب أو موضوع..."
                className="w-full pr-8 pl-7 py-1.5 rounded-xl border border-slate-200 text-xs font-arabic focus:outline-none focus:border-sky-400 focus:ring-2 focus:ring-sky-100"
              />
              {query && (
                <button onClick={() => setQuery('')} aria-label="مسح البحث" className="absolute left-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700 cursor-pointer">
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </label>
            {filtered && (
              <button onClick={clearFilters} className="text-[11px] font-bold text-sky-700 hover:underline font-arabic cursor-pointer">
                مسح الفلاتر
              </button>
            )}
          </div>

          {shown.length === 0 ? (
            <div className="text-center py-10 border border-dashed border-slate-200 rounded-2xl">
              <p className="text-sm text-slate-600 font-arabic mb-2">لا توجد نتائج تطابق هذه الفلاتر.</p>
              <button onClick={clearFilters} className="text-xs font-bold text-sky-700 hover:underline font-arabic cursor-pointer">مسح الفلاتر</button>
            </div>
          ) : (
            <>
              {/* Overview */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-5 mb-6">
                <div className="p-4 rounded-2xl border border-slate-200/80 bg-slate-50/60">
                  <p className="text-xs font-bold text-slate-800 font-arabic">عن ماذا تتحدث النتائج؟</p>
                  <p className="text-[10px] text-slate-400 font-arabic mb-3">اضغط على أي نوع لعرض نتائجه فقط</p>
                  <CategoryDonut patterns={real} active={active} onPick={setActive} />
                  <div className="grid grid-cols-2 gap-2 mt-4">
                    <div className="p-2.5 rounded-xl bg-white border border-emerald-100">
                      <p className="text-xl font-black text-emerald-700">{shown.filter(isUp).length}</p>
                      <p className="text-[10px] font-bold text-slate-500 font-arabic">نتائج أعلى من المعتاد</p>
                    </div>
                    <div className="p-2.5 rounded-xl bg-white border border-rose-100">
                      <p className="text-xl font-black text-rose-600">{shown.filter((p) => !isUp(p)).length}</p>
                      <p className="text-[10px] font-bold text-slate-500 font-arabic">نتائج أقل من المعتاد</p>
                    </div>
                  </div>
                </div>

                <div className="lg:col-span-2 p-4 rounded-2xl border border-slate-200/80">
                  <p className="text-xs font-bold text-slate-800 font-arabic">{activeCat ? activeCat.question : 'كم تبعد كل نتيجة عن المنشور المعتاد؟'}</p>
                  <p className="text-[10px] text-slate-400 font-arabic mb-3">
                    الخط الأوسط = المنشور المعتاد للحساب · مرّر الفأرة على أي سطر لقراءة النتيجة، واضغط لفتح بطاقتها
                  </p>
                  <EffectBars patterns={shown} onPick={jumpTo} />
                </div>
              </div>

              {showShares && (
                <div className="p-4 mb-6 rounded-2xl border border-slate-200/80">
                  <p className="text-xs font-bold text-slate-800 font-arabic">موسم حج 1445هـ: من أين جاء الوصول؟</p>
                  <p className="text-[10px] text-slate-400 font-arabic mb-3">حصة كل منصة من إجمالي الموسم، من إحصاءات الهيئة المنشورة</p>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
                    <ShareDonut title="مرات الظهور" patterns={hajjShares.filter((p) => p.slice_key.startsWith('impressions:'))} />
                    <ShareDonut title="المشاهدات" patterns={hajjShares.filter((p) => p.slice_key.startsWith('views:'))} />
                  </div>
                </div>
              )}

              {/* Cards, split by what to do with them */}
              {working.length + review.length > 0 && (
                <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
                  {[
                    { key: 'up', title: 'ما ينجح', hint: 'أعلى من المعتاد، فكرّره', list: working, color: UP, icon: <TrendingUp className="w-4 h-4" aria-hidden /> },
                    { key: 'down', title: 'ما يحتاج مراجعة', hint: 'أقل من المعتاد، فراجعه قبل تكراره', list: review, color: DOWN, icon: <TrendingDown className="w-4 h-4" aria-hidden /> },
                  ].map((col) => (
                    <div key={col.key}>
                      <div className="flex items-center gap-2 mb-3">
                        <span className="p-1 rounded-lg text-white" style={{ backgroundColor: col.color }}>{col.icon}</span>
                        <h4 className="text-sm font-black text-slate-900 font-arabic">{col.title} <span className="text-slate-400 font-bold">({col.list.length})</span></h4>
                        <span className="text-[11px] text-slate-500 font-arabic">{col.hint}</span>
                      </div>
                      {col.list.length === 0 ? (
                        <p className="text-xs text-slate-400 font-arabic text-center py-6 border border-dashed border-slate-200 rounded-2xl">لا توجد نتائج هنا ضمن الفلاتر الحالية.</p>
                      ) : renderCards(col.list, col.key, 'grid grid-cols-1 md:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2 gap-3')}
                    </div>
                  ))}
                </div>
              )}

              {season.length > 0 && (
                <div className={working.length + review.length > 0 ? 'mt-6 pt-5 border-t border-slate-100' : ''}>
                  <div className="flex flex-wrap items-baseline gap-2 mb-3">
                    <h4 className="text-sm font-black text-slate-900 font-arabic">موسم الحج وبودكاست أوج | صدى <span className="text-slate-400 font-bold">({season.length})</span></h4>
                    <span className="text-[11px] text-slate-500 font-arabic">أرقام إجمالية منشورة تقارن المنصات والبرامج ببعضها، وليست مقارنة على مستوى المنشور</span>
                  </div>
                  {renderCards(season, 'season', 'grid grid-cols-1 md:grid-cols-2 2xl:grid-cols-3 gap-3')}
                </div>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
