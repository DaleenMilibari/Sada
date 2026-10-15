import { useState } from 'react';
import { Lock, Loader2, LogIn } from 'lucide-react';
import { ApiError, login } from '../lib/api';

interface LoginViewProps {
  onSuccess: () => void;
}

export default function LoginView({ onSuccess }: LoginViewProps) {
  const [password, setPassword] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!password || isSubmitting) return;
    setIsSubmitting(true);
    setError(null);
    try {
      await login(password);
      onSuccess();
    } catch (err) {
      const status = err instanceof ApiError ? err.status : 0;
      setError(
        status === 401
          ? 'كلمة المرور غير صحيحة'
          : status === 429
            ? 'محاولات كثيرة، انتظر دقيقة ثم أعد المحاولة'
            : 'تعذر الاتصال بالخادم، أعد المحاولة'
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 font-arabic flex items-center justify-center p-4" dir="rtl">
      <form
        onSubmit={handleSubmit}
        className="bg-white border border-slate-200/90 rounded-3xl p-8 w-full max-w-sm shadow-sm text-right animate-slide-up"
      >
        <div className="flex flex-col items-center mb-6">
          <img src="/favicon.png" alt="صدى" className="h-10 w-auto object-contain mb-3" />
          <h1 className="text-lg font-black text-slate-900">تسجيل الدخول إلى صدى</h1>
          <p className="text-xs text-slate-400 mt-1">منصة ذكاء التفاعل مع الجمهور</p>
        </div>

        <label htmlFor="password" className="block text-xs font-bold text-slate-500 mb-2">
          كلمة المرور
        </label>
        <div className="relative mb-3">
          <Lock className="absolute right-3 top-3 w-4 h-4 text-slate-400 pointer-events-none" />
          <input
            id="password"
            type="password"
            autoFocus
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full text-right text-sm text-slate-800 bg-slate-50 border border-slate-200 rounded-xl py-2.5 pr-10 pl-3 outline-none focus:border-emerald-500 transition-all"
          />
        </div>

        {error && (
          <p role="alert" className="text-xs font-bold text-red-600 bg-red-50 border border-red-200 rounded-xl px-3 py-2 mb-3">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={!password || isSubmitting}
          className="w-full flex items-center justify-center gap-2 bg-emerald-700 hover:bg-emerald-800 disabled:bg-slate-300 text-white font-bold text-sm py-3 rounded-2xl shadow-sm transition-all cursor-pointer disabled:cursor-not-allowed"
        >
          {isSubmitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <LogIn className="w-4 h-4" />}
          <span>دخول</span>
        </button>
      </form>
    </div>
  );
}
