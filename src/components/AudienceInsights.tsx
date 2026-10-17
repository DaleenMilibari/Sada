import { useCallback, useEffect, useState } from 'react';
import { CheckCircle2, ClipboardCheck, Copy, ExternalLink, Lightbulb, Loader2, Sparkles, Target, Wand2 } from 'lucide-react';
import { apiFetch, describeError } from '../lib/api';
import { ScopeTag } from './ContextBar';
import type { AudienceAccuracy, AudienceSummary, AudienceThemes, OptimizerDraft, Platform, ReviewItem } from '../types';

const PLATFORM_LABEL: Record<Platform, string> = { youtube: 'يوتيوب', instagram: 'إنستغرام', x: 'إكس' };
const pct = (x: number) => `${Math.round(x * 100)}%`;

export const INTENT_LABEL: Record<string, string> = {
  praise: 'إشادة',
  criticism: 'انتقاد',
  request: 'طلب أو اقتراح',
  question: 'سؤال',
  reaction: 'تفاعل مع الحدث',
  other: 'أخرى',
};
const SENTIMENT_LABEL: Record<string, string> = { positive: 'إيجابي تجاه الهيئة', neutral: 'محايد', negative: 'سلبي تجاه الهيئة' };

function Shell({ title, subtitle, icon, children, action }: {
  title: string; subtitle?: string; icon: React.ReactNode; children: React.ReactNode; action?: React.ReactNode;
}) {
  return (
    <div className="bg-white rounded-2xl border border-slate-200/80 p-6 shadow-2xs">
      <div className="flex items-start justify-between gap-3 mb-4">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-xl bg-emerald-50 border border-emerald-100 text-emerald-700">{icon}</div>
          <div>
            <h3 className="text-sm font-bold text-slate-900 font-arabic">{title}</h3>
            {subtitle && <p className="text-[11px] text-slate-400 font-arabic">{subtitle}</p>}
          </div>
        </div>
        {action}
      </div>
      {children}
    </div>
  );
}

// ── The page in a few sentences: computed from the data, no model involved ──

export function audienceShares(summary: AudienceSummary) {
  const count = (k: string) => summary.intents.find((i) => i.intent === k)?.count ?? 0;
  const classified = summary.totals.classified;
  const directed = classified - count('reaction') - count('other');
  return { classified, directed, count };
}

