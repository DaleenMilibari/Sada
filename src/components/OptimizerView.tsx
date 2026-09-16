import { useState, useRef } from 'react';
import {
  Wand2, Clock, Trophy, CheckCircle2,
  Upload, Loader2, Sparkles, Hash, ChevronDown, CalendarCheck,
  Copy, Check, FileText, X
} from 'lucide-react';

interface OptimizerViewProps {
  onNotify?: (title: string, desc?: string, type?: 'success' | 'info') => void;
}

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

const OPTIMIZED_CONTENT = `في لحظةٍ استثنائية تجمع الوطن، البث المباشر ينقل لكم أصدق المشاهد وأدق التفاصيل لحظة بلحظة.

كيف ترون أثر هذا التحول؟ شاركونا آراءكم وشاهدوا التغطية الكاملة الآن مباشرةً.`;

const ORIGINAL_CONTENT = 'بث مباشر للحدث اليوم. تابعونا للوقوف على أبرز المستجدات والتفاصيل على الهواء.';

const ALT_CONTENT = 'تغطية مستمرة ونقل فوري لأبرز المحطات اليوم. البث الرقمي المباشر متاح الآن لجميع الأجهزة بجودة فائقة.';

const HASHTAGS = ['#بث_مباشر', '#حدث_وطني', '#السعودية_اليوم'];

type Platform = 'إكس' | 'إنستغرام' | 'يوتيوب';
const PLATFORMS: Platform[] = ['إكس', 'إنستغرام', 'يوتيوب'];

