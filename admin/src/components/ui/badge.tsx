import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const badgeVariants = cva(
  'inline-flex items-center gap-1.5 rounded-pill px-2.5 py-0.5 text-xs font-medium transition-colors',
  {
    variants: {
      variant: {
        default: 'bg-surface-2 text-text-secondary',
        success: 'bg-[rgba(63,217,132,0.12)] text-success',
        danger: 'bg-[rgba(247,85,85,0.12)] text-danger',
        warning: 'bg-[rgba(245,181,68,0.12)] text-warning',
      },
    },
    defaultVariants: {
      variant: 'default',
    },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

// badgeVariants exported for consumers who need variant access (e.g. Badge-like custom components)
// eslint-disable-next-line react-refresh/only-export-components
export { Badge, badgeVariants };