export function InsightsCard({ summary, themes }: { summary: AudienceSummary; themes: AudienceThemes | null }) {
  const { classified, directed, count } = audienceShares(summary);
  if (classified < 10) return null;
  const lines: React.ReactNode[] = [];
  if (directed >= 10) {
    lines.push(
      <>
        من الردود الموجّهة للقنوات: <strong>{pct(count('criticism') / directed)}</strong> انتقاد،{' '}
        <strong>{pct(count('praise') / directed)}</strong> إشادة، و<strong>{pct((count('request') + count('question')) / directed)}</strong> طلبات وأسئلة.
      </>,
    );
  }
  const critical = [...summary.by_channel].filter((c) => c.negative > 0).sort((a, b) => b.negative - a.negative)[0];
  if (critical) {
    lines.push(
      <>
        أكثر حساب يتلقى ردوداً سلبية تجاهه: <strong>{critical.name_ar} ({PLATFORM_LABEL[critical.platform]})</strong> — {critical.negative} رداً من أصل{' '}
        {critical.comments}.
      </>,
    );
  }
  if (lines.length === 0) return null;
  return (
    <div className="rounded-2xl border border-emerald-200 bg-gradient-to-l from-emerald-50 to-white p-6">
      <div className="flex items-center gap-2 mb-3">
        <Lightbulb className="w-4 h-4 text-emerald-700" />
        <h3 className="text-sm font-bold text-emerald-900 font-arabic">الخلاصة في سطور</h3>
      </div>
      <ul className="space-y-2">
        {lines.map((l, i) => (
          <li key={i} className="flex gap-2 text-[13px] text-slate-700 font-arabic leading-relaxed">
            <span className="mt-2 w-1.5 h-1.5 rounded-full bg-emerald-600 shrink-0" />
            <span>{l}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ── Requests & criticism grouped into themes, each with a recommendation ──

export function ThemesCard({ themes, loading, onCreateDraft, onNotify }: {
  themes: AudienceThemes | null;
  loading: boolean;
  onCreateDraft?: (draft: OptimizerDraft) => void;
  onNotify?: (title: string, desc?: string, type?: 'success' | 'info') => void;
}) {
  const status = themes?.status;
  return (
    <Shell
      title="توصيات من صوت الجمهور"
      subtitle="طلبات وانتقادات متكررة مع إجراء مقترح لكل منها · كل موضوع مبني على تعليقين حقيقيين على الأقل"
      icon={<Target className="w-4 h-4" />}
    >
      {loading && (
        <div className="flex items-center gap-2 text-xs text-slate-500 font-arabic py-6 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" /> يحلل الذكاء الاصطناعي الطلبات والانتقادات...
        </div>
      )}
      {!loading && status && status !== 'ok' && (
        <p className="text-xs text-slate-400 font-arabic py-4">
          {status === 'not_enough_comments' ? 'لا توجد طلبات أو انتقادات كافية في هذه الفترة.' : 'تعذر تحليل المواضيع الآن - حاول لاحقاً.'}
        </p>
      )}
      {!loading && status === 'ok' && themes!.themes.length === 0 && (
        <p className="text-xs text-slate-400 font-arabic py-4">لم تتكرر طلبات أو انتقادات بما يكفي لتكوين موضوع.</p>
      )}
      {!loading && status === 'ok' && themes!.themes.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {themes!.themes.map((t) => (
            <div key={t.title} className="flex flex-col rounded-xl border border-slate-200/80 bg-slate-50/60 p-4">
              <div className="flex items-center justify-between gap-2 mb-2">
                <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border font-arabic ${
                  t.kind === 'request' ? 'bg-sky-50 text-sky-700 border-sky-200' : 'bg-rose-50 text-rose-700 border-rose-200'
                }`}>
                  {t.kind === 'request' ? 'طلب متكرر' : 'انتقاد متكرر'}
                </span>
                <span className="text-[11px] text-slate-500 font-arabic">
                  {t.count} تعليقاً · {t.accounts.map((a) => a.name_ar).slice(0, 2).join('، ')}
                </span>
              </div>
              <p className="text-sm font-bold text-slate-900 font-arabic mb-2">{t.title}</p>
              <div className="flex gap-2 p-2.5 rounded-lg bg-white border border-emerald-100 mb-3">
                <Sparkles className="w-3.5 h-3.5 text-emerald-600 mt-0.5 shrink-0" />
                <p className="text-xs text-slate-700 font-arabic leading-relaxed">{t.recommendation}</p>
              </div>
              <ul className="space-y-1.5 mb-3">
                {t.examples.slice(0, 2).map((e, i) => (
                  <li key={i}>
                    <a href={e.url} target="_blank" rel="noreferrer" className="group text-[11px] text-slate-600 font-arabic leading-relaxed hover:text-emerald-700">
                      «{e.text.length > 120 ? `${e.text.slice(0, 120)}…` : e.text}»
                      <ExternalLink className="inline w-3 h-3 mr-1 opacity-50 group-hover:opacity-100" />
                    </a>
                  </li>
                ))}
              </ul>
              <div className="mt-auto flex gap-2">
                {t.kind === 'request' && onCreateDraft && (
                  <button
                    onClick={() => onCreateDraft({
                      text: t.recommendation,
                      topic: t.topic,
                      entityKey: t.main_entity_key,
                      source: `صوت الجمهور: «${t.title}» (${t.count} تعليقاً)`,
                    })}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-700 text-white text-xs font-bold font-arabic hover:bg-emerald-800 cursor-pointer"
                  >
                    <Wand2 className="w-3.5 h-3.5" /> حوّلها لمسودة محتوى
                  </button>
                )}
                <button
                  onClick={() => {
                    navigator.clipboard?.writeText(`${t.title}\n${t.recommendation}`);
                    onNotify?.('تم نسخ التوصية', 'يمكنك مشاركتها مع فريق المحتوى', 'success');
                  }}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 bg-white text-slate-600 text-xs font-bold font-arabic hover:bg-slate-50 cursor-pointer"
                >
                  <Copy className="w-3.5 h-3.5" /> نسخ التوصية
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </Shell>
  );
}

// ── Measured accuracy against blind human review ──

const INTENT_ORDER = ['praise', 'criticism', 'request', 'question', 'reaction', 'other'];
const SENTIMENT_ORDER = ['positive', 'neutral', 'negative'];

function ReviewPanel({ onSaved, onClose }: { onSaved: () => void; onClose: () => void }) {
  const [item, setItem] = useState<ReviewItem | null | undefined>(undefined);
  const [intent, setIntent] = useState<string | null>(null);
  const [sentiment, setSentiment] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [done, setDone] = useState(0);

  const next = useCallback(async () => {
    setIntent(null);
    setSentiment(null);
    const queue = await apiFetch<ReviewItem[]>('/api/audience/review/next');
    setItem(queue[0] ?? null);
  }, []);

  useEffect(() => {
    next();
  }, [next]);

  const neutralByRule = intent === 'reaction' || intent === 'other';
  const save = async () => {
    if (!item || !intent || (!sentiment && !neutralByRule)) return;
    setSaving(true);
    try {
      await apiFetch('/api/audience/review', {
        method: 'POST',
        body: JSON.stringify({ comment_id: item.comment_id, intent, sentiment: neutralByRule ? 'neutral' : sentiment }),
      });
      setDone((d) => d + 1);
      onSaved();
      await next();
    } finally {
      setSaving(false);
    }
  };

  const pill = (active: boolean, disabled = false) =>
    `px-3 py-1.5 rounded-lg text-xs font-bold font-arabic border transition-colors ${
      disabled ? 'opacity-40 cursor-not-allowed border-slate-200 text-slate-400'
        : active ? 'bg-slate-900 text-white border-slate-900 cursor-pointer' : 'bg-white text-slate-700 border-slate-200 hover:bg-slate-50 cursor-pointer'
    }`;

  return (
    <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs font-bold text-slate-700 font-arabic">مراجعة بشرية عمياء · راجعت {done} في هذه الجلسة</p>
        <button onClick={onClose} className="text-xs text-slate-500 font-arabic hover:text-slate-800 cursor-pointer">إنهاء المراجعة</button>
      </div>
      {item === undefined && <Loader2 className="w-4 h-4 animate-spin text-slate-400" />}
      {item === null && <p className="text-xs text-slate-500 font-arabic">لا توجد تعليقات أخرى بانتظار المراجعة.</p>}
      {item && (
        <>
          <div className="bg-white rounded-lg border border-slate-200 p-3 mb-3">
            <p className="text-sm text-slate-900 font-arabic leading-relaxed">«{item.text}»</p>
            <a href={item.url} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-[11px] text-slate-500 mt-2 hover:text-emerald-700">
              <ExternalLink className="w-3 h-3" /> ردّ على: {item.title.slice(0, 80)} · {item.channel_name_ar} · {PLATFORM_LABEL[item.platform]}
            </a>
          </div>
          <p className="text-[11px] text-slate-500 font-arabic mb-1.5">1) عن ماذا يتحدث الرد؟</p>
          <div className="flex flex-wrap gap-1.5 mb-3">
            {INTENT_ORDER.map((k) => (
              <button key={k} onClick={() => setIntent(k)} className={pill(intent === k)}>{INTENT_LABEL[k]}</button>
            ))}
          </div>
          <p className="text-[11px] text-slate-500 font-arabic mb-1.5">
            2) موقفه من الهيئة أو قناتها أو محتواها {neutralByRule && '(محايد تلقائياً: الرد ليس عن الهيئة)'}
          </p>
          <div className="flex flex-wrap gap-1.5 mb-3">
            {SENTIMENT_ORDER.map((k) => (
              <button key={k} disabled={neutralByRule} onClick={() => setSentiment(k)} className={pill(neutralByRule ? k === 'neutral' : sentiment === k, neutralByRule)}>
                {SENTIMENT_LABEL[k]}
              </button>
            ))}
          </div>
          <div className="flex gap-2">
            <button
              onClick={save}
              disabled={saving || !intent || (!sentiment && !neutralByRule)}
              className="px-4 py-1.5 rounded-lg bg-emerald-700 text-white text-xs font-bold font-arabic disabled:opacity-40 cursor-pointer"
            >
              {saving ? 'جارٍ الحفظ...' : 'حفظ والتالي'}
            </button>
            <button onClick={next} className="px-4 py-1.5 rounded-lg border border-slate-200 bg-white text-slate-600 text-xs font-bold font-arabic cursor-pointer">
              تخطّي
            </button>
          </div>
        </>
      )}
    </div>
  );
}

export function AccuracyPanel({ onNotify }: { onNotify?: (title: string, desc?: string, type?: 'success' | 'info') => void }) {
  const [acc, setAcc] = useState<AudienceAccuracy | null>(null);
  const [reviewing, setReviewing] = useState(false);

  const load = useCallback(async () => {
    try {
      setAcc(await apiFetch<AudienceAccuracy>('/api/audience/accuracy'));
    } catch (err) {
      onNotify?.('تعذر تحميل دقة التحليل', describeError(err).desc, 'info');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <Shell
      title="دقة تحليل الجمهور"
      subtitle="مقارنة تصنيف الذكاء الاصطناعي بمراجعة بشرية عمياء: المراجع لا يرى تصنيف النموذج قبل أن يصنّف"
      icon={<ClipboardCheck className="w-4 h-4" />}
      action={(
        <div className="flex items-center gap-2">
          <ScopeTag fixed>كل التعليقات المراجَعة</ScopeTag>
          {!reviewing && (
            <button onClick={() => setReviewing(true)} className="px-3 py-1.5 rounded-lg bg-slate-900 text-white text-xs font-bold font-arabic cursor-pointer">
              راجع تعليقات
            </button>
          )}
        </div>
      )}
    >
      {!acc && <Loader2 className="w-4 h-4 animate-spin text-slate-400" />}
      {acc && acc.n === 0 && (
        <p className="text-xs text-slate-500 font-arabic leading-relaxed">
          لم تُراجع أي تعليقات بعد. اضغط «راجع تعليقات» وصنّف بنفسك {acc.min_for_accuracy} تعليقاً على الأقل لقياس دقة النموذج
          ({acc.pending} تعليقاً متاحاً للمراجعة).
        </p>
      )}
      {acc && acc.n > 0 && acc.intent && acc.sentiment && (
        <>
          <div className="grid grid-cols-2 gap-3">
            {[
              { label: 'دقة تحديد نوع الرد', s: acc.intent },
              { label: 'دقة تحديد الموقف من الهيئة', s: acc.sentiment },
            ].map(({ label, s }) => (
              <div key={label} className="rounded-xl bg-slate-50 border border-slate-200/70 p-4">
                <p className="text-2xl font-black text-slate-900">{pct(s.accuracy)}</p>
                <p className="text-xs text-slate-600 font-arabic mt-0.5">{label}</p>
                <p className="text-[10px] text-slate-400 mt-1" dir="ltr">
                  macro-F1 {s.macro_f1 ?? '—'} · Cohen's κ {s.kappa}
                </p>
              </div>
            ))}
          </div>
          <p className={`text-[11px] font-arabic mt-3 ${acc.preliminary ? 'text-amber-700' : 'text-slate-500'}`}>
            <CheckCircle2 className="inline w-3.5 h-3.5 ml-1" />
            مبني على {acc.n} تعليقاً راجعها إنسان دون رؤية تصنيف النموذج
            {acc.preliminary ? ` · نتيجة أولية (نحتاج ${acc.min_for_accuracy} على الأقل)` : ''} · النموذج: {acc.model}
          </p>
          <details className="mt-2">
            <summary className="text-[11px] text-slate-400 font-arabic cursor-pointer hover:text-slate-600">الدقة لكل فئة (للمختصين)</summary>
            <table className="w-full mt-2 text-[11px]" dir="rtl">
              <thead>
                <tr className="text-slate-400 font-arabic">
                  <th className="text-right font-normal">الفئة</th><th className="font-normal">Precision</th><th className="font-normal">Recall</th><th className="font-normal">F1</th><th className="font-normal">n</th>
                </tr>
              </thead>
              <tbody>
                {[...acc.intent.per_class].map((c) => (
                  <tr key={c.label} className="text-slate-700 text-center">
                    <td className="text-right font-arabic">{INTENT_LABEL[c.label] ?? c.label}</td>
                    <td>{c.precision}</td><td>{c.recall}</td><td>{c.f1}</td><td>{c.support}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </>
      )}
      {reviewing && <ReviewPanel onSaved={load} onClose={() => setReviewing(false)} />}
    </Shell>
  );
}
