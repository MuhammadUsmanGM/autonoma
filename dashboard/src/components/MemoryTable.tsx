import { Trash2 } from 'lucide-react'
import type { Memory } from '../types'

interface Props {
  memories: Memory[]
  onDelete: (id: number) => void
}

const TYPE_COLORS: Record<string, string> = {
  fact: 'bg-blue-500/15 text-blue-400 border-blue-500/20',
  preference: 'bg-purple-500/15 text-purple-400 border-purple-500/20',
  remember: 'bg-[var(--accent-dim)] text-[var(--accent)] border-[var(--accent)]/20',
  conversation_summary: 'bg-green-500/15 text-green-400 border-green-500/20',
}

export default function MemoryTable({ memories, onDelete }: Props) {
  if (memories.length === 0) {
    return (
      <p className="text-sm text-[var(--text-muted)] py-8 text-center">
        No memories found.
      </p>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-[var(--border)] text-left text-[var(--text-muted)]">
            <th className="py-3 px-4 font-medium">Content</th>
            <th className="py-3 px-4 font-medium w-28">Type</th>
            <th className="py-3 px-4 font-medium w-24 text-right">Importance</th>
            <th className="py-3 px-4 font-medium w-28">Created</th>
            <th className="py-3 px-4 font-medium w-16"></th>
          </tr>
        </thead>
        <tbody>
          {memories.map((m) => (
            <tr
              key={m.id}
              className="border-b border-[var(--border)]/50 hover:bg-white/[0.02] transition-colors"
            >
              <td className="py-3 px-4 max-w-md">
                <p className="truncate">{m.content}</p>
              </td>
              <td className="py-3 px-4">
                <span
                  className={`px-2 py-1 rounded text-xs font-medium border ${
                    TYPE_COLORS[m.type] || TYPE_COLORS.remember
                  }`}
                >
                  {m.type}
                </span>
              </td>
              <td className="py-3 px-4 text-right font-mono text-xs">
                {m.importance.toFixed(2)}
              </td>
              <td className="py-3 px-4 text-xs text-[var(--text-muted)]">
                {m.created_at?.slice(0, 10)}
              </td>
              <td className="py-3 px-4">
                <button
                  onClick={() => onDelete(m.id)}
                  className="p-1.5 rounded-lg hover:bg-red-500/10 text-[var(--text-muted)] hover:text-red-400 transition-colors cursor-pointer"
                >
                  <Trash2 size={14} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
