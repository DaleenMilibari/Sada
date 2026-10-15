import { useState, useEffect, useRef } from 'react';
import {
  Wand2, Clock, Trophy, CheckCircle2,
  Loader2, Sparkles, ChevronDown, Copy, Check, AlertTriangle, Radio
} from 'lucide-react';
import { ApiError, apiFetch, describeError } from '../lib/api';

interface OptimizerViewProps {
  onNotify?: (title: string, desc?: string, type?: 'success' | 'info') => void;
}

// Mirrors backend/schemas.py::OptimizationResult.
interface RankedAlternative {
  variant: string;
  platform: string;
  time_window: string;
  predicted_engagement: number;
  evidence: string[];
}

interface OptimizerEvidence {
  pattern_id: string;
  pattern: string;
  note: string | null;
}

interface OptimizationResult {
  recommended_variant: string;
  predicted_engagement: number;
  recommended_platform: string;
  recommended_time: string;
  ranked_alternatives: RankedAlternative[];
  evidence: OptimizerEvidence[];
  low_confidence: boolean;
}

// Scores are relative to the optimizer's BASELINE_SCORE (content_optimizer_agent.py).
const BASELINE_SCORE = 100;

const TEMPLATES = [
  {
    title: 'تغطية بث مباشر',
    text: 'بث مباشر للحدث اليوم. تابعونا للوقوف على أبرز المستجدات والتفاصيل على الهواء.',
  },
  {
    title: 'لقطة حوارية',
    text: 'الضيف يتحدث في اللقاء عن مستقبل المشاريع الوطنية والتمكين الشامل لكافة فئات المجتمع.',
  },
  {
    title: 'إعلان موجز',
    text: 'ترقبوا بعد قليل التغطية الشاملة والمباشرة عبر كافة المنصات الرقمية.',
  },
];

// Values must match the platform / content_type / topic keys in backend/data/engagement_records.json.
const PLATFORMS = [
  { id: 'x', label: 'إكس' },
  { id: 'instagram', label: 'إنستغرام' },
  { id: 'youtube', label: 'يوتيوب' },
  { id: 'snapchat', label: 'سناب شات' },
] as const;
type PlatformId = (typeof PLATFORMS)[number]['id'];

const PLATFORM_LABELS: Record<string, string> = Object.fromEntries(PLATFORMS.map((p) => [p.id, p.label]));

const CONTENT_TYPES = [
  { id: 'video', label: 'فيديو' },
  { id: 'image', label: 'صورة' },
  { id: 'text', label: 'نص' },
];

const TOPICS = [
  { id: 'national_event', label: 'حدث وطني' },
  { id: 'housing_support', label: 'الدعم السكني' },
  { id: 'economy', label: 'اقتصاد' },
  { id: 'sports', label: 'رياضة' },
  { id: 'science', label: 'علوم' },
  { id: 'general', label: 'عام' },
];

const TONES = ['تفاعلي', 'رسمي', 'إخباري'] as const;

const LOADING_STEPS = [
  { step: 1, text: 'استخراج الأنماط المفتاحية' },
  { step: 2, text: 'توليد المتغيرات عبر نموذج الذكاء الاصطناعي' },
  { step: 3, text: 'حساب التفاعل المتوقع وتحديد التوقيت الأمثل' },
];

function formatLift(score: number): string {
  const lift = Math.round(score - BASELINE_SCORE);
  return `${lift >= 0 ? '+' : ''}${lift}%`;
}

