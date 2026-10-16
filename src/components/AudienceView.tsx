import { useCallback, useEffect, useState } from 'react';
import { ExternalLink, Heart, Loader2, MessageCircle, MessagesSquare, Smile, Target, TrendingUp } from 'lucide-react';
import { apiFetch, describeError } from '../lib/api';
import type { AudienceSummary, AudienceThemes, OptimizerDraft, Platform, SentimentStats } from '../types';
import { AccuracyPanel, audienceShares, InsightsCard, ThemesCard } from './AudienceInsights';

interface AudienceViewProps {
  onNotify?: (title: string, desc?: string, type?: 'success' | 'info') => void;
  onCreateDraft?: (draft: OptimizerDraft) => void;
}

const REFRESH_MS = 60_000;
const DAYS_OPTIONS = [7, 30, 60];
const PLATFORM_TABS: { key: Platform | 'all'; label: string }[] = [
  { key: 'all', label: 'الكل' },
  { key: 'youtube', label: 'يوتيوب' },
  { key: 'x', label: 'إكس' },
];
const PLATFORM_LABEL: Record<Platform, string> = { youtube: 'يوتيوب', instagram: 'إنستغرام', x: 'إكس' };
const SENTIMENT_LABEL = { positive: 'إيجابي', negative: 'سلبي', neutral: 'محايد' } as const;
const INTENT_STYLE: Record<string, string> = {
  praise: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  criticism: 'bg-rose-50 text-rose-700 border-rose-200',
  request: 'bg-sky-50 text-sky-700 border-sky-200',
  question: 'bg-amber-50 text-amber-700 border-amber-200',
  reaction: 'bg-violet-50 text-violet-700 border-violet-200',
  other: 'bg-slate-50 text-slate-600 border-slate-200',
};

const compact = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 });
const percent = new Intl.NumberFormat('en', { style: 'percent', maximumFractionDigits: 0 });
const signedPercent = new Intl.NumberFormat('en', { style: 'percent', maximumFractionDigits: 0, signDisplay: 'always' });

