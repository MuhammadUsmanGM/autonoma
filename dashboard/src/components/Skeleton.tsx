import { motion } from 'framer-motion'

interface Props {
  className?: string
  variant?: 'rectangular' | 'circular' | 'text'
}

export default function Skeleton({ className = '', variant = 'rectangular' }: Props) {
  return (
    <div 
      className={`relative overflow-hidden bg-white/[0.03] dark:bg-white/[0.02] ${
        variant === 'circular' ? 'rounded-full' : 'rounded-lg'
      } ${className}`}
    >
      <motion.div
        animate={{
          x: ['-100%', '100%'],
        }}
        transition={{
          duration: 1.5,
          repeat: Infinity,
          ease: 'linear',
        }}
        className="absolute inset-0 bg-gradient-to-r from-transparent via-white/[0.05] to-transparent"
      />
    </div>
  )
}
