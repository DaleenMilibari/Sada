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

const AGENT_RESPONSE = (
  <div className="space-y-3 text-right">
    <p className="text-sm text-slate-800 font-arabic leading-relaxed font-medium">
      رصد محرك التشخيص الذكي انخفاضاً بنسبة{' '}
      <span className="font-bold text-red-600">31%</span> في متوسط التفاعل خلال الفترة المسائية لأمس. الأسباب الجذرية:
    </p>

    <div className="space-y-2">
      {[
        {
          icon: <Radio className="w-4 h-4 text-red-500" />,
          title: 'تداخل مع حدث إخباري عاجل موازٍ',
          desc: 'استحوذ حدث عاجل على 67% من انتباه الجمهور الرقمي بين 7 و 9 مساءً.',
        },
        {
          icon: <TrendingDown className="w-4 h-4 text-amber-500" />,
          title: 'انخفاض وتيرة الوسوم التفاعلية',
          desc: 'انخفض تداول الوسوم بنسبة 48% لتأخر اللقطات القصيرة عن لحظة الذروة.',
        },
        {
          icon: <Zap className="w-4 h-4 text-emerald-600" />,
          title: 'الإجراء التلقائي المتخذ',
          desc: 'أعاد النظام جدولة 3 منشورات مؤجلة إلى فترة الصباح الباكر، ما حقق استرداداً بنسبة +28%.',
        },
      ].map((item, i) => (
        <div key={i} className="flex items-start gap-3 bg-white rounded-xl p-3 border border-slate-200/80 shadow-2xs">
          <div className="p-1 rounded-lg bg-slate-50 border border-slate-100 flex-shrink-0 mt-0.5">
            {item.icon}
          </div>
          <div className="text-right">
            <h5 className="text-xs font-bold text-slate-900 font-arabic">{item.title}</h5>
            <p className="text-xs text-slate-600 font-arabic mt-0.5 leading-relaxed">{item.desc}</p>
          </div>
        </div>
      ))}
    </div>

    <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-3 flex items-center gap-2">
      <CheckCircle2 className="w-4 h-4 text-emerald-700 flex-shrink-0" />
      <p className="text-xs font-bold text-emerald-800 font-arabic">
        خطة التعافي التلقائي جارية — يتوقع استرداد المعدل الطبيعي خلال 4 ساعات.
      </p>
    </div>
  </div>
);

const INITIAL_MESSAGES: Message[] = [
  {
    id: '1',
    role: 'user',
    content: 'لماذا انخفض التفاعل أمس بشكل ملحوظ على جميع المنصات؟ وما الإجراءات التي اتخذها النظام؟',
    timestamp: '10:14 ص',
  },
  {
    id: '2',
    role: 'agent',
    content: AGENT_RESPONSE,
    timestamp: '10:14 ص',
    sources: ['سجل البث المرئي', 'تحليلات تفاعل إكس', 'مؤشرات المنصات'],
  },
];

const SUGGESTIONS = [
  'ما التوقيت الأنسب لإطلاق لقطة الدعم السكني؟',
  'قارن أداء اليوم بالمتوسط الأسبوعي',
  'ما الكلمات الأكثر تداولاً في محادثات الجمهور الآن؟',
];

const TIMELINE = [
  { time: '00:00', level: 25 },
  { time: '02:00', level: 18 },
  { time: '04:00', level: 12 },
  { time: '06:00', level: 38 },
  { time: '08:00', level: 52 },
  { time: '10:00', level: 60 },
  { time: '12:04', level: 96, isSpike: true },
  { time: '14:00', level: 46 },
  { time: '16:00', level: 40 },
  { time: '18:00', level: 68 },
  { time: '20:00', level: 82 },
  { time: '22:00', level: 64 },
];

