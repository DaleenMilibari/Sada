// Shared HTTP client for the Sada backend.
// Base URL comes from VITE_API_BASE at build time (set it in Vercel's env vars).

export const API_BASE = (import.meta.env.VITE_API_BASE ?? 'http://localhost:8000').replace(/\/$/, '');

const TOKEN_KEY = 'sada.token';
export const UNAUTHORIZED_EVENT = 'sada:unauthorized';

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Storage unavailable (private mode) - session just won't persist across reloads.
  }
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  const token = getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, 'network');
  }

  if (res.status === 401 && !path.startsWith('/api/auth/')) {
    setToken(null);
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      // non-JSON error body
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

// User-facing Arabic message for a failed request.
export function describeError(err: unknown): { title: string; desc: string } {
  const status = err instanceof ApiError ? err.status : 0;
  switch (status) {
    case 0:
      return { title: 'تعذر الاتصال بالخادم', desc: 'تحقق من اتصالك بالإنترنت ثم أعد المحاولة' };
    case 401:
      return { title: 'انتهت الجلسة', desc: 'يرجى تسجيل الدخول مجددًا' };
    case 429:
      return { title: 'طلبات كثيرة', desc: 'تم تجاوز الحد المسموح، انتظر دقيقة ثم أعد المحاولة' };
    case 503:
      return { title: 'خدمة الذكاء الاصطناعي غير مهيأة', desc: 'مفتاح Gemini API غير مضبوط على الخادم' };
    case 502:
      return { title: 'تعذر الحصول على رد من نموذج الذكاء الاصطناعي', desc: 'أعد المحاولة بعد قليل' };
    default:
      return { title: 'حدث خطأ غير متوقع', desc: `رمز الخطأ: ${status}` };
  }
}

export async function login(password: string): Promise<void> {
  const { token } = await apiFetch<{ token: string; expires_at: number }>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ password }),
  });
  setToken(token);
}

export async function isAuthRequired(): Promise<boolean> {
  const { auth_required } = await apiFetch<{ auth_required: boolean }>('/api/auth/status');
  return auth_required;
}

// "كل الفترة": a window wider than anything collected, so every stored post/comment is included.
export const ALL_DAYS = 3650;
export const daysLabel = (d: number) => (d >= ALL_DAYS ? 'كل الفترة' : `${d} يوماً`);
