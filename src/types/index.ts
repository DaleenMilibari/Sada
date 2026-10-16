export type ActiveView = 'dashboard' | 'optimizer' | 'broadcast';

export interface MetricCard {
  label: string;
  value: string;
  change: string;
  changeType: 'positive' | 'negative' | 'neutral';
  isSpecial?: boolean;
}

export interface ContentVariant {
  id: 'original' | 'optimized' | 'alternative';
  title: string;
  badge: string;
  content: string;
  hashtags?: string[];
  lift?: string;
  isWinner?: boolean;
  reasons?: string[];
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'agent';
  content: string | React.ReactNode;
  timestamp: string;
  sources?: string[];
}

export interface NotificationItem {
  id: string;
  title: string;
  desc: string;
  time: string;
  unread: boolean;
  type: 'viral' | 'optimize' | 'report';
}

// --- Task 2: Trends & Viral Prediction (mirrors backend/schemas.py) ---

export interface VideoOut {
  video_id: string;
  platform: 'youtube' | 'instagram';
  channel_id: string;
  entity_key: string;
  channel_name_ar: string;
  title: string;
  url: string;
  published_at: string;
  duration_seconds: number | null;
  content_type: 'short' | 'video' | 'live' | 'image' | 'carousel';
  topic: string;
  topic_source: 'rule' | 'llm';
  view_count: number | null;
  like_count: number | null;
  comment_count: number | null;
  stats_updated_at: string | null;
}

export interface TrendingItem {
  video: VideoOut;
  views_per_hour: number;
  velocity_index: number;
  viral_score: number; // 0-1
  predicted_views_7d: number | null;
  reason: string;
}

export interface ModelAccuracy {
  method: string;
  status: 'ok' | 'insufficient_history';
  train_window: string | null;
  test_window: string | null;
  n_test: number;
  n_eligible: number;
  mape: number | null; // percent
  baseline_mape: number | null; // percent
  top10_hit_rate: number | null; // 0-1
  beats_baseline: boolean | null;
  computed_at: string;
}