export default function BroadcastView({ onNotify }: BroadcastViewProps) {
  const [messages, setMessages] = useState<Message[]>(INITIAL_MESSAGES);
  const [input, setInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [clipApproved, setClipApproved] = useState(false);
  const [activeChannel, setActiveChannel] = useState('القناة الأولى');
  const [isPlaying, setIsPlaying] = useState(true);
  const [copiedResponse, setCopiedResponse] = useState(false);
  const [likedResponse, setLikedResponse] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping]);

  const sendMessage = async (customText?: string) => {
    const textToSend = customText || input;
    if (!textToSend.trim()) return;

    const userMsg: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: textToSend,
      timestamp: new Date().toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' }),
    };

    setMessages((prev) => [...prev, userMsg]);
    if (!customText) setInput('');
    setIsTyping(true);

    await new Promise((r) => setTimeout(r, 1400));

    setIsTyping(false);
    setMessages((prev) => [
      ...prev,
      {
        id: Date.now().toString() + '-agent',
        role: 'agent',
        content: (
          <div className="space-y-2 text-right">
            <p className="text-sm text-slate-800 font-arabic leading-relaxed font-medium">
              بناءً على استرجاع المعرفة من أرشيف البث، تم تحليل: <span className="font-bold text-slate-900">{textToSend}</span>.
            </p>
            <p className="text-xs text-slate-600 font-arabic leading-relaxed">
              تشير البيانات إلى أن ذروة الاستجابة الرقمية تتوافق مع توقيت الساعة 8:00 مساءً. نوصي بنشر اللقطة الفيروسية مع وسمي #بث_مباشر و#حدث_وطني.
            </p>
          </div>
        ),
        timestamp: new Date().toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' }),
        sources: ['أرشيف البث', 'محرك التشخيص RAG'],
      },
    ]);
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
            {['القناة الأولى', 'قناة الإخبارية', 'القناة الرياضية'].map((ch) => (
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
                {TIMELINE.map((item, i) => (
                  <div key={i} className="flex-1 flex flex-col items-center gap-1 group relative cursor-pointer">
                    <div className="absolute -top-7 bg-slate-900 text-white text-[10px] font-bold px-1.5 py-0.5 rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none z-20 font-arabic">
                      {item.time}: {item.level}%
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
                      {item.time.split(':')[0]}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* Timeline Legend */}
            <div className="flex items-center justify-between pt-2.5 border-t border-slate-100 text-xs font-arabic text-slate-500">
              <span className="text-[10px]">00:00</span>
              <div className="flex items-center gap-1 text-amber-700 font-bold">
                <Zap className="w-3.5 h-3.5 fill-amber-500 text-amber-600" />
                <span>ذروة التفاعل عند 12:04 (+45%)</span>
              </div>
              <span className="text-[10px]">24:00</span>
            </div>
          </div>
        </div>

        {/* ── Viral Spike Alert Box (Cleaned of duplicate 12:04 text) ── */}
        <div className="border-t border-slate-100 bg-amber-50/70 border-r-4 border-r-amber-500 p-5 transition-all">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div className="text-right flex-1">
              <div className="flex items-center gap-2 mb-1.5">
                <AlertTriangle className="w-4 h-4 text-amber-600" />
                <h4 className="text-sm font-bold text-slate-900 font-arabic">
                  تنبيه لقطة فيروسية مكتشفة!
                </h4>
              </div>

              <p className="text-xs text-slate-800 font-arabic leading-relaxed">
                عند الدقيقة <span className="font-bold text-amber-800">12:04</span> ارتفع تفاعل الجمهور الرقمي بنسبة{' '}
                <span className="font-bold text-amber-800">45%</span> عندما تحدث الضيف عن الدعم السكني. قام النظام تلقائياً
                بقص لقطة مدتها <span className="font-bold text-slate-900">20 ثانية</span> وترجمتها نصياً وتجهيز التغريدة الفائزة.
              </p>

              <div className="mt-2 p-2.5 bg-white/90 border border-amber-200/60 rounded-xl text-xs text-slate-600 font-arabic italic">
                «نعمل اليوم وفق خطة وطنية لتمكين المواطنين عبر حلول الدعم السكني المتكاملة...»
              </div>
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

        {/* Suggested Prompts */}
        <div className="px-5 py-2.5 bg-slate-50/30 border-b border-slate-100 flex flex-wrap items-center gap-2">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => sendMessage(s)}
              className="text-xs bg-white hover:bg-emerald-50 text-slate-700 hover:text-emerald-800 border border-slate-200 rounded-full px-3 py-1 font-arabic transition-all cursor-pointer shadow-2xs"
            >
              {s}
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

        {/* Input Bar */}
        <div className="p-3 border-t border-slate-100 bg-white">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              sendMessage();
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
              placeholder="اكتب استفسارك عن أداء البث..."
              className="flex-1 text-right text-xs font-bold text-slate-800 placeholder:text-slate-400 bg-slate-50 border border-slate-200 rounded-xl px-4 py-2.5 font-arabic outline-none focus:border-emerald-500 transition-all"
            />
          </form>
        </div>
      </div>
    </div>
  );
}
