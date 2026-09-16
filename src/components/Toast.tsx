import React from 'react';
import { CheckCircle2, AlertCircle, Info, X } from 'lucide-react';

export interface ToastMessage {
  id: string;
  title: string;
  description?: string;
  type?: 'success' | 'info' | 'warning';
}

interface ToastProps {
  toasts: ToastMessage[];
  onDismiss: (id: string) => void;
}

export default function Toast({ toasts, onDismiss }: ToastProps) {
  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-6 left-6 z-50 flex flex-col gap-2 max-w-sm w-full pointer-events-none" dir="rtl">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className="pointer-events-auto flex items-start gap-3 p-4 bg-white border border-slate-200 rounded-2xl shadow-xl shadow-slate-900/5 animate-slide-up transition-all duration-300"
        >
          <div className="flex-shrink-0 mt-0.5">
            {toast.type === 'warning' ? (
              <AlertCircle className="w-5 h-5 text-amber-500" />
            ) : toast.type === 'info' ? (
              <Info className="w-5 h-5 text-blue-500" />
            ) : (
              <CheckCircle2 className="w-5 h-5 text-emerald-600" />
            )}
          </div>
          <div className="flex-1 min-w-0 text-right">
            <h4 className="text-sm font-bold text-slate-900 font-arabic leading-snug">
              {toast.title}
            </h4>
            {toast.description && (
              <p className="text-xs text-slate-500 font-arabic mt-0.5 leading-relaxed">
                {toast.description}
              </p>
            )}
          </div>
          <button
            onClick={() => onDismiss(toast.id)}
            className="flex-shrink-0 p-1 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-100 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      ))}
    </div>
  );
}
