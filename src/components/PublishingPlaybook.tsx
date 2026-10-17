import { useEffect, useState } from 'react';
import { CalendarClock, ChevronLeft, Compass, Layers, Loader2, Megaphone, ShieldCheck, Wand2 } from 'lucide-react';
import { apiFetch, describeError } from '../lib/api';
import type { OptimizerDraft, Platform, Playbook, PlaybookOption } from '../types';

const PLATFORM_LABEL: Record<Platform, string> = { youtube: 'يوتيوب', instagram: 'إنستغرام', x: 'إكس' };
const PLATFORM_DOT: Record<Platform, string> = { youtube: 'bg-red-500', instagram: 'bg-pink-600', x: 'bg-slate-900' };
const CONFIDENCE = {
  high: { label: 'ثقة عالية', cls: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  medium: { label: 'ثقة متوسطة', cls: 'bg-amber-50 text-amber-700 border-amber-200' },
  low: { label: 'ثقة منخفضة - عينة صغيرة', cls: 'bg-rose-50 text-rose-700 border-rose-200' },
} as const;
const compact = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 });

function Tile({ icon, label, value, sub }: { icon: React.ReactNode; label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl bg-white border border-slate-200/80 p-4">
      <div className="flex items-center gap-1.5 text-slate-400 mb-1.5">
        {icon}
        <span className="text-[11px] font-arabic">{label}</span>
      </div>
      <p className="text-base font-black text-slate-900 font-arabic leading-snug">{value}</p>
      {sub && <p className="text-[11px] text-slate-500 font-arabic mt-1">{sub}</p>}
    </div>
  );
}

function usualPhrase(ratio: number): string {
  if (ratio >= 1.95) return `${ratio.toFixed(1)} ضعف المعتاد`;
  const pct = Math.round(Math.abs(ratio - 1) * 100);
  if (pct < 5) return 'مثل المعتاد';
  return ratio > 1 ? `أعلى من المعتاد بـ ${pct}%` : `أقل من المعتاد بـ ${pct}%`;
}

function Decision({ option, topicId, topicLabel, onCreateDraft }: {
  option: PlaybookOption;
  topicId: string;
  topicLabel: string;
  onCreateDraft?: (draft: OptimizerDraft) => void;
}) {
  const conf = CONFIDENCE[option.confidence];
  return (
    <div className="rounded-2xl border-2 border-emerald-600 bg-gradient-to-l from-emerald-50/70 to-white p-5">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
        <p className="text-sm font-bold text-emerald-900 font-arabic">قرار النشر لموضوع «{topicLabel}»</p>
        <span className={`flex items-center gap-1 text-[11px] font-bold px-2 py-0.5 rounded-full border font-arabic ${conf.cls}`}>
          <ShieldCheck className="w-3.5 h-3.5" /> {conf.label} · {option.topic_posts} منشوراً
        </span>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Tile icon={<Compass className="w-3.5 h-3.5" />} label="أين: المنصة" value={PLATFORM_LABEL[option.platform]} />
        <Tile icon={<Megaphone className="w-3.5 h-3.5" />} label="بأي حساب" value={option.name_ar} />
        <Tile
          icon={<Layers className="w-3.5 h-3.5" />}
          label="ماذا: نوع المحتوى"
          value={option.content_type?.label_ar ?? '—'}
          sub={option.content_type ? usualPhrase(option.content_type.multiplier) : 'بيانات غير كافية'}
        />
        <Tile
          icon={<CalendarClock className="w-3.5 h-3.5" />}
          label="متى: الوقت المقترح"
          value={option.best_time?.label_ar ?? '—'}
          sub={option.best_time ? `${usualPhrase(option.best_time.multiplier)} · بتوقيت الرياض` : 'بيانات غير كافية'}
        />
      </div>

      <p className="text-[13px] text-slate-700 font-arabic mt-4">
        الوصول المتوقع: نحو <strong>{compact.format(option.expected_reach)} {option.reach_unit_ar}</strong> للمنشور
        {option.relative_reach !== null && (
          <> · <strong>{option.relative_reach.toFixed(1)} ضعف</strong> ما يحققه حساب الهيئة المعتاد على {PLATFORM_LABEL[option.platform]}</>
        )}
      </p>

      <div className="mt-3 rounded-xl bg-white/70 border border-slate-200/70 p-3">
        <p className="text-[11px] font-bold text-slate-500 font-arabic mb-1.5">لماذا هذا القرار؟</p>
        <ul className="space-y-1">
          {option.reasons.map((r, i) => (
            <li key={i} className="flex gap-2 text-xs text-slate-700 font-arabic leading-relaxed">
              <span className="mt-1.5 w-1 h-1 rounded-full bg-emerald-600 shrink-0" />
              {r}
            </li>
          ))}
        </ul>
      </div>

      {onCreateDraft && (
        <button
          onClick={() => onCreateDraft({
            text: '',
            topic: topicId,
            entityKey: option.entity_key,
            contentType: option.content_type?.content_type,
            source: `خطة النشر: ${option.name_ar} على ${PLATFORM_LABEL[option.platform]}${option.best_time ? `، ${option.best_time.label_ar}` : ''}`,
          })}
          className="mt-4 flex items-center gap-1.5 px-4 py-2 rounded-xl bg-emerald-700 text-white text-xs font-bold font-arabic hover:bg-emerald-800 cursor-pointer"
        >
          <Wand2 className="w-4 h-4" /> اكتب المنشور بهذا القرار
        </button>
      )}
    </div>
  );
}

