import { useState, useRef, useEffect } from 'react';
import {
  Tv2, AlertTriangle, CheckCircle2, Send,
  Bot, User, Play, Pause, Volume2, Maximize2,
  Activity, Scissors, Wifi, Zap, Copy, Check,
  ThumbsUp, TrendingDown, Radio
} from 'lucide-react';

interface BroadcastViewProps {
  onNotify?: (title: string, desc?: string, type?: 'success' | 'info') => void;
}

interface Message {
  id: string;
  role: 'user' | 'agent';
  content: string | React.ReactNode;
  timestamp: string;
  sources?: string[];
}

// Mirrors backend/schemas.py::AwjDiagnosisRequest.
type AwjTopic = 'podcast_reach' | 'x_relationship';

// Mirrors backend/schemas.py::ContributingFactor.
interface ContributingFactor {
  reason: string;
  supporting_metric: string;
  evidence_source_title: string;
  evidence_url_or_ref: string;
  confidence: number;
}

// Mirrors backend/schemas.py::DiagnosisResult.
interface DiagnosisResult {
  diagnosis: string;
  contributing_factors: ContributingFactor[];
  recommendations: string[];
  low_confidence: boolean;
}

// Mirrors backend/schemas.py::BroadcastSignalPoint / BroadcastSegment / ClipOpportunity.
interface BroadcastSignalPoint {
  timestamp_seconds: number;
  engagement_level: number;
}

interface BroadcastSegment {
  start_seconds: number;
  end_seconds: number;
  label: string;
}

interface ClipOpportunityDetail {
  start_time: number;
  end_time: number;
  segment_label: string;
  spike_magnitude: number;
  confidence: number;
}

interface ClipOpportunity {
  clip_opportunity: ClipOpportunityDetail;
}

interface TimelineBar {
  time: string;
  level: number;
  isSpike: boolean;
}

const API_BASE = 'http://localhost:8000';

function formatTime(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60);
  const s = Math.floor(totalSeconds % 60);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

// Down-samples the raw 10s-interval signal into ~12 bars (bucket = max level in
// range, so a spike never gets averaged away) and flags any bar overlapping a
// detected clip window — mirrors the chart's previous 12-bar hourly layout.
function buildTimelineBars(
  signal: BroadcastSignalPoint[],
  clips: ClipOpportunityDetail[],
  barCount = 12
): TimelineBar[] {
  if (signal.length === 0) return [];
  const bucketSize = Math.max(1, Math.ceil(signal.length / barCount));
  const bars: TimelineBar[] = [];
  for (let i = 0; i < signal.length; i += bucketSize) {
    const chunk = signal.slice(i, i + bucketSize);
    const bucketStart = chunk[0].timestamp_seconds;
    const bucketEnd = chunk[chunk.length - 1].timestamp_seconds;
    const level = Math.max(...chunk.map((p) => p.engagement_level));
    const isSpike = clips.some((c) => bucketEnd >= c.start_time && bucketStart < c.end_time);
    bars.push({ time: formatTime(bucketStart), level: Math.min(100, level), isSpike });
  }
  return bars;
}

const INITIAL_MESSAGES: Message[] = [
  {
    id: '1',
    role: 'agent',
    content: 'اختر أحد الأسئلة أدناه وسأشخّصه بالاستناد إلى بيانات أوج | صدى الحقيقية (حلقات رهان وSO ومنشورات X الموثقة).',
    timestamp: '—',
  },
];

// Grounded in the real AWJ | Sada dataset (backend/data/raw/awj_sada_data.json)
// via diagnostic_recommendation_agent.diagnose_awj_topic — not the synthetic
// content_history.json. See NEXT_STEPS.md Task D for the original (now
// superseded) synthetic-item version of this chat.
const DIAGNOSIS_ITEMS: { label: string; topic: AwjTopic }[] = [
  {
    label: 'لماذا تحقق حلقات "رهان" مشاهدات يوتيوب أعلى من حلقات "SO"؟',
    topic: 'podcast_reach',
  },
  {
    label: 'لماذا تتفوق منشورات الحساب الرسمي @Medhalpodcast على منشورات إعادة النشر على X؟',
    topic: 'x_relationship',
  },
];

