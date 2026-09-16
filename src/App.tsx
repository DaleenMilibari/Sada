import { useState } from 'react';
import Sidebar from './components/Sidebar';
import DashboardView from './components/DashboardView';
import OptimizerView from './components/OptimizerView';
import BroadcastView from './components/BroadcastView';
import Toast, { type ToastMessage } from './components/Toast';
import type { ActiveView } from './types';
import { Bell, Search, Radio, CheckCheck, X, AlertTriangle, Trophy, BarChart3 } from 'lucide-react';

const VIEW_TITLES: Record<ActiveView, { title: string; subtitle: string }> = {
  dashboard: {
    title: 'لوحة التحكم والأنماط السلوكية',
    subtitle: 'الوكيل الأول · تحليل سلوك الجمهور والمنصات',
  },
  optimizer: {
    title: 'مُحسن ومختبر المحتوى',
    subtitle: 'الوكيل الثاني · اختبار المتغيرات وتحديد النسخة الفائزة',
  },
  broadcast: {
    title: 'مراقب البث والتشخيص الذكي',
    subtitle: 'الوكيل الثالث · رصد البث المباشر والتشخيص عبر RAG',
  },
};

const INITIAL_NOTIFICATIONS = [
  {
    id: 'n1',
    title: 'تنبيه لقطة فيروسية مكتشفة',
    desc: 'ارتفاع تفاعل بنسبة 45% عند الدقيقة 12:04 (حديث الدعم السكني)',
    time: 'منذ 8 دقائق',
    unread: true,
    type: 'viral' as const,
  },
  {
    id: 'n2',
    title: 'توليد النسخة المحسّنة الفائزة',
    desc: 'توقع زيادة التفاعل بنسبة +24% مع التوقيت الموصى به (8:00 م)',
    time: 'منذ 24 دقيقة',
    unread: true,
    type: 'optimize' as const,
  },
  {
    id: 'n3',
    title: 'اكتمال دورة الأنماط الأسبوعية',
    desc: 'تم تسجيل 3 أنماط جديدة في المخزن المشترك بنجاح',
    time: 'منذ ساعة',
    unread: false,
    type: 'report' as const,
  },
];

interface TopBarProps {
  view: ActiveView;
  onSearchClick: () => void;
  unreadCount: number;
  onToggleNotifications: () => void;
}

function TopBar({ view, onSearchClick, unreadCount, onToggleNotifications }: TopBarProps) {
  const current = VIEW_TITLES[view];

  return (
    <header className="fixed top-0 left-0 right-64 h-16 bg-white/95 backdrop-blur-md border-b border-slate-200/90 flex items-center justify-between px-7 z-40">
      {/* ── Right side in RTL: Breadcrumb & View Info ── */}
      <div className="text-right">
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-bold text-emerald-800 bg-emerald-50 border border-emerald-200/80 px-2 py-0.5 rounded-md font-arabic">
            صدى
          </span>
          <span className="text-xs text-slate-300">/</span>
          <h1 className="text-sm font-black text-slate-900 font-arabic tracking-tight">
            {current.title}
          </h1>
        </div>
        <p className="text-[10px] font-semibold text-slate-400 font-arabic mt-0.5">
          {current.subtitle}
        </p>
      </div>

      {/* ── Left side in RTL: Live status + Quick search + Notifications ── */}
      <div className="flex items-center gap-3">
        {/* Live Broadcast Pulse Pill */}
        <div className="hidden sm:flex items-center gap-2 bg-slate-50 border border-slate-200/80 px-3 py-1.5 rounded-xl text-xs font-arabic">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-red-600"></span>
          </span>
          <span className="font-bold text-slate-700">بث مباشر متصل</span>
        </div>

        {/* Search Input */}
        <div className="relative hidden md:block">
          <div className="flex items-center gap-2 bg-slate-50 hover:bg-slate-100 border border-slate-200/80 rounded-xl px-3.5 py-1.5 w-56 transition-colors">
            <Search className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />
            <input
              type="text"
              placeholder="بحث في الأنماط والبث..."
              className="bg-transparent text-xs text-slate-700 placeholder:text-slate-400 font-arabic outline-none flex-1 text-right"
            />
          </div>
        </div>

        {/* Notifications Bell */}
        <div className="relative">
          <button
            onClick={onToggleNotifications}
            className="p-2.5 rounded-xl bg-slate-50 hover:bg-slate-100 border border-slate-200/80 text-slate-600 hover:text-slate-900 transition-colors cursor-pointer relative"
            title="التنبيهات"
          >
            <Bell className="w-4 h-4" />
            {unreadCount > 0 && (
              <span className="absolute 1.5 top-1.5 right-1.5 w-2 h-2 rounded-full bg-red-500 ring-2 ring-white" />
            )}
          </button>
        </div>
      </div>
    </header>
  );
}

