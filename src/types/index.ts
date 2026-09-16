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
