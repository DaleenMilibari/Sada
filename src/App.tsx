import { lazy, Suspense, useEffect, useState } from 'react';
import Sidebar from './components/Sidebar';
import LoginView from './components/LoginView';
import Toast, { type ToastMessage } from './components/Toast';
import type { ActiveView, CollectorStatus, NotificationItem, OptimizerDraft } from './types';
import { apiFetch, getToken, isAuthRequired, setToken, UNAUTHORIZED_EVENT } from './lib/api';
import { Bell, CheckCheck, X, AlertTriangle, Trophy, BarChart3, LogOut, Loader2 } from 'lucide-react';

const DashboardView = lazy(() => import('./components/DashboardView'));
const OptimizerView = lazy(() => import('./components/OptimizerView'));
const AlertsView = lazy(() => import('./components/BroadcastView'));
const AudienceView = lazy(() => import('./components/AudienceView'));
const LiveClipsView = lazy(() => import('./components/LiveClipsView'));

const VIEW_TITLES: Record<ActiveView, { title: string; subtitle: string }> = {
  dashboard: {
    title: 'لوحة التحليلات والأنماط',
    subtitle: 'بيانات حقيقية من يوتيوب وإنستغرام وإكس · تحديث تلقائي كل دقيقة',
  },
  optimizer: {
    title: 'مُحسن ومختبر المحتوى',
    subtitle: 'الوكيل الثاني · اختبار المتغيرات وتحديد النسخة الفائزة',
  },
  broadcast: {
    title: 'التنبيهات والتشخيص',
    subtitle: 'رصد القفزات والانخفاضات وتشخيص أسبابها بالأدلة',
  },
  live: {
    title: 'لقطات البث المباشر',
    subtitle: 'رصد قفزات التفاعل أثناء البث واقتراح لقطات للنشر · إشارة محاكاة حالياً',
  },
  audience: {
    title: 'تحليل الجمهور',
    subtitle: 'مشاعر الجمهور وطلباته ونمو المتابعين من تعليقات وردود حقيقية',
  },
};

// Notification-center entries are recorded from real agent events (success toasts),
// keyed to a view so the icon matches the agent that produced them.
const VIEW_NOTIFICATION_TYPE: Record<ActiveView, NotificationItem['type']> = {
  dashboard: 'report',
  optimizer: 'optimize',
  broadcast: 'viral',
  live: 'viral',
  audience: 'report',
};

const STATUS_REFRESH_MS = 60_000;

// Real collector state from /api/collector/status - not a decorative badge.
function CollectorPill() {
  const [status, setStatus] = useState<CollectorStatus | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const data = await apiFetch<CollectorStatus>('/api/collector/status');
        if (alive) {
          setStatus(data);
          setFailed(false);
        }
      } catch {
        if (alive) setFailed(true);
      }
    };
    load();
    const id = window.setInterval(load, STATUS_REFRESH_MS);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  const last = status?.runs[0];
  let dot = 'bg-slate-400';
  let label = 'جارٍ التحقق من الجامع...';
  if (failed) {
    dot = 'bg-red-500';
    label = 'تعذر قراءة حالة الجامع';
  } else if (status) {
    if (!status.enabled) {
      label = 'جمع البيانات متوقف (لا مفاتيح)';
    } else if (last?.status === 'running') {
      dot = 'bg-blue-500 animate-pulse';
      label = 'جارٍ جمع البيانات...';
    } else if (last?.status === 'failed') {
      dot = 'bg-red-500';
      label = 'آخر جمع فشل';
    } else if (last?.status === 'partial') {
      dot = 'bg-amber-500';
      label = `جمع جزئي · ${status.total_videos.toLocaleString('en')} منشور`;
    } else if (last) {
      dot = 'bg-emerald-500';
      label = `الجامع يعمل · ${status.total_videos.toLocaleString('en')} منشور`;
    } else {
      label = 'لم يعمل الجامع بعد';
    }
  }
  return (
    <div className="hidden sm:flex items-center gap-2 bg-slate-50 border border-slate-200/80 px-3 py-1.5 rounded-xl text-xs font-arabic" title={last?.error ?? undefined}>
      <span className={`inline-flex rounded-full h-2 w-2 ${dot}`} />
      <span className="font-bold text-slate-700">{label}</span>
    </div>
  );
}

