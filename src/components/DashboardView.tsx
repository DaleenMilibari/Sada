import { useState, useEffect } from 'react';
import {
  TrendingUp, Clock, Zap, Users, BookOpen, BarChart2,
  Copy, Check, RefreshCw, Sparkles, Video, Award, Radio, Globe, ShieldCheck
} from 'lucide-react';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer
} from 'recharts';

interface DashboardViewProps {
  onNotify?: (title: string, desc?: string, type?: 'success' | 'info') => void;
}

const API_BASE = 'http://localhost:8000';

// Mirrors backend/schemas.py::Pattern.
interface ApiPattern {
  pattern_id: string;
  pattern: string;
  supporting_metric: string;
  confidence: number;
  affected_content_types: string[];
  dimension: 'content_type' | 'timing' | 'topic_platform' | 'platform_reach_real' | 'awj_sada_real';
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
};

const CATEGORY_TABS: { key: 'all' | 'content_type' | 'timing' | 'topic_platform' | 'real'; label: string }[] = [
  { key: 'all', label: 'الكل' },
  { key: 'content_type', label: 'نوع المحتوى' },
  { key: 'timing', label: 'توقيت' },
  { key: 'topic_platform', label: 'الموضوع والمنصة' },
  { key: 'real', label: 'بيانات حقيقية' },
];

const weeklyData = [
  { day: 'الأحد', engagement: 42, reach: 58 },
  { day: 'الاثنين', engagement: 55, reach: 72 },
  { day: 'الثلاثاء', engagement: 38, reach: 49 },
  { day: 'الأربعاء', engagement: 70, reach: 88 },
  { day: 'الخميس', engagement: 61, reach: 79 },
  { day: 'الجمعة', engagement: 85, reach: 96 },
  { day: 'السبت', engagement: 78, reach: 91 },
];

const platforms = [
  { name: 'يوتيوب', share: 38, count: '5.4M تفاعل', color: 'bg-red-500', barColor: '#ef4444' },
  { name: 'منصة إكس', share: 29, count: '4.1M تفاعل', color: 'bg-slate-800', barColor: '#1e293b' },
  { name: 'إنستغرام', share: 22, count: '3.1M تفاعل', color: 'bg-pink-600', barColor: '#db2777' },
  { name: 'سناب شات', share: 11, count: '1.6M تفاعل', color: 'bg-amber-400', barColor: '#f59e0b' },
];