export default function App() {
  const [activeView, setActiveView] = useState<ActiveView>('dashboard');
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const [notifications, setNotifications] = useState(INITIAL_NOTIFICATIONS);
  const [isNotificationsOpen, setIsNotificationsOpen] = useState(false);

  const showToast = (title: string, description?: string, type: 'success' | 'info' | 'warning' = 'success') => {
    const id = Date.now().toString() + Math.random().toString(36).substring(2, 5);
    const newToast: ToastMessage = { id, title, description, type };
    setToasts((prev) => [...prev, newToast]);

    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4000);
  };

  const handleDismissToast = (id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  const unreadCount = notifications.filter((n) => n.unread).length;

  const markAllAsRead = () => {
    setNotifications((prev) => prev.map((n) => ({ ...n, unread: false })));
    showToast('تم تحديد جميع التنبيهات كمقروءة', '', 'info');
  };

  return (
    <div className="min-h-screen bg-slate-50 font-arabic" dir="rtl">
      {/* ── Global Sidebar ── */}
      <Sidebar activeView={activeView} onViewChange={setActiveView} />

      {/* ── Global TopBar ── */}
      <TopBar
        view={activeView}
        onSearchClick={() => {}}
        unreadCount={unreadCount}
        onToggleNotifications={() => setIsNotificationsOpen(!isNotificationsOpen)}
      />

      {/* ── Notifications Dropdown Popover ── */}
      {isNotificationsOpen && (
        <div className="fixed top-16 left-8 z-50 w-80 bg-white border border-slate-200/90 rounded-2xl shadow-xl shadow-slate-900/10 p-4 animate-slide-up text-right">
          <div className="flex items-center justify-between pb-3 border-b border-slate-100 mb-3">
            <div className="flex items-center gap-1.5">
              <span className="text-xs font-bold text-slate-900 font-arabic">مركز التنبيهات الذكية</span>
              {unreadCount > 0 && (
                <span className="text-[10px] font-bold bg-red-100 text-red-700 px-1.5 py-0.2 rounded-full">
                  {unreadCount} جديد
                </span>
              )}
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={markAllAsRead}
                className="text-[11px] text-emerald-700 hover:text-emerald-900 font-bold p-1 rounded transition-colors"
                title="تحديد كمقروء"
              >
                <CheckCheck className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={() => setIsNotificationsOpen(false)}
                className="text-slate-400 hover:text-slate-600 p-1"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          <div className="space-y-2.5 max-h-72 overflow-y-auto">
            {notifications.map((n) => (
              <div
                key={n.id}
                className={`p-2.5 rounded-xl border transition-all text-right ${
                  n.unread
                    ? 'bg-emerald-50/50 border-emerald-200/70'
                    : 'bg-slate-50/50 border-slate-100 opacity-80'
                }`}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[10px] text-slate-400 font-arabic">{n.time}</span>
                  <div className="flex items-center gap-1.5">
                    <h4 className="text-xs font-bold text-slate-900 font-arabic">{n.title}</h4>
                    {n.type === 'viral' ? (
                      <AlertTriangle className="w-3.5 h-3.5 text-amber-600 flex-shrink-0" />
                    ) : n.type === 'optimize' ? (
                      <Trophy className="w-3.5 h-3.5 text-emerald-600 flex-shrink-0" />
                    ) : (
                      <BarChart3 className="w-3.5 h-3.5 text-blue-600 flex-shrink-0" />
                    )}
                  </div>
                </div>
                <p className="text-[11px] text-slate-600 font-arabic leading-relaxed">{n.desc}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Main View Container ── */}
      <main className="mr-64 pt-16 min-h-screen">
        <div className="p-7 max-w-[1440px] mx-auto">
          {activeView === 'dashboard' && <DashboardView onNotify={showToast} />}
          {activeView === 'optimizer' && <OptimizerView onNotify={showToast} />}
          {activeView === 'broadcast' && <BroadcastView onNotify={showToast} />}
        </div>
      </main>

      {/* ── Global Toast Notifications System ── */}
      <Toast toasts={toasts} onDismiss={handleDismissToast} />
    </div>
  );
}
