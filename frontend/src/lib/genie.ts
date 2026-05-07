/** Build the Databricks UI URL for a Genie Space.
 *
 *  Genie spaces live at /genie/rooms/<id> on the workspace host. The host
 *  is exposed via /api/settings/health.workspace_host. If unknown, fall
 *  back to a relative path that opens within the same workspace context.
 */
export function genieSpaceUrl(spaceId: string, workspaceHost: string | null): string {
  const id = encodeURIComponent(spaceId)
  if (workspaceHost) {
    const host = workspaceHost.replace(/\/+$/, '')
    return `${host}/genie/rooms/${id}`
  }
  return `/genie/rooms/${id}`
}
