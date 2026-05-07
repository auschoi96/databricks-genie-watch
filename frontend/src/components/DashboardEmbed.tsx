import { useMemo, useState } from 'react'
import { ExternalLink } from 'lucide-react'

interface Props {
  dashboardId: string
  workspaceHost: string | null
  height?: number
  parameters?: Record<string, string>
}

/** Embed a Databricks Lakeview dashboard via iframe.
 *
 *  Databricks Apps and the workspace UI live on different origins
 *  (*.databricksapps.com vs *.cloud.databricks.com), so the iframe src
 *  must be the absolute workspace URL. Cross-origin embedding can be
 *  blocked by X-Frame-Options on some workspaces — a fallback "Open in
 *  Databricks" button is always shown so the user has a working path.
 */
export function DashboardEmbed({
  dashboardId, workspaceHost, height = 720, parameters,
}: Props) {
  const [iframeFailed, setIframeFailed] = useState(false)

  const { embedSrc, openSrc } = useMemo(() => {
    if (!dashboardId || !workspaceHost) {
      return { embedSrc: '', openSrc: '' }
    }
    const host = workspaceHost.replace(/\/+$/, '')
    const qs = parameters
      ? '&' + new URLSearchParams(parameters).toString()
      : ''
    return {
      // Published embed URL. Some workspaces serve it at /embed/dashboardsv3/<id>;
      // others at /dashboardsv3/<id>/published. Try the embed path; if X-Frame-
      // Options blocks it, the user clicks the "Open in Databricks" button below.
      embedSrc: `${host}/embed/dashboardsv3/${dashboardId}${qs ? '?' + qs.slice(1) : ''}`,
      openSrc: `${host}/sql/dashboardsv3/${dashboardId}/published${qs}`,
    }
  }, [dashboardId, workspaceHost, parameters])

  if (!dashboardId) {
    return (
      <div className="rounded-lg border border-default bg-elevated p-6 text-sm text-muted">
        Set <code className="font-mono">DASHBOARD_COST_ID</code> in <code>app.yaml</code> to enable
        the workspace-wide Cost Explorer dashboard.
      </div>
    )
  }

  if (!workspaceHost) {
    return (
      <div className="rounded-lg border border-default bg-elevated p-6 text-sm text-muted">
        Workspace host not yet known — reload the page once auth has settled.
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between border-b border-default px-4 py-2">
        <p className="text-xs text-muted">
          Dashboard ID <code className="font-mono">{dashboardId}</code>
        </p>
        <a
          href={openSrc}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 rounded border border-default px-3 py-1 text-sm hover:bg-elevated"
        >
          <ExternalLink size={14} /> Open in Databricks
        </a>
      </div>
      {!iframeFailed ? (
        <iframe
          title="Cost Explorer"
          src={embedSrc}
          style={{ width: '100%', height, border: 0 }}
          onError={() => setIframeFailed(true)}
        />
      ) : (
        <div className="p-6 text-center text-sm text-muted">
          The dashboard could not be embedded inline (likely due to cross-origin
          frame restrictions). Click <strong>Open in Databricks</strong> above to
          view it in a new tab.
        </div>
      )}
    </div>
  )
}