export default function OptimizerView({ onNotify }: OptimizerViewProps) {
  const [selectedPlatforms, setSelectedPlatforms] = useState<Platform[]>(['إكس', 'إنستغرام']);
  const [content, setContent] = useState(ORIGINAL_CONTENT);
  const [tone, setTone] = useState<'تفاعلي' | 'رسمي' | 'إخباري'>('تفاعلي');
  const [isLoading, setIsLoading] = useState(false);
  const [loadingStep, setLoadingStep] = useState(0);
  const [hasResults, setHasResults] = useState(true);
  const [isDragging, setIsDragging] = useState(false);
  const [uploadedFile, setUploadedFile] = useState<{ name: string; size: string } | null>({
    name: 'مقتطف_البث_01.mp4',
    size: '14.2 MB',
  });
  const [copiedVariant, setCopiedVariant] = useState<string | null>(null);
  const [isScheduleModalOpen, setIsScheduleModalOpen] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const togglePlatform = (p: Platform) => {
    setSelectedPlatforms((prev) =>
      prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p]
    );
  };

  const handleOptimize = async () => {
    setIsLoading(true);
    setLoadingStep(1);
    await new Promise((r) => setTimeout(r, 600));
    setLoadingStep(2);
    await new Promise((r) => setTimeout(r, 700));
    setLoadingStep(3);
    await new Promise((r) => setTimeout(r, 500));
    setIsLoading(false);
    setHasResults(true);
    onNotify?.('اكتمل توليد المتغيرات', 'تم تحديد النسخة الفائزة', 'success');
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) {
      setUploadedFile({
        name: file.name,
        size: (file.size / (1024 * 1024)).toFixed(1) + ' MB',
      });
      onNotify?.('تم إرفاق الملف', file.name, 'info');
    }
  };

  const handleCopy = (key: string, text: string) => {
    navigator.clipboard?.writeText(text);
    setCopiedVariant(key);
    onNotify?.('تم نسخ النص إلى الحافظة', '', 'success');
    setTimeout(() => setCopiedVariant(null), 2000);
  };

  const confirmPublish = () => {
    setIsScheduleModalOpen(false);
    onNotify?.(
      'تم اعتماد وجدولة النشر الفوري',
      'الموعد المحدد: 8:00 مساءً',
      'success'
    );
  };

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
            <div className="grid grid-cols-3 gap-2">
              {PLATFORMS.map((p) => {
                const isSelected = selectedPlatforms.includes(p);
                return (
                  <button
                    key={p}
                    onClick={() => togglePlatform(p)}
                    className={`py-2 px-3 rounded-xl text-xs font-bold border transition-all cursor-pointer font-arabic flex items-center justify-center gap-1.5 ${
                      isSelected
                        ? 'bg-emerald-700 text-white border-emerald-700 shadow-xs'
                        : 'bg-slate-50 text-slate-600 border-slate-200 hover:bg-white'
                    }`}
                  >
                    {isSelected && <Check className="w-3.5 h-3.5" />}
                    <span>{p}</span>
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
                {(['تفاعلي', 'رسمي', 'إخباري'] as const).map((t) => (
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

            <div>
              <label className="block text-xs font-bold text-slate-500 font-arabic mb-2">
                نوع المحتوى
              </label>
              <div className="relative">
                <select className="w-full text-right text-xs font-bold text-slate-700 bg-slate-50 border border-slate-200 rounded-xl px-4 py-2.5 font-arabic appearance-none outline-none focus:border-emerald-500 cursor-pointer">
                  <option>محتوى بث مباشر</option>
                  <option>لقطة فيروسية</option>
                  <option>تغطية حدث وطني</option>
                  <option>حوار استوديو</option>
                </select>
                <ChevronDown className="absolute left-3 top-3 w-4 h-4 text-slate-400 pointer-events-none" />
              </div>
            </div>
          </div>

          {/* Raw Content Text Area */}
          <div className="bg-white border border-slate-200/90 rounded-2xl p-5 shadow-xs">
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs font-bold text-slate-500 font-arabic">
                الوصف الأولي للمحتوى
              </label>
              <span className="text-[11px] text-slate-400">
                {content.length} / 280
              </span>
            </div>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="اكتب فكرة المنشور الأولية..."
              rows={4}
              className="w-full text-right text-sm text-slate-800 placeholder:text-slate-300 bg-slate-50 border border-slate-200 rounded-xl p-3 font-arabic outline-none resize-none focus:border-emerald-500 transition-all leading-relaxed"
            />
          </div>

          {/* File Upload Zone */}
          <div
            className={`bg-white border-2 border-dashed rounded-2xl p-4 text-center cursor-pointer transition-all duration-200 ${
              isDragging
                ? 'border-emerald-500 bg-emerald-50/50'
                : 'border-slate-200 hover:border-emerald-300'
            }`}
            onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
          >
            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              accept="image/*,video/*"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) {
                  setUploadedFile({
                    name: f.name,
                    size: (f.size / (1024 * 1024)).toFixed(1) + ' MB',
                  });
                  onNotify?.('تم إرفاق الملف', f.name, 'info');
                }
              }}
            />

            {uploadedFile ? (
              <div className="flex items-center justify-between p-2 bg-emerald-50 border border-emerald-200 rounded-xl">
                <div className="flex items-center gap-2 text-right">
                  <FileText className="w-4 h-4 text-emerald-700" />
                  <div>
                    <p className="text-xs font-bold text-slate-800 font-arabic truncate max-w-[140px]">
                      {uploadedFile.name}
                    </p>
                    <p className="text-[10px] text-slate-400">{uploadedFile.size}</p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    setUploadedFile(null);
                  }}
                  className="p-1 text-slate-400 hover:text-red-500"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            ) : (
              <div className="py-2">
                <Upload className="w-5 h-5 text-slate-400 mx-auto mb-1" />
                <p className="text-xs font-bold text-slate-600 font-arabic">
                  اسحب الفيديو أو الصورة هنا
                </p>
                <p className="text-[10px] text-slate-400 font-arabic">
                  MP4, MOV, PNG حتى 50 ميغابايت
                </p>
              </div>
            )}
          </div>

          {/* CTA Button */}
          <button
            onClick={handleOptimize}
            disabled={isLoading || !content.trim()}
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
                {[
                  { step: 1, text: 'استخراج الأنماط المفتاحية' },
                  { step: 2, text: 'صياغة النسخ وحساب نسبة التفاعل' },
                  { step: 3, text: 'توليد الوسوم وتحديد التوقيت الأمثل' },
                ].map((item) => (
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

          {!isLoading && hasResults && (
            <div className="space-y-4 animate-slide-up">
              {/* Timing Capsule Widget */}
              <div className="bg-blue-50/60 border border-blue-200/70 rounded-2xl p-4 shadow-xs flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="p-2.5 bg-blue-100 text-blue-700 rounded-xl">
                    <Clock className="w-5 h-5" />
                  </div>
                  <div>
                    <p className="text-xs text-slate-500 font-arabic">
                      التوقيت المقترح للنشر
                    </p>
                    <p className="text-sm font-black text-slate-900 font-arabic mt-0.5">
                      اليوم الساعة <span className="text-emerald-700">8:00 مساءً</span>
                    </p>
                  </div>
                </div>

                <span className="text-xs font-semibold text-blue-700 bg-blue-100 px-2.5 py-1 rounded-full font-arabic">
                  ذروة التفاعل
                </span>
              </div>

              {/* 1. Winner Variant Card (Cleaned of duplicates) */}
              <div className="bg-white border-2 border-emerald-600 rounded-2xl p-5 shadow-xs relative overflow-hidden">
                <div className="flex items-center justify-between mb-3">
                  <span className="flex items-center gap-1.5 bg-emerald-600 text-white text-xs font-bold px-3 py-1 rounded-full shadow-2xs font-arabic">
                    <Trophy className="w-3.5 h-3.5" />
                    النسخة الفائزة (+24% تفاعل متوقع)
                  </span>

                  <button
                    onClick={() => handleCopy('winner', OPTIMIZED_CONTENT)}
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

                {/* Content Box */}
                <div className="bg-emerald-50/50 border border-emerald-100 rounded-xl p-4 mb-3">
                  <p className="text-sm text-slate-800 font-arabic leading-relaxed whitespace-pre-line text-right font-medium">
                    {OPTIMIZED_CONTENT}
                  </p>
                </div>

                {/* Hashtags */}
                <div className="flex flex-wrap items-center gap-1.5 justify-end mb-3">
                  {HASHTAGS.map((tag) => (
                    <span
                      key={tag}
                      className="inline-flex items-center gap-1 text-[11px] font-bold text-emerald-800 bg-white border border-emerald-200/80 px-2.5 py-1 rounded-full font-arabic"
                    >
                      <Hash className="w-3 h-3 text-emerald-600" />
                      {tag}
                    </span>
                  ))}
                </div>

                {/* Rationale */}
                <div className="pt-2.5 border-t border-emerald-100 flex items-center gap-1.5 text-xs text-slate-500 font-arabic">
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 flex-shrink-0" />
                  <span>صيغة سؤال تفاعلي + نبرة احتفالية تتطابق مع نمط البث</span>
                </div>
              </div>

              {/* 2. Original Version Card */}
              <div className="bg-white border border-slate-200/90 rounded-2xl p-4 shadow-xs">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-bold text-slate-500 bg-slate-100 px-2.5 py-0.5 rounded-full font-arabic">
                    النسخة الأصلية
                  </span>
                  <button
                    onClick={() => handleCopy('original', ORIGINAL_CONTENT)}
                    className="p-1 text-slate-400 hover:text-slate-700 transition-colors"
                    title="نسخ"
                  >
                    {copiedVariant === 'original' ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />}
                  </button>
                </div>
                <p className="text-xs text-slate-600 font-arabic leading-relaxed bg-slate-50/70 p-3 rounded-xl border border-slate-100 text-right">
                  {ORIGINAL_CONTENT}
                </p>
              </div>

              {/* 3. Alternative Version */}
              <div className="bg-white border border-slate-200/90 rounded-2xl p-4 shadow-xs">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold text-slate-700 font-arabic">
                      النسخة البديلة
                    </span>
                    <span className="text-[11px] font-semibold text-blue-700 bg-blue-50 px-2 py-0.5 rounded font-arabic">
                      +9% تفاعل متوقع
                    </span>
                  </div>
                  <button
                    onClick={() => handleCopy('alt', ALT_CONTENT)}
                    className="p-1 text-slate-400 hover:text-slate-700 transition-colors"
                    title="نسخ"
                  >
                    {copiedVariant === 'alt' ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />}
                  </button>
                </div>
                <p className="text-xs text-slate-600 font-arabic leading-relaxed bg-slate-50/70 p-3 rounded-xl border border-slate-100 text-right">
                  {ALT_CONTENT}
                </p>
              </div>

              {/* Action Footer CTA */}
              <button
                onClick={() => setIsScheduleModalOpen(true)}
                className="w-full flex items-center justify-center gap-2 bg-emerald-700 hover:bg-emerald-800 text-white font-bold text-base py-3.5 rounded-2xl shadow-sm transition-all active:scale-[0.99] cursor-pointer font-arabic"
              >
                <CalendarCheck className="w-5 h-5" />
                <span>اعتماد وجدولة النشر الفوري</span>
              </button>
            </div>
          )}
        </div>
      </div>

      {/* ── Schedule Confirmation Modal ── */}
      {isScheduleModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-xs p-4" dir="rtl">
          <div className="bg-white border border-slate-200 rounded-3xl p-6 max-w-md w-full shadow-xl animate-slide-up text-right">
            <div className="flex items-center justify-between mb-4 pb-3 border-b border-slate-100">
              <div className="flex items-center gap-2 text-emerald-700">
                <CalendarCheck className="w-5 h-5" />
                <h3 className="text-base font-bold font-arabic">تأكيد الجدولة</h3>
              </div>
              <button
                onClick={() => setIsScheduleModalOpen(false)}
                className="p-1 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="bg-slate-50 rounded-2xl p-4 border border-slate-100 space-y-2 mb-5">
              <div className="flex items-center justify-between text-xs font-arabic">
                <span className="text-slate-400">النسخة:</span>
                <span className="font-bold text-emerald-700">النسخة المحسّنة (الفائزة)</span>
              </div>
              <div className="flex items-center justify-between text-xs font-arabic">
                <span className="text-slate-400">القنوات:</span>
                <span className="font-bold text-slate-800">
                  {selectedPlatforms.join(' · ')}
                </span>
              </div>
              <div className="flex items-center justify-between text-xs font-arabic">
                <span className="text-slate-400">الموعد:</span>
                <span className="font-bold text-slate-800">اليوم الساعة 8:00 مساءً</span>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={confirmPublish}
                className="flex-1 py-2.5 bg-emerald-700 hover:bg-emerald-800 text-white text-sm font-bold rounded-xl font-arabic cursor-pointer"
              >
                تأكيد
              </button>
              <button
                onClick={() => setIsScheduleModalOpen(false)}
                className="py-2.5 px-4 bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm font-bold rounded-xl font-arabic cursor-pointer"
              >
                إلغاء
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