interface TopBarProps {
  view: ActiveView;
  unreadCount: number;
  onToggleNotifications: () => void;
  onLogout?: () => void;
}

function TopBar({ view, unreadCount, onToggleNotifications, onLogout }: TopBarProps) {
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
        <CollectorPill />

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

        {onLogout && (
          <button
            onClick={onLogout}
            className="p-2.5 rounded-xl bg-slate-50 hover:bg-red-50 border border-slate-200/80 text-slate-600 hover:text-red-600 transition-colors cursor-pointer"
            title="تسجيل الخروج"
          >
            <LogOut className="w-4 h-4" />
          </button>
        )}
      </div>
    </header>
  );
}

type AuthState = 'checking' | 'login' | 'ready';

export default function App() {
  const [authState, setAuthState] = useState<AuthState>(getToken() ? 'ready' : 'checking');
  const [authRequired, setAuthRequired] = useState(true);
  const [activeView, setActiveView] = useState<ActiveView>('dashboard');
  // An insight elsewhere (e.g. an audience request) can open the optimizer pre-filled.
  const [optimizerDraft, setOptimizerDraft] = useState<OptimizerDraft | null>(null);
  const openOptimizer = (draft: OptimizerDraft) => {
    setOptimizerDraft(draft);
    setActiveView('optimizer');
  };
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [isNotificationsOpen, setIsNotificationsOpen] = useState(false);

  useEffect(() => {
    if (authState !== 'checking') return;
    // No stored token: ask the backend whether a login is needed at all
    // (auth is off in local dev when SADA_ACCESS_PASSWORD is unset).
    isAuthRequired()
      .then((required) => {
        setAuthRequired(required);
        setAuthState(required ? 'login' : 'ready');
      })
      .catch(() => setAuthState('login'));
  }, [authState]);

  useEffect(() => {
    const onUnauthorized = () => setAuthState('login');
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  const handleLogout = () => {
    setToken(null);
    setNotifications([]);
    setAuthState('login');
  };

  const showToast = (title: string, description?: string, type: 'success' | 'info' | 'warning' = 'success') => {
    const id = Date.now().toString() + Math.random().toString(36).substring(2, 5);
    const newToast: ToastMessage = { id, title, description, type };
    setToasts((prev) => [...prev, newToast]);

    if (type === 'success' && description) {
      const notification: NotificationItem = {
        id,
        title,
        desc: description,
        time: new Date().toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' }),
        unread: true,
        type: VIEW_NOTIFICATION_TYPE[activeView],
      };
      setNotifications((prev) => [notification, ...prev].slice(0, 20));
    }

    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4000);
  };

  if (authState === 'checking') {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <Loader2 className="w-6 h-6 text-emerald-600 animate-spin" />
      </div>
    );
  }

  if (authState === 'login') {
    return <LoginView onSuccess={() => setAuthState('ready')} />;
  }

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
        unreadCount={unreadCount}
        onToggleNotifications={() => setIsNotificationsOpen(!isNotificationsOpen)}
        onLogout={authRequired ? handleLogout : undefined}
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
            {notifications.length === 0 && (
              <p className="text-xs text-slate-400 font-arabic text-center py-6">لا توجد تنبيهات بعد</p>
            )}
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
          <Suspense fallback={<div className="flex justify-center py-24"><Loader2 className="w-6 h-6 text-emerald-600 animate-spin" /></div>}>
            {activeView === 'dashboard' && <DashboardView onNotify={showToast} onCreateDraft={openOptimizer} />}
            {activeView === 'optimizer' && <OptimizerView key={optimizerDraft?.text ?? 'blank'} onNotify={showToast} initialDraft={optimizerDraft} />}
            {activeView === 'broadcast' && <AlertsView onNotify={showToast} />}
            {activeView === 'live' && <LiveClipsView onNotify={showToast} />}
            {activeView === 'audience' && <AudienceView onNotify={showToast} onCreateDraft={openOptimizer} />}
          </Suspense>
        </div>
      </main>

      {/* ── Global Toast Notifications System ── */}
      <Toast toasts={toasts} onDismiss={handleDismissToast} />
    </div>
  );
}
