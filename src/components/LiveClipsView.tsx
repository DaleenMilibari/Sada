import { useCallback, useEffect, useMemo, useState } from 'react';
import { FlaskConical, Radio, RefreshCw, Scissors, TrendingUp } from 'lucide-react';
import {
  Area, AreaChart, CartesianGrid, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { ApiError, apiFetch, describeError } from '../lib/api';
import type { BroadcastSnapshot, ClipOpportunityDetail, ClipOpportunity } from '../types';

const CARD = 'bg-white border border-slate-200/90 rounded-2xl p-5 shadow-xs';
// Alternating light bands so each broadcast segment is visible behind the signal.
const SEGMENT_FILLS = ['#f8fafc', '#f1f5f9'];

const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

interface LiveClipsViewProps {
  onNotify?: (title: string, desc?: string, type?: 'success' | 'info') => void;
}

// "لقطات البث المباشر": engagement during a broadcast, the segments it ran through, and the
// spikes the Live Clip Detection agent flags as clip opportunities. The signal is simulated
// (backend/data/broadcast_mock.json) until the YouTube live feed is connected - the page says so.
export default function LiveClipsView({ onNotify }: LiveClipsViewProps) {
  const [broadcast, setBroadcast] = useState<BroadcastSnapshot | null>(null);
  const [clips, setClips] = useState<ClipOpportunityDetail[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [snapshot, found] = await Promise.all([
        apiFetch<BroadcastSnapshot>('/api/broadcast/signal'),
        apiFetch<ClipOpportunity[]>('/api/broadcast/detect-clips', { method: 'POST' }),
      ]);
      setBroadcast(snapshot);
      setClips(found.map((c) => c.clip_opportunity));
      setSelected(null);
      setError(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return; // App switches to the login screen
      const { title, desc } = describeError(err);
      setError(title);
      onNotify?.(title, desc, 'info');
    } finally {
      setLoading(false);
    }
  }, [onNotify]);

  useEffect(() => {
    load();
  }, [load]);

  const signal = useMemo(
    () => [...(broadcast?.signal ?? [])].sort((a, b) => a.timestamp_seconds - b.timestamp_seconds),
    [broadcast],
  );
  const baseline = useMemo(() => {
    if (!signal.length) return null;
    const sorted = signal.map((p) => p.engagement_level).sort((a, b) => a - b);
    return sorted[Math.floor(sorted.length / 2)];
  }, [signal]);
  const duration = signal.length ? signal[signal.length - 1].timestamp_seconds : 0;
  const best = clips?.[0];

  return (
    <div className="space-y-5 animate-fade-in">
      {/* ── Header ── */}
      <div className={`${CARD} flex flex-wrap items-start justify-between gap-4`}>
        <div className="flex items-start gap-3">
          <div className="p-2 bg-rose-50 rounded-xl text-rose-600">
            <Radio className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-base font-black text-slate-900 font-arabic">فرص اللقطات أثناء البث</h2>
            <p className="text-xs text-slate-500 font-arabic mt-1 leading-relaxed max-w-2xl">
              يرصد الوكيل القفزات المفاجئة في تفاعل الجمهور مقارنة بالمستوى المعتاد للدقيقتين السابقتين،
              ويربط كل قفزة بالفقرة التي حدثت فيها لتقطيعها ونشرها على المنصات.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1.5 text-[11px] font-bold text-amber-800 bg-amber-50 border border-amber-200 px-2.5 py-1 rounded-lg font-arabic">
            <FlaskConical className="w-3.5 h-3.5" />
            إشارة محاكاة · لم يُربط البث المباشر بعد
          </span>
          <button
            onClick={load}
            disabled={loading}
            className="p-2 rounded-lg text-slate-500 hover:text-slate-900 hover:bg-slate-100 disabled:opacity-50 transition-colors"
            aria-label="إعادة التحليل"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {error && !broadcast && (
        <div className={`${CARD} text-center py-12`}>
          <p className="text-sm text-slate-500 font-arabic">{error}</p>
        </div>
      )}

      {!broadcast && !error && <div className={`${CARD} h-80 bg-slate-100 animate-pulse`} />}

      {broadcast && (
        <>
          {/* ── Stat tiles ── */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <Stat label="مدة البث المحلَّل" value={clock(duration)} hint={`${signal.length} قراءة · كل 10 ثوانٍ`} />
            <Stat label="فرص اللقطات" value={String(clips?.length ?? 0)} hint="قفزات تتجاوز المعتاد بوضوح" />
            <Stat
              label="أقوى قفزة"
              value={best ? `+${Math.round(best.spike_magnitude)}%` : '—'}
              hint={best ? `${best.segment_label} · ${clock(best.start_time)}` : 'لا توجد قفزة كافية'}
            />
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
            {/* ── Signal chart ── */}
            <div className={`xl:col-span-2 ${CARD}`}>
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-bold text-slate-900 font-arabic">تفاعل الجمهور خلال البث</h3>
                <div className="flex items-center gap-3 text-[11px] text-slate-500 font-arabic">
                  <span className="inline-flex items-center gap-1"><span className="w-3 h-2 rounded-sm bg-rose-200" />لقطة مرصودة</span>
                  <span className="inline-flex items-center gap-1"><span className="w-3 h-2 rounded-sm bg-slate-200" />فقرة</span>
                </div>
              </div>
              <div className="h-72" dir="ltr">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={signal} margin={{ top: 24, right: 8, left: 0, bottom: 0 }}>
                    <defs>
                      <linearGradient id="liveSignal" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#047857" stopOpacity={0.28} />
                        <stop offset="100%" stopColor="#047857" stopOpacity={0.02} />
                      </linearGradient>
                    </defs>
                    {broadcast.segments.map((seg, i) => (
                      <ReferenceArea
                        key={seg.label + seg.start_seconds}
                        x1={seg.start_seconds}
                        x2={Math.min(seg.end_seconds, duration)}
                        fill={SEGMENT_FILLS[i % 2]}
                        fillOpacity={1}
                        label={{ value: seg.label, position: 'insideTop', fontSize: 10, fill: '#64748b', fontFamily: 'Tajawal, sans-serif' }}
                      />
                    ))}
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                    <XAxis
                      dataKey="timestamp_seconds"
                      type="number"
                      domain={[0, duration]}
                      tickFormatter={clock}
                      tick={{ fontSize: 11, fill: '#94a3b8' }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={false} tickLine={false} width={36} />
                    {clips?.map((c, i) => (
                      <ReferenceArea
                        key={`clip-${c.start_time}`}
                        x1={c.start_time}
                        x2={c.end_time}
                        fill="#e11d48"
                        fillOpacity={selected === null || selected === i ? 0.18 : 0.06}
                        stroke={selected === i ? '#e11d48' : undefined}
                        strokeOpacity={0.6}
                      />
                    ))}
                    <Tooltip
                      contentStyle={{ borderRadius: 16, fontFamily: 'Tajawal, sans-serif', direction: 'rtl', textAlign: 'right' }}
                      labelFormatter={(s: number) => `الدقيقة ${clock(s)}`}
                      formatter={(v: number) => [v.toFixed(1), 'مستوى التفاعل']}
                    />
                    <Area type="monotone" dataKey="engagement_level" stroke="#047857" strokeWidth={2} fill="url(#liveSignal)" isAnimationActive={false} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
              {baseline != null && (
                <p className="text-[11px] text-slate-500 font-arabic mt-2">
                  المستوى المعتاد خلال البث ≈ {baseline.toFixed(1)}. القفزة تُحتسب مقارنة بالدقيقتين السابقتين لها، لا بكامل البث.
                </p>
              )}
            </div>

            {/* ── Ranked clip opportunities ── */}
            <div className={CARD}>
              <div className="flex items-center gap-2 mb-4">
                <div className="p-1.5 bg-rose-50 rounded-lg text-rose-600">
                  <Scissors className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-slate-900 font-arabic">اللقطات المقترحة</h3>
                  <p className="text-[11px] text-slate-500 font-arabic">مرتبة حسب حجم القفزة</p>
                </div>
              </div>

              {clips && clips.length === 0 && (
                <p className="text-sm text-slate-500 font-arabic text-center py-8">
                  لم تُرصد قفزة واضحة؛ الإشارة ضمن تذبذبها المعتاد.
                </p>
              )}

              <ul className="space-y-2.5">
                {clips?.map((c, i) => (
                  <li key={c.start_time}>
                    <button
                      onClick={() => setSelected(selected === i ? null : i)}
                      aria-pressed={selected === i}
                      className={`w-full text-right p-3 rounded-xl border transition-all cursor-pointer ${
                        selected === i ? 'border-rose-300 bg-rose-50/60' : 'border-slate-200/80 hover:border-slate-300 hover:bg-slate-50'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="w-6 h-6 flex-shrink-0 rounded-lg bg-slate-900 text-white text-xs font-bold flex items-center justify-center">
                            {i + 1}
                          </span>
                          <span className="text-sm font-bold text-slate-900 font-arabic truncate">{c.segment_label}</span>
                        </div>
                        <span className="inline-flex items-center gap-1 text-xs font-black text-rose-700 flex-shrink-0" dir="ltr">
                          <TrendingUp className="w-3.5 h-3.5" />+{Math.round(c.spike_magnitude)}%
                        </span>
                      </div>
                      <div className="flex items-center justify-between mt-2 text-[11px] text-slate-500 font-arabic">
                        <span>
                          من <span dir="ltr" className="font-bold text-slate-700">{clock(c.start_time)}</span> إلى{' '}
                          <span dir="ltr" className="font-bold text-slate-700">{clock(c.end_time)}</span>
                          {' '}({c.end_time - c.start_time} ث)
                        </span>
                        <span>الثقة {Math.round(c.confidence * 100)}%</span>
                      </div>
                      <div className="mt-2 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                        <div className="h-full bg-rose-500 rounded-full" style={{ width: `${Math.round(c.confidence * 100)}%` }} />
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className={CARD}>
      <p className="text-xs font-bold text-slate-500 font-arabic">{label}</p>
      <p className="text-2xl font-black text-slate-900 font-arabic mt-1" dir="ltr" style={{ textAlign: 'right' }}>{value}</p>
      <p className="text-[11px] text-slate-400 font-arabic mt-1 truncate">{hint}</p>
    </div>
  );
}