function renderDiagnosisMessage(result: DiagnosisResult): React.ReactNode {
  return (
    <div className="space-y-3 text-right">
      <p className="text-sm text-slate-800 font-arabic leading-relaxed font-medium">
        {result.diagnosis}
      </p>

      {result.contributing_factors.length > 0 && (
        <div className="space-y-2">
          {result.contributing_factors.map((factor, i) => (
            <div key={i} className="flex items-start gap-3 bg-white rounded-xl p-3 border border-slate-200/80 shadow-2xs">
              <div className="p-1 rounded-lg bg-slate-50 border border-slate-100 flex-shrink-0 mt-0.5">
                {i === 0 ? (
                  <TrendingDown className="w-4 h-4 text-amber-500" />
                ) : (
                  <Radio className="w-4 h-4 text-slate-500" />
                )}
              </div>
              <div className="text-right">
                <h5 className="text-xs font-bold text-slate-900 font-arabic">{factor.reason}</h5>
                <p className="text-xs text-slate-600 font-arabic mt-0.5 leading-relaxed">
                  {factor.supporting_metric}
                </p>
                <span className="text-[10px] text-slate-400 font-arabic">
                  ثقة: {Math.round(factor.confidence * 100)}%
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {result.recommendations.length > 0 && (
        <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-3 space-y-1.5">
          {result.recommendations.map((rec, i) => (
            <p key={i} className="text-xs font-bold text-emerald-800 font-arabic flex items-start gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-700 flex-shrink-0 mt-0.5" />
              <span>{rec}</span>
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

export default function BroadcastView({ onNotify }: BroadcastViewProps) {
  const [messages, setMessages] = useState<Message[]>(INITIAL_MESSAGES);
  const [input, setInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [clipApproved, setClipApproved] = useState(false);
  const [activeChannel, setActiveChannel] = useState('رهان');
  const [isPlaying, setIsPlaying] = useState(true);
  const [copiedResponse, setCopiedResponse] = useState(false);
  const [likedResponse, setLikedResponse] = useState(false);
  const [broadcastLoading, setBroadcastLoading] = useState(true);
  const [signal, setSignal] = useState<BroadcastSignalPoint[]>([]);
  const [clips, setClips] = useState<ClipOpportunityDetail[]>([]);
  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping]);

  useEffect(() => {
    (async () => {
      try {
        const [signalRes, clipsRes] = await Promise.all([
          fetch(`${API_BASE}/api/broadcast/signal`),
          fetch(`${API_BASE}/api/broadcast/detect-clips`, { method: 'POST' }),
        ]);
        if (!signalRes.ok || !clipsRes.ok) throw new Error('broadcast fetch failed');

        const signalData: { signal: BroadcastSignalPoint[]; segments: BroadcastSegment[] } =
          await signalRes.json();
        const clipsData: ClipOpportunity[] = await clipsRes.json();

        setSignal(signalData.signal);
        setClips(clipsData.map((c) => c.clip_opportunity));
      } catch {
        onNotify?.('تعذر تحميل بيانات البث', 'تأكد من تشغيل الخادم الخلفي على المنفذ 8000', 'info');
      } finally {
        setBroadcastLoading(false);
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    })();
  }, []);

  const timelineBars = buildTimelineBars(signal, clips);
  const topClip = clips[0];

  const runDiagnosis = async (entry: { label: string; topic: AwjTopic }) => {
    if (isTyping) return;

    const userMsg: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: entry.label,
      timestamp: new Date().toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' }),
    };
    setMessages((prev) => [...prev, userMsg]);
    setIsTyping(true);

    try {
      const res = await fetch(`${API_BASE}/api/diagnose/awj-sada`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic: entry.topic }),
      });

      if (res.status === 503) {
        onNotify?.('مفتاح Gemini API غير مهيأ', 'أضف GEMINI_API_KEY إلى backend/.env لتفعيل التشخيص', 'info');
        setMessages((prev) => [
          ...prev,
          {
            id: Date.now().toString() + '-agent-error',
            role: 'agent',
            content: 'تعذر إجراء التشخيص: مفتاح Gemini API غير مهيأ على الخادم.',
            timestamp: new Date().toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' }),
          },
        ]);
        return;
      }

      if (!res.ok) {
        throw new Error(`Request failed: ${res.status}`);
      }

      const result: DiagnosisResult = await res.json();
      const sources = Array.from(new Set(result.contributing_factors.map((f) => f.evidence_source_title)));

      setMessages((prev) => [
        ...prev,
        {
          id: Date.now().toString() + '-agent',
          role: 'agent',
          content: renderDiagnosisMessage(result),
          timestamp: new Date().toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' }),
          sources,
        },
      ]);
    } catch {
      onNotify?.('تعذر الاتصال بخادم التشخيص', 'تأكد من تشغيل الخادم الخلفي على المنفذ 8000', 'info');
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now().toString() + '-agent-error',
          role: 'agent',
          content: 'تعذر الاتصال بخادم التشخيص. تأكد من تشغيل الخادم الخلفي.',
          timestamp: new Date().toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' }),
        },
      ]);
    } finally {
      setIsTyping(false);
    }
  };

  const handleApproveClip = () => {
    setClipApproved(true);
    onNotify?.(
      'تم اعتماد ونشر المقطع',
      'تم بث اللقطة (20 ثانية) والتغريدة المترجمة تلقائياً',
      'success'
    );
  };

  return (
    <div className="animate-fade-in space-y-6">
      {/* ── Section 1: Broadcast Monitor & Viral Spike ── */}
      <div className="bg-white border border-slate-200/90 rounded-2xl shadow-xs overflow-hidden">
        {/* Channel Selector Header */}
        <div className="px-5 py-3 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
          <div className="flex items-center gap-2">
            {/* Real AWJ | Sada podcasts (backend/newData) - both are covered by the real awj_sada_real patterns */}
            {['رهان', 'SO'].map((ch) => (
              <button
                key={ch}
                onClick={() => {
                  setActiveChannel(ch);
                  onNotify?.('تم التبديل إلى ' + ch, '', 'info');
                }}
                className={`px-3 py-1 rounded-xl text-xs font-bold font-arabic transition-all cursor-pointer ${
                  activeChannel === ch
                    ? 'bg-slate-900 text-white shadow-2xs'
                    : 'bg-white text-slate-600 border border-slate-200 hover:bg-slate-100'
                }`}
              >
                {ch}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-2 text-xs text-slate-500 font-arabic">
            <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
            <span className="font-bold text-slate-700">48,290</span>
            <span>مشاهد</span>
          </div>
        </div>

        {/* Video Frame & Timeline */}
        <div className="grid grid-cols-1 lg:grid-cols-5">
          {/* Simulated Video Player */}
          <div className="lg:col-span-2 relative bg-slate-950 min-h-[230px] flex flex-col items-center justify-center p-6 select-none overflow-hidden group">
            {/* Top Badges */}
            <div className="absolute top-3 right-3 flex items-center gap-2 z-10">
              <span className="flex items-center gap-1 bg-red-600 text-white text-[10px] font-bold px-2 py-0.5 rounded-full shadow-xs">
                <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />
                مباشر
              </span>
              <span className="bg-black/60 text-slate-200 text-[10px] font-bold px-2 py-0.5 rounded-full font-arabic">
                {activeChannel}
              </span>
            </div>

            <div className="absolute top-3 left-3 z-10">
              <span className="flex items-center gap-1 bg-emerald-950/80 text-emerald-400 border border-emerald-500/30 text-[10px] font-bold px-2 py-0.5 rounded-full">
                <Wifi className="w-3 h-3" /> 1080p
              </span>
            </div>

            {/* Center Symbol / Audio Visualizer */}
            <div className="relative z-10 text-center my-auto">
              <div className="w-14 h-14 rounded-2xl bg-emerald-900/40 border border-emerald-500/30 flex items-center justify-center mx-auto mb-2 shadow-sm">
                <Tv2 className="w-7 h-7 text-emerald-400" />
              </div>
              <h4 className="text-white text-sm font-bold font-arabic">
                البث المباشر الموحد
              </h4>

              {/* Dynamic Soundwave Bars */}
              <div className="flex items-center justify-center gap-1 mt-3">
                {[12, 28, 45, 20, 50, 35, 45, 25, 38, 15].map((h, i) => (
                  <span
                    key={i}
                    className="w-1 bg-emerald-400/80 rounded-full animate-pulse"
                    style={{
                      height: `${h}px`,
                      animationDelay: `${i * 0.1}s`,
                      animationDuration: '1.2s',
                    }}
                  />
                ))}
              </div>
            </div>

            {/* Player Controls Bar */}
            <div className="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/80 to-transparent p-2.5 flex items-center justify-between text-white z-10">
              <div className="flex items-center gap-2.5">
                <button
                  onClick={() => setIsPlaying(!isPlaying)}
                  className="p-1 hover:bg-white/20 rounded transition-colors cursor-pointer"
                >
                  {isPlaying ? <Pause className="w-3.5 h-3.5 fill-white" /> : <Play className="w-3.5 h-3.5 fill-white" />}
                </button>
                <Volume2 className="w-3.5 h-3.5 text-slate-300" />
                <span className="text-[10px] font-bold text-slate-300">
                  12:04
                </span>
              </div>

              <Maximize2 className="w-3.5 h-3.5 text-slate-300" />
            </div>
          </div>

          {/* Social Activity Timeline */}
          <div className="lg:col-span-3 p-5 flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-bold text-slate-900 font-arabic">
                  نشاط التفاعل الرقمي
                </h3>
                <div className="flex items-center gap-1 text-xs text-slate-400 font-arabic">
                  <Activity className="w-4 h-4 text-emerald-600" />
                  <span>نبض البث</span>
                </div>
              </div>

              {/* Bar Chart */}
              <div className="flex items-end gap-1.5 h-28 my-2 px-2 bg-slate-50/70 rounded-xl p-3 border border-slate-100">
                {broadcastLoading ? (
                  <span className="text-xs text-slate-400 font-arabic mx-auto">جارٍ تحليل نشاط البث...</span>
                ) : (
                  timelineBars.map((item, i) => (
                    <div key={i} className="flex-1 flex flex-col items-center gap-1 group relative cursor-pointer">
                      <div className="absolute -top-7 bg-slate-900 text-white text-[10px] font-bold px-1.5 py-0.5 rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none z-20 font-arabic">
                        {item.time}: {Math.round(item.level)}%
                      </div>

                      <div
                        className={`w-full rounded-sm transition-all ${
                          item.isSpike
                            ? 'bg-amber-500 ring-2 ring-amber-300/70'
                            : 'bg-emerald-200/90 hover:bg-emerald-300'
                        }`}
                        style={{ height: `${item.level}%` }}
                      />
                      <span className="text-[9px] text-slate-400 font-arabic">
                        {item.time}
                      </span>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Timeline Legend */}
            <div className="flex items-center justify-between pt-2.5 border-t border-slate-100 text-xs font-arabic text-slate-500">
              <span className="text-[10px]">{timelineBars[0]?.time ?? '00:00'}</span>
              {topClip && (
                <div className="flex items-center gap-1 text-amber-700 font-bold">
                  <Zap className="w-3.5 h-3.5 fill-amber-500 text-amber-600" />
                  <span>
                    ذروة التفاعل عند {formatTime(topClip.start_time)} (+{Math.round(topClip.spike_magnitude)}%)
                  </span>
                </div>
              )}
              <span className="text-[10px]">{timelineBars[timelineBars.length - 1]?.time ?? '20:00'}</span>
            </div>
          </div>
        </div>

        {/* ── Viral Spike Alert Box ── */}
        {topClip && (
          <div className="border-t border-slate-100 bg-amber-50/70 border-r-4 border-r-amber-500 p-5 transition-all">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
              <div className="text-right flex-1">
                <div className="flex items-center gap-2 mb-1.5">
                  <AlertTriangle className="w-4 h-4 text-amber-600" />
                  <h4 className="text-sm font-bold text-slate-900 font-arabic">
                    تنبيه لقطة فيروسية مكتشفة! (ثقة {Math.round(topClip.confidence * 100)}%)
                  </h4>
                </div>

                <p className="text-xs text-slate-800 font-arabic leading-relaxed">
                  عند الدقيقة <span className="font-bold text-amber-800">{formatTime(topClip.start_time)}</span> ارتفع تفاعل الجمهور الرقمي بنسبة{' '}
                  <span className="font-bold text-amber-800">{Math.round(topClip.spike_magnitude)}%</span> خلال فقرة{' '}
                  <span className="font-bold text-slate-900">«{topClip.segment_label}»</span>. قام النظام تلقائياً
                  بتحديد لقطة مدتها{' '}
                  <span className="font-bold text-slate-900">{topClip.end_time - topClip.start_time} ثانية</span> جاهزة للمراجعة والنشر.
                </p>

                {clips.length > 1 && (
                  <p className="mt-1.5 text-[11px] text-amber-700 font-arabic">
                    + {clips.length - 1} فرصة أخرى مكتشفة خلال هذا البث.
                  </p>
                )}
              </div>

              {/* Action Button */}
              <div className="flex-shrink-0">
                <button
                  onClick={handleApproveClip}
                  disabled={clipApproved}
                  className={`w-full md:w-auto flex items-center justify-center gap-2 px-5 py-3 rounded-xl text-xs font-bold font-arabic shadow-xs transition-all cursor-pointer ${
                    clipApproved
                      ? 'bg-emerald-700 text-white'
                      : 'bg-amber-500 hover:bg-amber-600 text-white active:scale-95'
                  }`}
                >
                  {clipApproved ? (
                    <>
                      <CheckCircle2 className="w-4 h-4" />
                      <span>تم اعتماد ونشر المقطع</span>
                    </>
                  ) : (
                    <>
                      <Scissors className="w-4 h-4" />
                      <span>اعتماد ونشر المقطع الفيروسي</span>
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        )}
        {!broadcastLoading && !topClip && (
          <div className="border-t border-slate-100 bg-slate-50/70 p-4 text-center">
            <span className="text-xs text-slate-500 font-arabic">لا توجد لقطات فيروسية بارزة حالياً في هذا البث.</span>
          </div>
        )}
      </div>

      {/* ── Section 2: RAG Diagnostic Chat ── */}
      <div className="bg-white border border-slate-200/90 rounded-2xl shadow-xs overflow-hidden">
        {/* Chat Top Header */}
        <div className="px-5 py-3.5 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
            <span className="text-xs font-bold text-emerald-800 font-arabic">
              محرك الذاكرة متصل (RAG)
            </span>
          </div>

          <div className="flex items-center gap-2">
            <h3 className="text-sm font-bold text-slate-900 font-arabic">
              المساعد التشخيصي الذكي
            </h3>
            <div className="p-1 bg-emerald-700 text-white rounded-lg">
              <Bot className="w-4 h-4" />
            </div>
          </div>
        </div>

        {/* Published items available for diagnosis */}
        <div className="px-5 py-2.5 bg-slate-50/30 border-b border-slate-100 flex flex-wrap items-center gap-2">
          {DIAGNOSIS_ITEMS.map((entry) => (
            <button
              key={entry.topic}
              onClick={() => runDiagnosis(entry)}
              disabled={isTyping}
              className="text-xs bg-white hover:bg-emerald-50 text-slate-700 hover:text-emerald-800 border border-slate-200 rounded-full px-3 py-1 font-arabic transition-all cursor-pointer shadow-2xs disabled:cursor-not-allowed disabled:opacity-60"
            >
              {entry.label}
            </button>
          ))}
        </div>

        {/* Messages */}
        <div className="p-5 space-y-4 max-h-[360px] overflow-y-auto bg-slate-50/20">
          {messages.map((msg) => {
            const isUser = msg.role === 'user';
            return (
              <div
                key={msg.id}
                className={`flex gap-3 animate-slide-up ${isUser ? 'flex-row-reverse' : 'flex-row'}`}
              >
                <div
                  className={`w-7 h-7 rounded-xl flex-shrink-0 flex items-center justify-center text-xs ${
                    isUser ? 'bg-slate-900 text-white' : 'bg-emerald-700 text-white'
                  }`}
                >
                  {isUser ? <User className="w-3.5 h-3.5" /> : <Bot className="w-3.5 h-3.5" />}
                </div>

                <div className={`flex flex-col max-w-[85%] ${isUser ? 'items-end' : 'items-start'}`}>
                  <div
                    className={`p-4 rounded-2xl text-sm ${
                      isUser
                        ? 'bg-slate-900 text-white rounded-tr-xs'
                        : 'bg-white text-slate-900 border border-slate-200/90 shadow-2xs rounded-tl-xs'
                    }`}
                  >
                    {typeof msg.content === 'string' ? (
                      <p className="font-arabic leading-relaxed">{msg.content}</p>
                    ) : (
                      msg.content
                    )}

                    {msg.sources && (
                      <div className="mt-3 pt-2 border-t border-slate-100 flex flex-wrap items-center gap-1 text-[10px] text-slate-400 font-arabic">
                        <span>المصادر:</span>
                        {msg.sources.map((src, idx) => (
                          <span key={idx} className="bg-slate-100 text-slate-600 px-1.5 py-0.2 rounded font-medium">
                            {src}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="flex items-center gap-2 mt-1 px-1 text-[10px] text-slate-400 font-arabic">
                    <span>{msg.timestamp}</span>
                    {!isUser && (
                      <div className="flex items-center gap-1 mr-2">
                        <button
                          onClick={() => {
                            setLikedResponse(!likedResponse);
                            onNotify?.('شكراً لتقييمك', '', 'info');
                          }}
                          className={`p-0.5 hover:text-emerald-700 ${likedResponse ? 'text-emerald-700' : ''}`}
                        >
                          <ThumbsUp className="w-3 h-3" />
                        </button>
                        <button
                          onClick={() => {
                            setCopiedResponse(true);
                            onNotify?.('تم نسخ الإجابة', '', 'success');
                            setTimeout(() => setCopiedResponse(false), 1500);
                          }}
                          className="p-0.5 hover:text-emerald-700"
                        >
                          {copiedResponse ? <Check className="w-3 h-3 text-emerald-600" /> : <Copy className="w-3 h-3" />}
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            );
          })}

          {isTyping && (
            <div className="flex gap-3">
              <div className="w-7 h-7 rounded-xl bg-emerald-700 text-white flex-shrink-0 flex items-center justify-center">
                <Bot className="w-3.5 h-3.5" />
              </div>
              <div className="bg-white border border-slate-200 rounded-2xl rounded-tl-xs p-3 shadow-2xs flex items-center gap-2">
                <span className="text-xs text-slate-400 font-arabic">جارٍ التحليل...</span>
                <div className="flex items-center gap-1">
                  {[0, 1, 2].map((i) => (
                    <span
                      key={i}
                      className="w-1.5 h-1.5 rounded-full bg-emerald-600 animate-bounce"
                      style={{ animationDelay: `${i * 0.15}s` }}
                    />
                  ))}
                </div>
              </div>
            </div>
          )}

          <div ref={chatEndRef} />
        </div>

        {/* Input Bar — free-text questions aren't grounded in any agent yet (see NEXT_STEPS.md Task D), so typing here explains that instead of faking an answer */}
        <div className="p-3 border-t border-slate-100 bg-white">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (!input.trim()) return;
              onNotify?.(
                'الأسئلة النصية الحرة غير مدعومة بعد',
                'اختر أحد المنشورات أعلاه للحصول على تشخيص مبني على بيانات حقيقية',
                'info'
              );
              setInput('');
            }}
            className="flex items-center gap-2"
          >
            <button
              type="submit"
              disabled={!input.trim() || isTyping}
              className="p-2.5 bg-emerald-700 hover:bg-emerald-800 disabled:bg-slate-200 text-white rounded-xl transition-colors cursor-pointer disabled:cursor-not-allowed"
            >
              <Send className="w-4 h-4 transform rotate-180" />
            </button>

            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="اختر منشوراً أعلاه للتشخيص (الأسئلة الحرة غير مدعومة بعد)"
              className="flex-1 text-right text-xs font-bold text-slate-800 placeholder:text-slate-400 bg-slate-50 border border-slate-200 rounded-xl px-4 py-2.5 font-arabic outline-none focus:border-emerald-500 transition-all"
            />
          </form>
        </div>
      </div>
    </div>
  );
}
