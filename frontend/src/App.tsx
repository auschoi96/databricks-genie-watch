import { useState } from 'react'
import { LayoutDashboard, Database, DollarSign, Settings as SettingsIcon, MessageSquare } from 'lucide-react'

import { SpacesList } from './pages/SpacesList'
import { SpaceDetail } from './pages/SpaceDetail'
import { ResourceRollup } from './pages/ResourceRollup'
import { CostExplorer } from './pages/CostExplorer'
import { Feedback } from './pages/Feedback'
import { Settings } from './pages/Settings'

type View =
  | { kind: 'spaces' }
  | { kind: 'space-detail'; spaceId: string }
  | { kind: 'resources' }
  | { kind: 'cost' }
  | { kind: 'feedback' }
  | { kind: 'settings' }

export default function App() {
  const [view, setView] = useState<View>({ kind: 'spaces' })

  return (
    <div className="min-h-screen bg-background text-fg">
      <Header
        active={
          view.kind === 'space-detail' ? 'spaces' : view.kind
        }
        onNavigate={kind => {
          if (kind === 'spaces') setView({ kind: 'spaces' })
          else if (kind === 'resources') setView({ kind: 'resources' })
          else if (kind === 'cost') setView({ kind: 'cost' })
          else if (kind === 'feedback') setView({ kind: 'feedback' })
          else if (kind === 'settings') setView({ kind: 'settings' })
        }}
      />
      <main className="mx-auto max-w-6xl p-6">
        {view.kind === 'spaces' && (
          <SpacesList onOpenSpace={sid => setView({ kind: 'space-detail', spaceId: sid })} />
        )}
        {view.kind === 'space-detail' && (
          <SpaceDetail
            spaceId={view.spaceId}
            onBack={() => setView({ kind: 'spaces' })}
            onOpenSettings={() => setView({ kind: 'settings' })}
          />
        )}
        {view.kind === 'resources' && <ResourceRollup />}
        {view.kind === 'cost' && (
          <CostExplorer onOpenSpace={sid => setView({ kind: 'space-detail', spaceId: sid })} />
        )}
        {view.kind === 'feedback' && <Feedback />}
        {view.kind === 'settings' && <Settings />}
      </main>
    </div>
  )
}

function Header({
  active,
  onNavigate,
}: {
  active: 'spaces' | 'resources' | 'cost' | 'feedback' | 'settings'
  onNavigate: (k: 'spaces' | 'resources' | 'cost' | 'feedback' | 'settings') => void
}) {
  const items: Array<{ kind: typeof active; label: string; icon: React.ReactNode }> = [
    { kind: 'spaces', label: 'Spaces', icon: <LayoutDashboard size={16} /> },
    { kind: 'cost', label: 'Cost', icon: <DollarSign size={16} /> },
    { kind: 'resources', label: 'Resources', icon: <Database size={16} /> },
    { kind: 'feedback', label: 'Feedback', icon: <MessageSquare size={16} /> },
    { kind: 'settings', label: 'Settings', icon: <SettingsIcon size={16} /> },
  ]
  return (
    <header className="border-b border-default bg-background">
      <div className="mx-auto flex max-w-6xl items-center justify-between p-4">
        <div className="flex items-center gap-3">
          <span className="font-display text-xl font-bold">GenieWatch</span>
          <span className="text-xs text-muted">observability for Genie Spaces</span>
        </div>
        <nav className="flex gap-1">
          {items.map(it => (
            <button
              key={it.kind}
              onClick={() => onNavigate(it.kind)}
              className={`flex items-center gap-1 rounded px-3 py-1.5 text-sm ${
                active === it.kind ? 'bg-elevated' : 'text-muted hover:bg-elevated/50'
              }`}
            >
              {it.icon}
              {it.label}
            </button>
          ))}
        </nav>
      </div>
    </header>
  )
}
