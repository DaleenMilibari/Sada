import { BarChart3, Wand2, Tv2, ChevronLeft, ShieldCheck } from 'lucide-react';
import type { ActiveView } from '../types';

interface SidebarProps {
  activeView: ActiveView;
  onViewChange: (view: ActiveView) => void;
}

const navItems: { id: ActiveView; icon: React.ReactNode; label: string }[] = [
  {
    id: 'dashboard',
    icon: <BarChart3 className="w-5 h-5" />,
    label: 'لوحة التحكم والأنماط',
  },
  {
    id: 'optimizer',
    icon: <Wand2 className="w-5 h-5" />,
    label: 'مُحسن ومختبر المحتوى',
  },
  {
    id: 'broadcast',
    icon: <Tv2 className="w-5 h-5" />,
    label: 'مراقب البث والتشخيص',
  },
];

export default function Sidebar({ activeView, onViewChange }: SidebarProps) {
  return (
    <aside className="fixed right-0 top-0 h-full w-64 bg-white border-l border-slate-200 flex flex-col z-50 select-none shadow-xs">
      {/* ── Clean Brand Header ── */}
      <div className="px-5 py-5 border-b border-slate-100 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <img
            src="/favicon.png"
            alt="صدى"
            className="h-7 w-auto object-contain"
          />
          <span className="text-[11px] font-bold text-slate-400 font-arabic border-r border-slate-200 pr-2.5">
            ذكاء البث المتزامن
          </span>
        </div>
      </div>

      {/* ── Sync Badge ── */}
      <div className="mx-4 mt-4 mb-2">
        <div className="flex items-center justify-between bg-emerald-50/70 border border-emerald-200/70 rounded-xl px-3 py-2">
          <div className="flex items-center gap-2">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-600"></span>
            </span>
            <span className="text-xs font-bold text-emerald-800 font-arabic">
              تزامن الوكلاء نشط
            </span>
          </div>
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
        </div>
      </div>

      {/* ── Navigation ── */}
      <nav className="flex-1 px-3 pt-3 overflow-y-auto">
        <p className="text-[10px] font-bold text-slate-400 tracking-wider px-3 mb-2 font-arabic uppercase">
          الوحدات
        </p>

        <ul className="space-y-1">
          {navItems.map((item) => {
            const isActive = activeView === item.id;
            return (
              <li key={item.id}>
                <button
                  onClick={() => onViewChange(item.id)}
                  className={`w-full flex items-center justify-between px-3.5 py-3 rounded-xl text-right transition-all duration-150 group cursor-pointer ${
                    isActive
                      ? 'bg-emerald-700 text-white shadow-xs font-bold'
                      : 'text-slate-700 hover:bg-slate-50 hover:text-slate-900 font-medium'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <div
                      className={`p-1 rounded-lg transition-colors ${
                        isActive
                          ? 'text-white'
                          : 'text-slate-400 group-hover:text-emerald-700'
                      }`}
                    >
                      {item.icon}
                    </div>
                    <span className="text-sm font-arabic">
                      {item.label}
                    </span>
                  </div>

                  <ChevronLeft
                    className={`w-4 h-4 transition-transform ${
                      isActive
                        ? 'text-white opacity-90 -translate-x-0.5'
                        : 'text-slate-300 group-hover:text-slate-500'
                    }`}
                  />
                </button>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* ── Footer ── */}
      <div className="p-3 border-t border-slate-100 bg-slate-50/50">
        <div className="flex items-center justify-between bg-white border border-slate-200/80 rounded-xl p-2 shadow-2xs">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-lg bg-emerald-700 flex items-center justify-center text-white font-bold text-xs font-arabic">
              ص
            </div>
            <div className="text-right">
              <p className="text-xs font-bold text-slate-800 font-arabic leading-tight">
                المشرف العام
              </p>
              <p className="text-[10px] text-slate-400 font-arabic">
                إدارة البث
              </p>
            </div>
          </div>
          <ShieldCheck className="w-4 h-4 text-emerald-600" />
        </div>
      </div>
    </aside>
  );
}
