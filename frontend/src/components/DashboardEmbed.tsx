import { useMemo } from 'react'

interface Props {
  dashboardId: string
  height?: number
  parameters?: Record<string, string>
}

/** Embeds a Databricks Lakeview dashboard via iframe. */
export function DashboardEmbed({ dashboardId, height = 720, parameters }: Props) {
  const src = useMemo(() => {
    const base = `/embed/dashboardsv3/${dashboardId}`
    if (!parameters || Object.keys(parameters).length === 0) return base
    const qs = new URLSearchParams(parameters).toString()
    return `${base}?${qs}`
  }, [dashboardId, parameters])

  if (!dashboardId) {
    return (
      <div className="rounded-lg border border-default bg-elevated p-6 text-sm text-muted">
        Set <code className="font-mono">DASHBOARD_COST_ID</code> in <code>app.yaml</code> to enable
        the workspace-wide Cost Explorer dashboard.
      </div>
    )
  }

  return (
    <iframe
      title="Cost Explorer"
      src={src}
      style={{ width: '100%', height, border: 0 }}
      allow="clipboard-write"
    />
  )
}
