import type { ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

export default function AuroraBackground({ children }: Props) {
  return (
    <div className="relative min-h-screen bg-aurora-deep">
      {/* Animated gradient blobs — aurora-drift defined in tailwind.config.js */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden">
        <div
          className="absolute top-[-20%] left-[10%] w-[60%] h-[60%] rounded-full opacity-20 blur-[100px] animate-aurora-drift"
          style={{ background: 'radial-gradient(circle, rgba(99,102,241,0.4), transparent 70%)' }}
        />
        <div
          className="absolute bottom-[-10%] right-[5%] w-[50%] h-[50%] rounded-full opacity-[0.15] blur-[100px] animate-aurora-drift"
          style={{
            background: 'radial-gradient(circle, rgba(236,72,153,0.3), transparent 70%)',
            animationDelay: '3s',
            animationDirection: 'alternate-reverse',
          }}
        />
        <div
          className="absolute top-[40%] right-[25%] w-[35%] h-[35%] rounded-full opacity-10 blur-[80px] animate-aurora-drift"
          style={{
            background: 'radial-gradient(circle, rgba(45,212,191,0.3), transparent 70%)',
            animationDelay: '6s',
          }}
        />
      </div>
      {/* Content sits above the blobs */}
      <div className="relative z-10">
        {children}
      </div>
    </div>
  );
}