export default function PublishingPlaybook({ onCreateDraft, onNotify }: {
  onCreateDraft?: (draft: OptimizerDraft) => void;
  onNotify?: (title: string, desc?: string, type?: 'success' | 'info') => void;
}) {
  const [playbook, setPlaybook] = useState<Playbook | null>(null);
  const [topic, setTopic] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<Playbook>('/api/playbook?days=60')
      .then((p) => {
        setPlaybook(p);
        setTopic((t) => t ?? p.topics.find((x) => x.best)?.topic ?? null);
      })
      .catch((err) => onNotify?.('تعذر تحميل خطة النشر', describeError(err).desc, 'info'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const current = playbook?.topics.find((t) => t.topic === topic) ?? null;
  const others = current?.by_platform.filter((o) => o !== current.best && o.platform !== current.best?.platform) ?? [];

  return (
    <div className="bg-white rounded-2xl border border-slate-200/80 p-6 shadow-2xs">
      <div className="flex items-start gap-3 mb-4">
        <div className="p-2 rounded-xl bg-emerald-50 border border-emerald-100 text-emerald-700"><Compass className="w-5 h-5" /></div>
        <div>
          <h3 className="text-base font-bold text-slate-900 font-arabic">خطة النشر: ماذا أنشر، وأين، ومتى؟</h3>
          <p className="text-xs text-slate-400 font-arabic">
            اختر موضوع المنشور فتحصل على قرار كامل مبني على أداء منشورات الهيئة الحقيقية في آخر {playbook?.days ?? 60} يوماً
          </p>
        </div>
      </div>

      {!playbook && (
        <div className="flex justify-center py-10 text-slate-400"><Loader2 className="w-5 h-5 animate-spin" /></div>
      )}

      {playbook && (
        <>
          <p className="text-[11px] font-bold text-slate-500 font-arabic mb-2">عن ماذا تريد أن تنشر؟</p>
          <div className="flex flex-wrap gap-2 mb-5">
            {playbook.topics.map((t) => (
              <button
                key={t.topic}
                onClick={() => setTopic(t.topic)}
                disabled={!t.best}
                className={`px-3 py-1.5 rounded-xl text-xs font-bold font-arabic border transition-colors ${
                  topic === t.topic
                    ? 'bg-emerald-700 text-white border-emerald-700'
                    : t.best ? 'bg-white text-slate-700 border-slate-200 hover:bg-slate-50 cursor-pointer' : 'bg-slate-50 text-slate-300 border-slate-100 cursor-not-allowed'
                }`}
              >
                {t.label_ar}
              </button>
            ))}
          </div>

          {current?.best && <Decision option={current.best} topicId={current.topic} topicLabel={current.label_ar} onCreateDraft={onCreateDraft} />}

          {current && others.length > 0 && (
            <div className="mt-4">
              <p className="text-[11px] font-bold text-slate-500 font-arabic mb-2">إن أردت النشر على منصة أخرى</p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {others.map((o) => (
                  <div key={`${o.platform}-${o.entity_key}`} className="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
                    <p className="text-xs font-bold text-slate-800 font-arabic flex items-center gap-1.5">
                      <span className={`w-2 h-2 rounded-full ${PLATFORM_DOT[o.platform]}`} />
                      {PLATFORM_LABEL[o.platform]}: {o.name_ar}
                    </p>
                    <p className="text-[11px] text-slate-600 font-arabic mt-1">
                      {o.content_type?.label_ar ?? '—'} · {o.best_time?.label_ar ?? '—'} · نحو {compact.format(o.expected_reach)} {o.reach_unit_ar}
                      {' '}· {CONFIDENCE[o.confidence].label}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}

          <details className="mt-5 group">
            <summary className="text-xs font-bold text-slate-600 font-arabic cursor-pointer hover:text-slate-900 flex items-center gap-1">
              <ChevronLeft className="w-3.5 h-3.5 group-open:-rotate-90 transition-transform" /> الخطة الكاملة لكل المواضيع
            </summary>
            <div className="overflow-x-auto mt-3">
              <table className="w-full text-xs font-arabic">
                <thead>
                  <tr className="text-slate-400 border-b border-slate-100">
                    <th className="text-right font-normal py-2">الموضوع</th>
                    <th className="text-right font-normal">أين (الحساب)</th>
                    <th className="text-right font-normal">ماذا</th>
                    <th className="text-right font-normal">متى</th>
                    <th className="text-right font-normal">الوصول المتوقع</th>
                    <th className="text-right font-normal">الثقة</th>
                  </tr>
                </thead>
                <tbody>
                  {playbook.topics.map((t) => (
                    <tr
                      key={t.topic}
                      onClick={() => t.best && setTopic(t.topic)}
                      className={`border-b border-slate-50 ${t.best ? 'cursor-pointer hover:bg-emerald-50/50' : ''} ${topic === t.topic ? 'bg-emerald-50/70' : ''}`}
                    >
                      <td className="py-2 font-bold text-slate-800">{t.label_ar}</td>
                      {t.best ? (
                        <>
                          <td className="text-slate-700">{t.best.name_ar} · {PLATFORM_LABEL[t.best.platform]}</td>
                          <td className="text-slate-700">{t.best.content_type?.label_ar ?? '—'}</td>
                          <td className="text-slate-700">{t.best.best_time?.label_ar ?? '—'}</td>
                          <td className="text-slate-700">{compact.format(t.best.expected_reach)} {t.best.reach_unit_ar}</td>
                          <td><span className={`px-1.5 py-0.5 rounded-full border text-[10px] ${CONFIDENCE[t.best.confidence].cls}`}>{CONFIDENCE[t.best.confidence].label.split(' - ')[0]}</span></td>
                        </>
                      ) : (
                        <td colSpan={5} className="text-slate-400">منشورات قليلة في هذا الموضوع - لا يمكن التوصية بعد</td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-[10px] text-slate-400 font-arabic mt-2 leading-relaxed">
              الترتيب حسب الوصول النسبي (الوصول المتوقع مقسوماً على وصول حساب الهيئة المعتاد على نفس المنصة)، لأن المشاهدة على يوتيوب ومرة الظهور على إكس
              ليستا نفس الوحدة. أثر الموضوع المقيس على عدد قليل من المنشورات يُقرَّب إحصائياً نحو المعتاد حتى لا تتصدر نتيجة صدفة.
            </p>
          </details>
        </>
      )}
    </div>
  );
}