function Segmented<T extends string | number>({ options, value, onChange }: {
  options: { key: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="flex bg-slate-100 rounded-xl p-1 gap-1">
      {options.map((o) => (
        <button
          key={String(o.key)}
          onClick={() => onChange(o.key)}
          className={`px-3 py-1.5 rounded-lg text-xs font-bold font-arabic transition-colors cursor-pointer ${
            value === o.key ? 'bg-white text-slate-900 shadow-2xs' : 'text-slate-500 hover:text-slate-700'
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function Kpi({ icon, label, value, hint }: { icon: React.ReactNode; label: string; value: string; hint?: string }) {
  return (
    <div className="bg-white rounded-2xl border border-slate-200/80 p-5 shadow-2xs">
      <div className="flex items-center justify-between mb-3">
        <div className="p-2.5 rounded-xl bg-slate-50 border border-slate-200/70 text-slate-600">{icon}</div>
        {hint && <span className="text-[10px] text-slate-400 font-arabic">{hint}</span>}
      </div>
      {/* Plain numbers render LTR so signs stay in place (-0.8%, not 0.8%-); Arabic text stays RTL. */}
      <p className="text-2xl font-black text-slate-900 font-arabic">
        <span dir={/[؀-ۿ]/.test(value) ? 'rtl' : 'ltr'}>{value}</span>
      </p>
      <p className="text-xs text-slate-500 font-arabic mt-1">{label}</p>
    </div>
  );
}

// Stacked positive / neutral / negative bar over classified comments; says so when the sample is too small.
// Positive / neutral / negative among the replies that talk about the channel itself.
const MIN_DIRECTED = 10;
function SentimentBar({ s }: { s: SentimentStats }) {
  if (s.directed < MIN_DIRECTED) {
    return (
      <p className="text-[11px] text-slate-400 font-arabic">
        ردود قليلة تتحدث عن القناة نفسها ({s.directed} من {s.classified}) - لا يكفي للحكم
      </p>
    );
  }
  const neutral = s.directed - s.positive - s.negative;
  const part = (n: number) => `${(n / s.directed) * 100}%`;
  return (
    <div>
      <div className="flex h-2.5 rounded-full overflow-hidden bg-slate-100">
        <div className="bg-emerald-500" style={{ width: part(s.positive) }} title={`إيجابي ${s.positive}`} />
        <div className="bg-slate-300" style={{ width: part(neutral) }} title={`محايد ${neutral}`} />
        <div className="bg-rose-500" style={{ width: part(s.negative) }} title={`سلبي ${s.negative}`} />
      </div>
      <p className="text-[10px] text-slate-500 font-arabic mt-1">
        إيجابي {percent.format(s.positive / s.directed)} · سلبي {percent.format(s.negative / s.directed)} · من {s.directed} رداً
        يتحدث عن القناة (و{s.classified - s.directed} رداً تفاعلاً مع الحدث)
      </p>
    </div>
  );
}

function Card({ title, subtitle, icon, children }: { title: string; subtitle?: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="bg-white rounded-2xl border border-slate-200/80 p-6 shadow-2xs">
      <div className="flex items-center gap-3 mb-4">
        <div className="p-2 rounded-xl bg-emerald-50 border border-emerald-100 text-emerald-700">{icon}</div>
        <div>
          <h3 className="text-sm font-bold text-slate-900 font-arabic">{title}</h3>
          {subtitle && <p className="text-[11px] text-slate-400 font-arabic">{subtitle}</p>}
        </div>
      </div>
      {children}
    </div>
  );
}

export default function AudienceView({ onNotify, onCreateDraft }: AudienceViewProps) {
  const [platform, setPlatform] = useState<Platform | 'all'>('all');
  const [days, setDays] = useState(30);
  const [summary, setSummary] = useState<AudienceSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [themes, setThemes] = useState<AudienceThemes | null>(null);
  const [themesLoading, setThemesLoading] = useState(false);

  // Themes need one (cached) AI call, so they load separately and don't hold up the page.
  useEffect(() => {
    let alive = true;
    setThemes(null);
    setThemesLoading(true);
    const query = `days=${days}${platform === 'all' ? '' : `&platform=${platform}`}`;
    apiFetch<AudienceThemes>(`/api/audience/themes?${query}`)
      .then((t) => alive && setThemes(t))
      .catch(() => alive && setThemes({ generated_at: '', days, platform: null, n_comments: 0, status: 'llm_failed', themes: [] }))
      .finally(() => alive && setThemesLoading(false));
    return () => {
      alive = false;
    };
  }, [days, platform]);

  const load = useCallback(async () => {
    try {
      const query = `days=${days}${platform === 'all' ? '' : `&platform=${platform}`}`;
      setSummary(await apiFetch<AudienceSummary>(`/api/audience/summary?${query}`));
      setError(null);
    } catch (err) {
      setError(describeError(err).title);
      onNotify?.('تعذر تحميل تحليل الجمهور', describeError(err).desc, 'info');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [days, platform]);

  useEffect(() => {
    setSummary(null);
    load();
    const id = window.setInterval(load, REFRESH_MS);
    return () => window.clearInterval(id);
  }, [load]);

  const t = summary?.totals;
  const empty = summary && t && t.comments === 0 && summary.follower_growth.length === 0;
  // Replies about the channels/content themselves (not reactions to the news) - the base for sentiment shares.
  const { classified, directed } = summary ? audienceShares(summary) : { classified: 0, directed: 0 };
  const directedShare = classified >= 10 ? directed / classified : null;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-bold text-slate-900 font-arabic">صوت الجمهور</h2>
          <p className="text-xs text-slate-400 font-arabic">
            تعليقات وردود الجمهور العامة على منشورات الهيئة، مصنّفة آلياً · تحليل إجمالي دون أي بيانات تعريفية بالأشخاص
          </p>
        </div>
        <div className="flex gap-2">
          <Segmented options={PLATFORM_TABS} value={platform} onChange={setPlatform} />
          <Segmented options={DAYS_OPTIONS.map((d) => ({ key: d, label: `${d} يوماً` }))} value={days} onChange={setDays} />
        </div>
      </div>

      {error && !summary && <p className="text-sm text-rose-600 font-arabic">{error}</p>}
      {!summary && !error && (
        <div className="flex justify-center py-20 text-slate-400"><Loader2 className="w-6 h-6 animate-spin" /></div>
      )}

      {empty && (
        <div className="bg-white rounded-2xl border border-dashed border-slate-300 p-12 text-center">
          <MessagesSquare className="w-8 h-8 text-slate-300 mx-auto mb-3" />
          <p className="text-sm font-bold text-slate-700 font-arabic">لا توجد تعليقات مجمّعة في هذه الفترة بعد</p>
          <p className="text-xs text-slate-400 font-arabic mt-1">
            تُجمع تعليقات يوتيوب وردود إكس تلقائياً مع دورات جمع البيانات، ثم تُصنّف بالذكاء الاصطناعي.
          </p>
        </div>
      )}

      {summary && t && !empty && (
        <>
          <InsightsCard summary={summary} themes={themes} />

          <div className="grid grid-cols-1 md:grid-cols-4 gap-5">
            <Kpi
              icon={<MessageCircle className="w-5 h-5" />}
              label="ردود وتعليقات حلّلها الذكاء الاصطناعي"
              value={`${t.classified.toLocaleString('en')} من ${t.comments.toLocaleString('en')}`}
              hint="بلا أي بيانات تعريفية"
            />
            <Kpi
              icon={<Target className="w-5 h-5" />}
              label="تتحدث عن القنوات أو محتواها"
              value={directedShare === null ? '—' : percent.format(directedShare)}
              hint={`${directed} رداً`}
            />
            <Kpi
              icon={<Heart className="w-5 h-5" />}
              label="إيجابية من الردود الموجّهة للقنوات"
              value={directed >= 10 ? percent.format(t.positive / directed) : '—'}
              hint={directed >= 10 ? `سلبية: ${percent.format(t.negative / directed)}` : 'عينة صغيرة'}
            />
            <Kpi
              icon={<Smile className="w-5 h-5" />}
              label="صافي الموقف من القنوات (إيجابي − سلبي)"
              value={directed >= 10 ? signedPercent.format((t.positive - t.negative) / directed) : '—'}
              hint="من الردود الموجّهة لها"
            />
          </div>

          <ThemesCard themes={themes} loading={themesLoading} onCreateDraft={onCreateDraft} onNotify={onNotify} />

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <Card title="الموقف من كل حساب" subtitle="من الردود التي تتحدث عن القناة أو محتواها أو تغطيتها - لا من التفاعل مع الخبر نفسه" icon={<Smile className="w-4 h-4" />}>
              <div className="space-y-4">
                {summary.by_channel.length === 0 && <p className="text-xs text-slate-400 font-arabic">لا توجد بيانات.</p>}
                {summary.by_channel.map((c) => (
                  <div key={`${c.platform}-${c.entity_key}`}>
                    <div className="flex justify-between mb-1">
                      <span className="text-xs font-bold text-slate-800 font-arabic">{c.name_ar} ({PLATFORM_LABEL[c.platform]})</span>
                      <span className="text-[11px] text-slate-500">{c.comments.toLocaleString('en')} تعليق</span>
                    </div>
                    <SentimentBar s={c} />
                  </div>
                ))}
              </div>
            </Card>

            <Card title="نمو المتابعين" subtitle="من قياسات دورية لعدد المتابعين" icon={<TrendingUp className="w-4 h-4" />}>
              <div className="space-y-3">
                {summary.follower_growth.length === 0 && <p className="text-xs text-slate-400 font-arabic">لا توجد قياسات بعد.</p>}
                {summary.follower_growth.length > 0 && summary.follower_growth.every((g) => g.change === null) && (
                  <p className="text-[11px] text-amber-700 bg-amber-50 border border-amber-100 rounded-lg p-2 font-arabic">
                    سُجّل أول قياس لكل حساب. يُحسب النمو تلقائياً بعد القياس التالي (كل 6 ساعات ليوتيوب، ويومياً لإكس).
                  </p>
                )}
                {summary.follower_growth.map((g) => (
                  <div key={`${g.platform}-${g.entity_key}`} className="flex items-center justify-between text-xs">
                    <span className="font-bold text-slate-800 font-arabic">{g.name_ar} ({PLATFORM_LABEL[g.platform]})</span>
                    <span className="text-slate-600">
                      {compact.format(g.last)}
                      {g.change === null ? null : (
                        <span className={`mr-2 font-bold ${g.change >= 0 ? 'text-emerald-600' : 'text-rose-600'}`}>
                          {g.change >= 0 ? '+' : ''}{compact.format(g.change)} ({signedPercent.format(g.change_pct ?? 0)})
                        </span>
                      )}
                    </span>
                  </div>
                ))}
              </div>
            </Card>
          </div>

          <Card title="ماذا يقول الجمهور" subtitle="أنواع التعليقات، مع أكثر التعليقات إعجاباً كأمثلة" icon={<MessagesSquare className="w-4 h-4" />}>
            {summary.intents.length === 0 ? (
              <p className="text-xs text-slate-400 font-arabic">لم تُصنّف أي تعليقات بعد.</p>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {summary.intents.map((i) => (
                  <div key={i.intent} className="rounded-xl border border-slate-200/80 bg-slate-50/60 p-4">
                    <div className="flex items-center justify-between mb-3">
                      <span className={`text-[11px] font-bold px-2 py-0.5 rounded-full border font-arabic ${INTENT_STYLE[i.intent]}`}>{i.label_ar}</span>
                      <span className="text-[11px] text-slate-500">
                        {i.count.toLocaleString('en')}{i.share !== null ? ` · ${percent.format(i.share)}` : ''}
                      </span>
                    </div>
                    <ul className="space-y-2">
                      {i.examples.map((e, n) => (
                        <li key={n} className="text-xs text-slate-700 font-arabic leading-relaxed bg-white rounded-lg border border-slate-200/70 p-2.5">
                          «{e.text}»
                          <a href={e.url} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-[10px] text-emerald-700 mt-1 hover:underline">
                            <ExternalLink className="w-3 h-3" />
                            {e.channel_name_ar} · {PLATFORM_LABEL[e.platform]}
                            {e.sentiment ? ` · ${SENTIMENT_LABEL[e.sentiment]}` : ''}
                            {e.like_count ? ` · ${e.like_count} إعجاب` : ''}
                          </a>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            )}
          </Card>

          <AccuracyPanel onNotify={onNotify} />

          <Card title="أكثر المنشورات إثارة للنقاش" subtitle="حسب عدد التعليقات المجمّعة" icon={<MessageCircle className="w-4 h-4" />}>
            <div className="space-y-4">
              {summary.discussed_posts.map((p) => (
                <div key={p.video.video_id} className="flex flex-col md:flex-row md:items-center gap-3 justify-between">
                  <a href={p.video.url} target="_blank" rel="noreferrer" className="text-xs font-bold text-slate-800 font-arabic hover:text-emerald-700 line-clamp-1 md:max-w-[55%]" title={p.video.title}>
                    {p.video.title}
                    <span className="block text-[10px] font-normal text-slate-500">{p.video.channel_name_ar} · {PLATFORM_LABEL[p.video.platform]} · {p.comments} تعليق</span>
                  </a>
                  <div className="md:w-[40%]"><SentimentBar s={p} /></div>
                </div>
              ))}
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