export default function OptimizerView({ onNotify }: OptimizerViewProps) {
  const [selectedPlatforms, setSelectedPlatforms] = useState<PlatformId[]>(['x', 'instagram']);
  const [content, setContent] = useState(TEMPLATES[0].text);
  const [tone, setTone] = useState<(typeof TONES)[number]>('تفاعلي');
  const [contentType, setContentType] = useState('video');
  const [topic, setTopic] = useState('national_event');
  const [isLoading, setIsLoading] = useState(false);
  const [loadingStep, setLoadingStep] = useState(0);
  const [result, setResult] = useState<OptimizationResult | null>(null);
  const [submittedText, setSubmittedText] = useState('');
  const [copiedVariant, setCopiedVariant] = useState<string | null>(null);
  const stepTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => () => {
    if (stepTimer.current) clearInterval(stepTimer.current);
  }, []);

  const togglePlatform = (p: PlatformId) => {
    setSelectedPlatforms((prev) =>
      prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p]
    );
  };

  const handleOptimize = async () => {
    if (isLoading || !content.trim() || selectedPlatforms.length === 0) return;
    setIsLoading(true);
    setLoadingStep(1);
    // Steps advance while the request is in flight; the last one completes when the response lands.
    stepTimer.current = setInterval(() => setLoadingStep((s) => Math.min(s + 1, LOADING_STEPS.length)), 1500);

    try {
      const res = await apiFetch<OptimizationResult>('/api/optimize', {
        method: 'POST',
        body: JSON.stringify({
          content_type: contentType,
          topic,
          platform_options: selectedPlatforms,
          original_text: content.trim(),
          tone,
        }),
      });
      setResult(res);
      setSubmittedText(content.trim());
      onNotify?.(
        'اكتمل توليد المتغيرات',
        `النسخة الفائزة على ${PLATFORM_LABELS[res.recommended_platform] ?? res.recommended_platform} (${formatLift(res.predicted_engagement)} تفاعل متوقع)`,
        'success'
      );
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 401)) {
        const { title, desc } = describeError(err);
        onNotify?.(title, desc, 'info');
      }
    } finally {
      if (stepTimer.current) clearInterval(stepTimer.current);
      setIsLoading(false);
      setLoadingStep(0);
    }
  };

  const handleCopy = (key: string, text: string) => {
    navigator.clipboard?.writeText(text);
    setCopiedVariant(key);
    onNotify?.('تم نسخ النص إلى الحافظة', '', 'info');
    setTimeout(() => setCopiedVariant(null), 2000);
  };

  // ranked_alternatives covers every variant × platform × time combo - show each
  // distinct variant other than the winner once, at its best-scoring combo.
  const alternatives = result
    ? result.ranked_alternatives.filter(
        (alt, i, all) =>
          alt.variant !== result.recommended_variant &&
          all.findIndex((a) => a.variant === alt.variant) === i
      )
    : [];

  return (
    <div className="animate-fade-in">
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* ── Input Panel (Right, 2 cols) ── */}
        <div className="lg:col-span-2 space-y-4">
          {/* Quick Presets */}
          <div className="bg-white border border-slate-200/90 rounded-2xl p-5 shadow-xs">
            <label className="block text-xs font-bold text-slate-500 font-arabic mb-2.5">
              قوالب صياغة جاهزة
            </label>
            <div className="flex flex-wrap gap-2">
              {TEMPLATES.map((tmpl) => (
                <button
                  key={tmpl.title}
                  onClick={() => {
                    setContent(tmpl.text);
                    onNotify?.('تم تحميل القالب', tmpl.title, 'info');
                  }}
                  className="px-3 py-1.5 bg-slate-50 hover:bg-emerald-50 text-slate-700 hover:text-emerald-800 border border-slate-200 hover:border-emerald-300 rounded-xl text-xs font-bold font-arabic transition-all cursor-pointer"
                >
                  {tmpl.title}
                </button>
              ))}
            </div>
          </div>

          {/* Platform Selector */}
          <div className="bg-white border border-slate-200/90 rounded-2xl p-5 shadow-xs">
            <label className="block text-xs font-bold text-slate-500 font-arabic mb-2.5">
              المنصات المستهدفة
            </label>
            <div className="grid grid-cols-2 gap-2">
              {PLATFORMS.map((p) => {
                const isSelected = selectedPlatforms.includes(p.id);
                return (
                  <button
                    key={p.id}
                    onClick={() => togglePlatform(p.id)}
                    className={`py-2 px-3 rounded-xl text-xs font-bold border transition-all cursor-pointer font-arabic flex items-center justify-center gap-1.5 ${
                      isSelected
                        ? 'bg-emerald-700 text-white border-emerald-700 shadow-xs'
                        : 'bg-slate-50 text-slate-600 border-slate-200 hover:bg-white'
                    }`}
                  >
                    {isSelected && <Check className="w-3.5 h-3.5" />}
                    <span>{p.label}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Tone & Classification */}
          <div className="bg-white border border-slate-200/90 rounded-2xl p-5 shadow-xs space-y-4">
            <div>
              <label className="block text-xs font-bold text-slate-500 font-arabic mb-2">
                نبرة الصياغة
              </label>
              <div className="grid grid-cols-3 gap-2">
                {TONES.map((t) => (
                  <button
                    key={t}
                    onClick={() => setTone(t)}
                    className={`py-1.5 px-3 rounded-xl text-xs font-bold border transition-all cursor-pointer font-arabic ${
                      tone === t
                        ? 'bg-slate-900 text-white border-slate-900'
                        : 'bg-slate-50 text-slate-600 border-slate-200 hover:bg-slate-100'
                    }`}
                  >
                    {t}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label htmlFor="content-type" className="block text-xs font-bold text-slate-500 font-arabic mb-2">
                  نوع المحتوى
                </label>
                <div className="relative">
                  <select
                    id="content-type"
                    value={contentType}
                    onChange={(e) => setContentType(e.target.value)}
                    className="w-full text-right text-xs font-bold text-slate-700 bg-slate-50 border border-slate-200 rounded-xl px-4 py-2.5 font-arabic appearance-none outline-none focus:border-emerald-500 cursor-pointer"
                  >
                    {CONTENT_TYPES.map((c) => (
                      <option key={c.id} value={c.id}>{c.label}</option>
                    ))}
                  </select>
                  <ChevronDown className="absolute left-3 top-3 w-4 h-4 text-slate-400 pointer-events-none" />
                </div>
              </div>

              <div>
                <label htmlFor="topic" className="block text-xs font-bold text-slate-500 font-arabic mb-2">
                  الموضوع
                </label>
                <div className="relative">
                  <select
                    id="topic"
                    value={topic}
                    onChange={(e) => setTopic(e.target.value)}
                    className="w-full text-right text-xs font-bold text-slate-700 bg-slate-50 border border-slate-200 rounded-xl px-4 py-2.5 font-arabic appearance-none outline-none focus:border-emerald-500 cursor-pointer"
                  >
                    {TOPICS.map((t) => (
                      <option key={t.id} value={t.id}>{t.label}</option>
                    ))}
                  </select>
                  <ChevronDown className="absolute left-3 top-3 w-4 h-4 text-slate-400 pointer-events-none" />
                </div>
              </div>
            </div>
          </div>

          {/* Raw Content Text Area */}
          <div className="bg-white border border-slate-200/90 rounded-2xl p-5 shadow-xs">
            <div className="flex items-center justify-between mb-2">
              <label htmlFor="draft" className="text-xs font-bold text-slate-500 font-arabic">
                الوصف الأولي للمحتوى
              </label>
              <span className={`text-[11px] ${content.length > 280 ? 'text-amber-600 font-bold' : 'text-slate-400'}`}>
                {content.length} / 280
              </span>
            </div>
            <textarea
              id="draft"
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="اكتب فكرة المنشور الأولية..."
              rows={4}
              maxLength={2000}
              className="w-full text-right text-sm text-slate-800 placeholder:text-slate-300 bg-slate-50 border border-slate-200 rounded-xl p-3 font-arabic outline-none resize-none focus:border-emerald-500 transition-all leading-relaxed"
            />
          </div>

          {/* CTA Button */}
          <button
            onClick={handleOptimize}
            disabled={isLoading || !content.trim() || selectedPlatforms.length === 0}
            className="w-full flex items-center justify-center gap-2 bg-emerald-700 hover:bg-emerald-800 disabled:bg-slate-300 text-white font-bold text-base py-3.5 rounded-2xl shadow-sm transition-all active:scale-[0.99] cursor-pointer disabled:cursor-not-allowed font-arabic"
          >
            {isLoading ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                <span>جارٍ المعالجة...</span>
              </>
            ) : (
              <>
                <Wand2 className="w-5 h-5" />
                <span>تحسين واختبار المتغيرات</span>
              </>
            )}
          </button>
          {selectedPlatforms.length === 0 && (
            <p className="text-[11px] text-amber-600 font-arabic text-center">اختر منصة واحدة على الأقل</p>
          )}
        </div>

        {/* ── Results Panel (Left, 3 cols) ── */}
        <div className="lg:col-span-3 space-y-4">
          {isLoading && (
            <div className="min-h-[440px] flex flex-col items-center justify-center bg-white border border-slate-200/90 rounded-2xl p-8 shadow-xs text-center animate-fade-in">
              <div className="relative mb-6">
                <div className="w-16 h-16 rounded-full border-4 border-slate-100" />
                <div className="absolute inset-0 w-16 h-16 rounded-full border-4 border-emerald-600 border-t-transparent animate-spin" />
                <div className="absolute inset-0 flex items-center justify-center">
                  <Sparkles className="w-6 h-6 text-emerald-600" />
                </div>
              </div>

              <h3 className="text-base font-bold text-slate-900 font-arabic mb-1">
                جارٍ تحليل وتوليد المتغيرات
              </h3>
              <p className="text-xs text-slate-400 font-arabic mb-6">
                مطابقة الصياغة مع أنماط التفاعل الرقمي
              </p>

              <div className="w-full max-w-sm space-y-2 text-right">
                {LOADING_STEPS.map((item) => (
                  <div
                    key={item.step}
                    className={`flex items-center justify-between p-2.5 rounded-xl border text-xs font-arabic ${
                      loadingStep >= item.step
                        ? 'bg-emerald-50 border-emerald-200 text-emerald-900 font-bold'
                        : 'bg-slate-50 border-slate-200 text-slate-400'
                    }`}
                  >
                    <span>{item.text}</span>
                    {loadingStep > item.step ? (
                      <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                    ) : loadingStep === item.step ? (
                      <Loader2 className="w-4 h-4 text-emerald-600 animate-spin" />
                    ) : (
                      <span className="w-3.5 h-3.5 rounded-full border border-slate-300" />
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {!isLoading && !result && (
            <div className="min-h-[440px] flex flex-col items-center justify-center bg-white border border-dashed border-slate-200 rounded-2xl p-8 text-center">
              <Wand2 className="w-8 h-8 text-slate-300 mb-3" />
              <h3 className="text-sm font-bold text-slate-700 font-arabic mb-1">لا توجد نتائج بعد</h3>
              <p className="text-xs text-slate-400 font-arabic max-w-xs">
                اكتب وصف المنشور واختر المنصات، ثم اضغط «تحسين واختبار المتغيرات» لتوليد النسخ ومقارنتها.
              </p>
            </div>
          )}

          {!isLoading && result && (
            <div className="space-y-4 animate-slide-up">
              {/* Timing Capsule Widget */}
              <div className="bg-blue-50/60 border border-blue-200/70 rounded-2xl p-4 shadow-xs flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="p-2.5 bg-blue-100 text-blue-700 rounded-xl">
                    <Clock className="w-5 h-5" />
                  </div>
                  <div>
                    <p className="text-xs text-slate-500 font-arabic">
                      التوقيت والمنصة المقترحان للنشر
                    </p>
                    <p className="text-sm font-black text-slate-900 font-arabic mt-0.5">
                      <span className="text-emerald-700">{result.recommended_time}</span>
                    </p>
                  </div>
                </div>

                <span className="flex items-center gap-1 text-xs font-semibold text-blue-700 bg-blue-100 px-2.5 py-1 rounded-full font-arabic">
                  <Radio className="w-3 h-3" />
                  {PLATFORM_LABELS[result.recommended_platform] ?? result.recommended_platform}
                </span>
              </div>

              {result.low_confidence && (
                <div className="flex items-start gap-2 bg-amber-50 border border-amber-200 rounded-2xl p-3 text-xs text-amber-800 font-arabic">
                  <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                  <span>
                    ثقة منخفضة: لا يوجد نمط تفاعل مطابق مباشرةً لهذا النوع والموضوع، والتوصية مبنية على أقوى نمط عام متاح.
                  </span>
                </div>
              )}

              {/* 1. Winner Variant Card */}
              <div className="bg-white border-2 border-emerald-600 rounded-2xl p-5 shadow-xs relative overflow-hidden">
                <div className="flex items-center justify-between mb-3">
                  <span className="flex items-center gap-1.5 bg-emerald-600 text-white text-xs font-bold px-3 py-1 rounded-full shadow-2xs font-arabic">
                    <Trophy className="w-3.5 h-3.5" />
                    النسخة الفائزة ({formatLift(result.predicted_engagement)} تفاعل متوقع)
                  </span>

                  <button
                    onClick={() => handleCopy('winner', result.recommended_variant)}
                    className="flex items-center gap-1 text-xs font-bold text-emerald-700 hover:text-emerald-900 bg-emerald-50 hover:bg-emerald-100 border border-emerald-200 px-2.5 py-1 rounded-lg transition-colors cursor-pointer font-arabic"
                  >
                    {copiedVariant === 'winner' ? (
                      <>
                        <Check className="w-3.5 h-3.5" />
                        <span>تم النسخ</span>
                      </>
                    ) : (
                      <>
                        <Copy className="w-3.5 h-3.5" />
                        <span>نسخ</span>
                      </>
                    )}
                  </button>
                </div>

                <div className="bg-emerald-50/50 border border-emerald-100 rounded-xl p-4 mb-3">
                  <p className="text-sm text-slate-800 font-arabic leading-relaxed whitespace-pre-line text-right font-medium">
                    {result.recommended_variant}
                  </p>
                </div>

                {/* Rationale - evidence from the pattern store */}
                <div className="pt-2.5 border-t border-emerald-100 space-y-1.5">
                  {result.evidence.map((ev) => (
                    <div key={ev.pattern_id + ev.pattern} className="flex items-start gap-1.5 text-xs text-slate-500 font-arabic">
                      <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 flex-shrink-0 mt-0.5" />
                      <span>{ev.pattern}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* 2. Original Version Card */}
              <div className="bg-white border border-slate-200/90 rounded-2xl p-4 shadow-xs">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-bold text-slate-500 bg-slate-100 px-2.5 py-0.5 rounded-full font-arabic">
                    النسخة الأصلية
                  </span>
                  <button
                    onClick={() => handleCopy('original', submittedText)}
                    className="p-1 text-slate-400 hover:text-slate-700 transition-colors"
                    title="نسخ"
                  >
                    {copiedVariant === 'original' ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />}
                  </button>
                </div>
                <p className="text-xs text-slate-600 font-arabic leading-relaxed bg-slate-50/70 p-3 rounded-xl border border-slate-100 text-right">
                  {submittedText}
                </p>
              </div>

              {/* 3. Alternative Versions */}
              {alternatives.map((alt, i) => (
                <div key={alt.variant} className="bg-white border border-slate-200/90 rounded-2xl p-4 shadow-xs">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-xs font-bold text-slate-700 font-arabic">
                        نسخة بديلة {i + 1}
                      </span>
                      <span className="text-[11px] font-semibold text-blue-700 bg-blue-50 px-2 py-0.5 rounded font-arabic">
                        {formatLift(alt.predicted_engagement)} تفاعل متوقع
                      </span>
                      <span className="text-[11px] text-slate-400 font-arabic">
                        {PLATFORM_LABELS[alt.platform] ?? alt.platform} · {alt.time_window}
                      </span>
                    </div>
                    <button
                      onClick={() => handleCopy(`alt-${i}`, alt.variant)}
                      className="p-1 text-slate-400 hover:text-slate-700 transition-colors"
                      title="نسخ"
                    >
                      {copiedVariant === `alt-${i}` ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />}
                    </button>
                  </div>
                  <p className="text-xs text-slate-600 font-arabic leading-relaxed bg-slate-50/70 p-3 rounded-xl border border-slate-100 text-right">
                    {alt.variant}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
