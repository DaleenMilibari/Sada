export type ActiveView = 'dashboard' | 'optimizer' | 'broadcast' | 'audience';

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
  platform: 'youtube' | 'instagram' | 'x';
  channel_id: string;
  entity_key: string;
  channel_name_ar: string;
  title: string;
  url: string;
  published_at: string;
  duration_seconds: number | null;
  content_type: 'short' | 'video' | 'live' | 'image' | 'carousel' | 'text';
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

// --- Task 3: Live dashboard & analytics (mirrors backend/schemas.py) ---

export type Platform = 'youtube' | 'instagram' | 'x';

export interface AnalyticsSummary {
  generated_at: string;
  data_as_of: string | null;
  days: number;
  platform: Platform | null;
  min_post_age_days: number;
  totals: { posts: number; views: number; likes: number; comments: number; engagement_rate: number | null };
  by_platform: { platform: Platform; accounts: number; posts: number; followers: number; likes: number; comments: number }[];
  by_channel: {
    platform: Platform;
    entity_key: string;
    name_ar: string;
    subscriber_count: number | null;
    posts: number;
    views: number | null;
    median_performance_index: number;
    engagement_rate: number | null;
  }[];
  by_content_type: { platform: Platform; content_type: string; posts: number; median_performance_index: number }[];
  by_topic: { topic: string; label_ar: string; posts: number; median_performance_index: number }[];
  best_times: { platform: Platform; day_of_week: string; hour: number; median_performance_index: number; n: number }[];
}

export interface CollectorRun {
  id: number;
  status: string;
  started_at: string;
  finished_at: string | null;
  error: string | null;
}

export interface CollectorStatus {
  enabled: boolean;
  youtube_enabled: boolean;
  instagram_enabled: boolean;
  schedule_enabled: boolean;
  interval_minutes: number;
  total_videos: number;
  runs: CollectorRun[];
}

// --- Task 4: Spikes, drops & diagnosis ---

export interface Alert {
  alert_id: string;
  kind: 'spike' | 'drop';
  video: VideoOut;
  metric: 'views' | 'interactions';
  observed: number;
  expected: number;
  ratio: number;
  severity: 'high' | 'medium';
  detected_at: string;
  detection: 'level' | 'velocity';
  basis: 'same_age' | 'plateau' | 'snapshots';
  peers: number;
  explanation: string;
}

export interface ContributingFactor {
  reason: string;
  supporting_metric: string;
  evidence_source_title: string;
  evidence_url_or_ref: string;
  confidence: number;
}

export interface DiagnosisResult {
  diagnosis: string;
  contributing_factors: ContributingFactor[];
  recommendations: string[];
  low_confidence: boolean;
}

// --- Audience analysis (mirrors backend/schemas.py::AudienceSummary) ---

export interface SentimentStats {
  comments: number;
  classified: number; // the rest are unclassified - never counted as neutral
  positive: number;
  negative: number;
  neutral: number;
  positive_share: number | null; // null when fewer than 10 classified
  negative_share: number | null;
  net_sentiment: number | null; // (positive - negative) / classified
}

export interface AudienceSummary {
  generated_at: string;
  days: number;
  platform: Platform | null;
  totals: SentimentStats;
  by_channel: (SentimentStats & { platform: Platform; entity_key: string; name_ar: string })[];
  intents: {
    intent: 'praise' | 'criticism' | 'request' | 'question' | 'other';
    label_ar: string;
    count: number;
    share: number | null;
    examples: {
      text: string;
      url: string;
      platform: Platform;
      channel_name_ar: string;
      like_count: number | null;
      sentiment: 'positive' | 'negative' | 'neutral' | null;
    }[];
  }[];
  discussed_posts: (SentimentStats & { video: VideoOut })[];
  follower_growth: {
    platform: Platform;
    entity_key: string;
    name_ar: string;
    first_at: string;
    last_at: string;
    first: number;
    last: number;
    change: number | null; // null until two measurements half a day apart
    change_pct: number | null;
    points: { at: string; followers: number }[];
  }[];
}
