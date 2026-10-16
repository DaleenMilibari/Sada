import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, Bot, CheckCircle2, ExternalLink, Loader2, MousePointerClick, ShieldQuestion } from 'lucide-react';
import { ApiError, apiFetch, describeError } from '../lib/api';
import AlertsPanel from './AlertsPanel';
import type { Alert, DiagnosisResult } from '../types';

interface AlertsViewProps {
  onNotify?: (title: string, desc?: string, type?: 'success' | 'info') => void;
}

interface Message {
  id: string;
  role: 'user' | 'agent';
  alert?: Alert;
  text?: string;
  result?: DiagnosisResult;
}

function isLink(ref: string): boolean {
  return /^https?:\/\//.test(ref);
}

function DiagnosisBlock({ result }: { result: DiagnosisResult }) {
  return (
    <div className="space-y-3 text-right">
      {result.low_confidence && (
        <div className="flex items-start gap-2 bg-amber-50 border border-amber-200 rounded-xl p-3">
          <ShieldQuestion className="w-4 h-4 text-amber-700 shrink-0 mt-0.5" />
          <p className="text-xs font-bold text-amber-800 font-arabic">أدلة غير كافية — لا يمكن تقديم تشخيص موثوق، ولن نخمّن سبباً.</p>
        </div>
      )}
      <p className="text-sm text-slate-800 font-arabic leading-relaxed font-medium">{result.diagnosis}</p>

      {result.contributing_factors.length > 0 && (
        <div className="space-y-2">
          {result.contributing_factors.map((f, i) => (
            <div key={i} className="bg-white rounded-xl p-3 border border-slate-200/80 shadow-2xs">
              <h5 className="text-xs font-bold text-slate-900 font-arabic">{f.reason}</h5>
              <p className="text-xs text-slate-600 font-arabic mt-0.5">{f.supporting_metric}</p>
              <div className="flex items-center justify-between mt-1.5 text-[10px] text-slate-400 font-arabic">
                <span>ثقة: {Math.round(f.confidence * 100)}%</span>
                {isLink(f.evidence_url_or_ref) ? (
                  <a
                    href={f.evidence_url_or_ref}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1 text-emerald-700 hover:text-emerald-900 font-bold max-w-[70%]"
                    title={f.evidence_source_title}
                  >
                    <ExternalLink className="w-3 h-3 shrink-0" />
                    <span className="truncate">الدليل: {f.evidence_source_title}</span>
                  </a>
                ) : (
                  <span>{f.evidence_source_title}</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {result.recommendations.length > 0 && (
        <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-3 space-y-1.5">
          {result.recommendations.map((rec, i) => (
            <p key={i} className="text-xs font-bold text-emerald-800 font-arabic flex items-start gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-700 shrink-0 mt-0.5" />
              <span>{rec}</span>
            </p>
          ))}
        </div>
      )}
      {!result.low_confidence && (
        <p className="text-[10px] text-slate-400 font-arabic">
          التشخيص مبني على مقارنة المنشور بمنشورات مشابهة؛ هذه ارتباطات وليست أسباباً مثبتة.
        </p>
      )}
    </div>
  );
}

// "التنبيهات والتشخيص": detected spikes/drops on the left, click one to diagnose it (Task 4).
export default function BroadcastView({ onNotify }: AlertsViewProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, busy]);

  const diagnose = async (alert: Alert) => {
    if (busy) return;
    setSelectedId(alert.alert_id);
    setBusy(true);
    const stamp = Date.now().toString();
    setMessages((prev) => [...prev, { id: stamp, role: 'user', alert }]);
    try {
      const result = await apiFetch<DiagnosisResult>('/api/diagnose/video', {
        method: 'POST',
        body: JSON.stringify({ video_id: alert.video.video_id }),
      });
      setMessages((prev) => [...prev, { id: stamp + '-a', role: 'agent', result }]);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return; // App switches to the login screen
      const { title, desc } = describeError(err);
      onNotify?.(title, desc, 'info');
      setMessages((prev) => [...prev, { id: stamp + '-e', role: 'agent', text: `تعذر إجراء التشخيص: ${title}.` }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="animate-fade-in grid grid-cols-1 xl:grid-cols-2 gap-6">
      <AlertsPanel selectedId={selectedId} onSelect={diagnose} />

      <div className="bg-white border border-slate-200/90 rounded-2xl shadow-xs flex flex-col min-h-[420px] max-h-[760px]">
        <div className="px-5 py-3 border-b border-slate-100 flex items-center gap-2">
          <div className="p-1.5 bg-emerald-50 rounded-lg text-emerald-700">
            <Bot className="w-4 h-4" />
          </div>
          <h3 className="text-sm font-bold text-slate-900 font-arabic">التشخيص</h3>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {messages.length === 0 && (
            <div className="h-full flex flex-col items-center justify-center text-center text-slate-400 py-16">
              <MousePointerClick className="w-8 h-8 mb-3" />
              <p className="text-sm font-arabic">اختر تنبيهاً من القائمة لتشخيص سبب القفزة أو الانخفاض</p>
              <p className="text-xs font-arabic mt-1">كل عامل في التشخيص يرتبط بمنشور حقيقي كدليل</p>
            </div>
          )}

          {messages.map((m) =>
            m.role === 'user' && m.alert ? (
              <div key={m.id} className="flex justify-start">
                <div className="bg-slate-900 text-white rounded-2xl px-4 py-2.5 max-w-[85%] text-right">
                  <p className="text-xs font-arabic flex items-center gap-1.5">
                    <AlertTriangle className="w-3.5 h-3.5" />
                    {m.alert.kind === 'spike' ? 'لماذا تفوّق هذا المنشور؟' : 'لماذا تراجع هذا المنشور؟'}
                  </p>
                  <p className="text-[11px] text-slate-300 font-arabic mt-0.5 line-clamp-2">{m.alert.video.title}</p>
                </div>
              </div>
            ) : (
              <div key={m.id} className="flex justify-end">
                <div className="bg-slate-50 border border-slate-200/80 rounded-2xl p-4 max-w-[95%] w-full">
                  {m.result ? <DiagnosisBlock result={m.result} /> : <p className="text-sm text-slate-700 font-arabic">{m.text}</p>}
                </div>
              </div>
            ),
          )}

          {busy && (
            <div className="flex items-center gap-2 text-xs text-slate-500 font-arabic">
              <Loader2 className="w-4 h-4 animate-spin" />
              جارٍ مقارنة المنشور بمنشورات مشابهة...
            </div>
          )}
          <div ref={endRef} />
        </div>
      </div>
    </div>
  );
}
