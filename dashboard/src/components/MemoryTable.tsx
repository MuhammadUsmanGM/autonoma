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
          <tr className="border-b border-[var(--border)] text-left text-[var(--text-muted)] bg-white/[0.01]">
            <th className="py-4 px-6 font-bold uppercase tracking-widest text-[10px]">Transmission</th>
            <th className="py-4 px-6 font-bold uppercase tracking-widest text-[10px] w-28">Protocol</th>
            <th className="py-4 px-6 font-bold uppercase tracking-widest text-[10px] w-24 text-right">Weight</th>
            <th className="py-4 px-6 font-bold uppercase tracking-widest text-[10px] w-28 text-right">Registry</th>
            <th className="py-4 px-6 font-bold uppercase tracking-widest text-[10px] w-16"></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-white/[0.02]">
          {memories.map((m) => (
            <tr
              key={m.id}
              className="hover:bg-white/[0.03] transition-all group"
            >
              <td className="py-4 px-6 max-w-md">
                <p className="text-white/80 group-hover:text-white transition-colors line-clamp-2">{m.content}</p>
              </td>
              <td className="py-4 px-6">
                <span
                  className={`px-2 py-0.5 rounded-lg text-[10px] font-bold uppercase tracking-wider border ${
                    TYPE_COLORS[m.type] || TYPE_COLORS.remember
                  }`}
                >
                  {m.type.replace('_', ' ')}
                </span>
              </td>
              <td className="py-4 px-6 text-right font-mono text-[11px] text-[var(--text-muted)] group-hover:text-[var(--accent)] transition-colors">
                {m.importance.toFixed(3)}
              </td>
              <td className="py-4 px-6 text-right text-[11px] text-[var(--text-muted)]">
                {new Date(m.created_at || Date.now()).toLocaleDateString([], { month: 'short', day: 'numeric', year: '2-digit' })}
              </td>
              <td className="py-4 px-6 text-right">
                <button
                  onClick={() => onDelete(m.id)}
                  className="p-2 rounded-xl hover:bg-red-500/20 text-white/20 hover:text-red-400 transition-all cursor-pointer"
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
