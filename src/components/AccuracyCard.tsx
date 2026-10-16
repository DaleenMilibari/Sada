import { useEffect, useState } from 'react';
import { Target } from 'lucide-react';
import { ApiError, apiFetch, describeError } from '../lib/api';
import type { ModelAccuracy } from '../types';

// The backend recomputes the backtest at most hourly.
const REFRESH_MS = 10 * 60_000;

function ErrorBar({ label, value, max, tone }: { label: string; value: number; max: number; tone: string }) {
  return (
    <div>
      <div className="flex items-center justify-between text-[11px] font-arabic mb-1">
        <span className="text-slate-600">{label}</span>
        <span className="font-bold text-slate-900">{value.toFixed(1)}%</span>
      </div>
      <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${tone}`} style={{ width: `${Math.min(100, (value / max) * 100)}%` }} />
      </div>
    </div>
  );
}

// Measured accuracy of the day-7 views prediction (Task 2). Fetches its own data.
export default function AccuracyCard() {
  const [accuracy, setAccuracy] = useState<ModelAccuracy | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = async () => {
      try {
        setAccuracy(await apiFetch<ModelAccuracy>('/api/model/accuracy'));
        setError(null);
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) return; // App switches to the login screen
        setError(describeError(err).title);
      }
    };
    load();
    const id = window.setInterval(load, REFRESH_MS);
    return () => window.clearInterval(id);
  }, []);

  const ready = accuracy?.status === 'ok' && accuracy.mape !== null && accuracy.baseline_mape !== null;

  return (
    <div className="bg-white border border-slate-200/90 rounded-2xl p-5 shadow-xs">
      <div className="flex items-center justify-between gap-2 mb-4">
        <div className="flex items-center gap-2">
          <div className="p-1.5 bg-violet-50 rounded-lg text-violet-600">
            <Target className="w-4 h-4" />
          </div>
          <h3 className="text-sm font-bold text-slate-900 font-arabic">دقة توقّع المشاهدات</h3>
        </div>
        {ready && accuracy.beats_baseline !== null && (
          <span
            className={`px-2.5 py-1 rounded-full text-[11px] font-bold font-arabic border ${
              accuracy.beats_baseline
                ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                : 'bg-amber-50 text-amber-700 border-amber-200'
            }`}
          >
            {accuracy.beats_baseline ? 'أدق من خط الأساس' : 'لم يتفوق على خط الأساس'}
          </span>
        )}
      </div>

      {!accuracy && !error && <div className="h-28 bg-slate-100 rounded-xl animate-pulse" />}
      {!accuracy && error && <p className="text-sm text-slate-500 font-arabic text-center py-6">{error}</p>}

      {accuracy && !ready && (
        <div className="text-center py-4">
          <span className="inline-block mb-2 px-2 py-0.5 rounded-full text-[11px] font-bold bg-slate-100 text-slate-600 font-arabic">
            تجريبي
          </span>
          <p className="text-sm text-slate-600 font-arabic">
            لا يكفي سجل اللقطات بعد لقياس الدقة: نحتاج مقاطع لها مشاهدات مقيسة في اليوم الأول واليوم السابع.
          </p>
          <p className="text-[11px] text-slate-400 font-arabic mt-1">مقاطع مكتملة حتى الآن: {accuracy.n_eligible}</p>
        </div>
      )}

      {ready && (
        <>
          <div className="space-y-3">
            <ErrorBar
              label="متوسط الخطأ النسبي (MAPE) لنموذجنا"
              value={accuracy.mape!}
              max={Math.max(accuracy.mape!, accuracy.baseline_mape!)}
              tone="bg-violet-500"
            />
            <ErrorBar
              label="خط الأساس: وسيط مشاهدات القناة"
              value={accuracy.baseline_mape!}
              max={Math.max(accuracy.mape!, accuracy.baseline_mape!)}
              tone="bg-slate-400"
            />
          </div>

          <div className="grid grid-cols-2 gap-3 mt-4">
            <div className="bg-slate-50 rounded-xl p-3">
              <p className="text-xl font-black text-slate-900">{Math.round(accuracy.top10_hit_rate! * 100)}%</p>
              <p className="text-[11px] text-slate-500 font-arabic">من توقّعنا لأعلى 10 كانت فعلًا ضمن الأعلى 10</p>
            </div>
            <div className="bg-slate-50 rounded-xl p-3">
              <p className="text-xl font-black text-slate-900">{accuracy.n_test}</p>
              <p className="text-[11px] text-slate-500 font-arabic">مقطعًا في اختبار الدقة</p>
            </div>
          </div>

          <p className="text-[11px] text-slate-500 font-arabic mt-4 leading-relaxed">
            دُرّب النموذج على مقاطع {accuracy.train_window} ثم اختُبر على أحدث 20٪ ({accuracy.test_window}):
            توقّعنا مشاهدات اليوم السابع من مشاهدات اليوم الأول بمنحنى النمو المعتاد لكل قناة، وقارنّاها بالأرقام الفعلية.
          </p>
        </>
      )}
    </div>
  );
}