export default function DashboardView({ onNotify }: DashboardViewProps) {
  const [period, setPeriod] = useState<'today' | 'week' | 'month'>('week');
  const [activeCategory, setActiveCategory] = useState<typeof CATEGORY_TABS[number]['key']>('all');
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isLoadingPatterns, setIsLoadingPatterns] = useState(true);
  const [patterns, setPatterns] = useState<ApiPattern[]>([]);
  const [chartMetric, setChartMetric] = useState<'all' | 'engagement' | 'reach'>('all');

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/api/patterns`);
        if (!res.ok) throw new Error('patterns fetch failed');
        setPatterns(await res.json());
      } catch {
        onNotify?.('تعذر تحميل مخزن الأنماط', 'تأكد من تشغيل الخادم الخلفي على المنفذ 8000', 'info');
      } finally {
        setIsLoadingPatterns(false);
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    })();
  }, []);

  const filteredPatterns = patterns.filter((p) => {
    if (activeCategory === 'all') return true;
    if (activeCategory === 'real') return p.source.startsWith('real_');
    return p.dimension === activeCategory;
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
      const res = await fetch(`${API_BASE}/api/patterns/refresh`, { method: 'POST' });
      if (!res.ok) throw new Error('refresh failed');
      const fresh: ApiPattern[] = await res.json();
      setPatterns(fresh);
      onNotify?.('تم تحديث مخزن الأنماط', `${fresh.length} نمط محدّث من بيانات حقيقية ومركّبة`, 'info');
    } catch {
      onNotify?.('تعذر تحديث مخزن الأنماط', 'تأكد من تشغيل الخادم الخلفي على المنفذ 8000', 'info');
    } finally {
      setIsRefreshing(false);
    }
  };

  return (
    <div className="animate-fade-in space-y-6">
      {/* ── Top Metric Cards with Integrated Period Filter ── */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-bold text-slate-700 font-arabic">
            مؤشرات الأداء الرئيسية
          </h3>
          <div className="flex items-center gap-1 bg-white border border-slate-200/80 p-1 rounded-xl shadow-2xs">
            {[
              { id: 'today', label: 'اليوم' },
              { id: 'week', label: 'هذا الأسبوع' },
              { id: 'month', label: 'هذا الشهر' },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setPeriod(tab.id as any)}
                className={`px-3 py-1 rounded-lg text-xs font-bold font-arabic transition-all cursor-pointer ${
                  period === tab.id
                    ? 'bg-slate-900 text-white shadow-2xs'
                    : 'text-slate-600 hover:text-slate-900'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
          {/* Metric 1 */}
          <div className="bg-white border border-slate-200/90 rounded-2xl p-5 shadow-xs hover:shadow-sm transition-all">
            <div className="flex items-start justify-between mb-3">
              <div className="flex items-center gap-1 bg-emerald-50 text-emerald-700 border border-emerald-200/70 px-2.5 py-1 rounded-full text-xs font-bold font-arabic">
                <TrendingUp className="w-3 h-3" />
                <span>+5.4%</span>
              </div>
              <div className="p-2.5 bg-slate-100 rounded-xl text-slate-600">
                <Users className="w-5 h-5" />
              </div>
            </div>
            <div className="flex items-baseline justify-between">
              <p className="text-3xl font-black text-slate-900 font-arabic">
                14.2M
              </p>
              <svg className="w-20 h-8 text-emerald-500 stroke-current fill-none stroke-2" viewBox="0 0 100 40">
                <path d="M0,35 Q20,30 40,25 T70,15 T100,5" />
              </svg>
            </div>
            <p className="text-xs font-semibold text-slate-500 font-arabic mt-1">
              إجمالي الوصول
            </p>
          </div>

          {/* Metric 2 */}
          <div className="bg-white border border-slate-200/90 rounded-2xl p-5 shadow-xs hover:shadow-sm transition-all">
            <div className="flex items-start justify-between mb-3">
              <div className="flex items-center gap-1 bg-emerald-50 text-emerald-700 border border-emerald-200/70 px-2.5 py-1 rounded-full text-xs font-bold font-arabic">
                <TrendingUp className="w-3 h-3" />
                <span>+12.1%</span>
              </div>
              <div className="p-2.5 bg-slate-100 rounded-xl text-slate-600">
                <Clock className="w-5 h-5" />
              </div>
            </div>
            <div className="flex items-baseline justify-between">
              <p className="text-3xl font-black text-slate-900 font-arabic">
                2د 14ث
              </p>
              <svg className="w-20 h-8 text-teal-500 stroke-current fill-none stroke-2" viewBox="0 0 100 40">
                <path d="M0,30 Q25,35 50,20 T75,12 T100,8" />
              </svg>
            </div>
            <p className="text-xs font-semibold text-slate-500 font-arabic mt-1">
              متوسط وقت المشاهدة
            </p>
          </div>

          {/* Metric 3 (No duplicate number in badge) */}
          <div className="bg-white border-2 border-emerald-600/30 rounded-2xl p-5 shadow-xs hover:shadow-sm transition-all relative overflow-hidden">
            <div className="flex items-start justify-between mb-3">
              <div className="flex items-center gap-1 bg-emerald-600 text-white px-2.5 py-1 rounded-full text-xs font-bold">
                <Sparkles className="w-3 h-3" />
                <span>الأعلى نمواً</span>
              </div>
              <div className="p-2.5 bg-emerald-100/80 rounded-xl text-emerald-700">
                <Zap className="w-5 h-5" />
              </div>
            </div>
            <div className="flex items-baseline justify-between">
              <p className="text-3xl font-black text-emerald-800 font-arabic">
                +18.4%
              </p>
              <svg className="w-20 h-8 text-emerald-600 stroke-current fill-none stroke-2" viewBox="0 0 100 40">
                <path d="M0,38 Q20,32 45,18 T75,10 T100,2" />
              </svg>
            </div>
            <p className="text-xs font-bold text-emerald-900 font-arabic mt-1">
              رفع التفاعل الأصلي
            </p>
          </div>
        </div>
      </div>

      {/* ── Charts & Platform Breakdown ── */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-5">
        {/* Engagement Area Chart (3 cols) */}
        <div className="lg:col-span-3 bg-white border border-slate-200/90 rounded-2xl p-5 shadow-xs">
          <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
            <div className="flex items-center gap-2">
              <div className="p-1.5 bg-slate-100 rounded-lg text-slate-700">
                <BarChart2 className="w-4 h-4" />
              </div>
              <h3 className="text-sm font-bold text-slate-900 font-arabic">
                منحنى التفاعل الأسبوعي
              </h3>
            </div>

            {/* Filter Toggle */}
            <div className="flex items-center gap-1 bg-slate-100 p-1 rounded-xl">
              <button
                onClick={() => setChartMetric('all')}
                className={`px-2.5 py-1 rounded-lg text-xs font-semibold font-arabic transition-colors ${
                  chartMetric === 'all'
                    ? 'bg-white text-slate-900 shadow-2xs'
                    : 'text-slate-600 hover:text-slate-900'
                }`}
              >
                الكل
              </button>
              <button
                onClick={() => setChartMetric('engagement')}
                className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold font-arabic transition-colors ${
                  chartMetric === 'engagement'
                    ? 'bg-emerald-700 text-white shadow-2xs'
                    : 'text-emerald-700 hover:bg-emerald-50'
                }`}
              >
                <span className="w-2 h-2 rounded-full bg-emerald-500" />
                التفاعل
              </button>
              <button
                onClick={() => setChartMetric('reach')}
                className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold font-arabic transition-colors ${
                  chartMetric === 'reach'
                    ? 'bg-teal-700 text-white shadow-2xs'
                    : 'text-teal-700 hover:bg-teal-50'
                }`}
              >
                <span className="w-2 h-2 rounded-full bg-teal-400" />
                الوصول
              </button>
            </div>
          </div>

          <div className="h-60 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={weeklyData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="gradEngage" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#059669" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="#059669" stopOpacity={0.0} />
                  </linearGradient>
                  <linearGradient id="gradReach" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#2dd4bf" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="#2dd4bf" stopOpacity={0.0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                <XAxis
                  dataKey="day"
                  tick={{ fontSize: 12, fill: '#64748b', fontFamily: 'Tajawal, sans-serif' }}
                  axisLine={{ stroke: '#e2e8f0' }}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fontSize: 11, fill: '#94a3b8' }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#ffffff',
                    borderColor: '#e2e8f0',
                    borderRadius: '16px',
                    boxShadow: '0 10px 25px -5px rgba(0, 0, 0, 0.1)',
                    fontFamily: 'Tajawal, sans-serif',
                    direction: 'rtl',
                    textAlign: 'right',
                    padding: '8px 12px',
                  }}
                  formatter={(value: any, name: any) => [
                    `${value} ألف`,
                    name === 'reach' ? 'الوصول' : 'التفاعل',
                  ]}
                  labelFormatter={(label) => `يوم ${label}`}
                />
                {(chartMetric === 'all' || chartMetric === 'reach') && (
                  <Area
                    type="monotone"
                    dataKey="reach"
                    stroke="#0d9488"
                    strokeWidth={2}
                    fill="url(#gradReach)"
                    name="reach"
                  />
                )}
                {(chartMetric === 'all' || chartMetric === 'engagement') && (
                  <Area
                    type="monotone"
                    dataKey="engagement"
                    stroke="#059669"
                    strokeWidth={2.5}
                    fill="url(#gradEngage)"
                    name="engagement"
                  />
                )}
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Platform Breakdown (2 cols) */}
        <div className="lg:col-span-2 bg-white border border-slate-200/90 rounded-2xl p-5 shadow-xs flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-bold text-slate-900 font-arabic">
                توزيع المنصات
              </h3>
            </div>

            <div className="space-y-3.5">
              {platforms.map((p) => (
                <div key={p.name} className="p-2 rounded-xl hover:bg-slate-50 transition-colors">
                  <div className="flex items-center justify-between mb-1.5">
                    <div className="flex items-center gap-2">
                      <span className={`w-2.5 h-2.5 rounded-full ${p.color}`} />
                      <span className="text-xs font-bold text-slate-800 font-arabic">{p.name}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-medium text-slate-400 font-arabic">{p.count}</span>
                      <span className="text-xs font-black text-slate-900">{p.share}%</span>
                    </div>
                  </div>
                  <div className="w-full h-2 bg-slate-100 rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all duration-700"
                      style={{ width: `${p.share}%`, backgroundColor: p.barColor }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>
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
              const meta = DIMENSION_META[pattern.dimension];
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
