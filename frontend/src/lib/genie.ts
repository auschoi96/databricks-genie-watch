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

/** Build a Databricks deep-link to a specific Genie conversation / message.
 *
 *  Falls back to the space-level URL when conversation_id is missing.
 *  The exact query-param format is best-effort — the Genie UI may evolve.
 *  Tested empirically against the deployed workspace before relying on it
 *  for navigation.
 */
export function genieMessageUrl(
  spaceId: string,
  conversationId: string | null,
  messageId: string | null,
  workspaceHost: string | null,
): string {
  const base = genieSpaceUrl(spaceId, workspaceHost)
  if (!conversationId) return base
  const qs = new URLSearchParams({ conversation_id: conversationId })
  if (messageId) qs.set('message_id', messageId)
  return `${base}?${qs.toString()}`
}
