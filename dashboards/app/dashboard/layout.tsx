import type { Metadata } from 'next';

export const metadata: Metadata = {
  title:       'Sentinel AI — Risk Operations Center',
  description: 'Real-time pulse scoring and behavioural risk analytics dashboard',
};

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return children;
}