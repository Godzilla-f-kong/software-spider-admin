export const relationResources: Record<string, string> = {
  software_id: 'software',
  source_id: 'sources',
  release_id: 'releases',
  variant_id: 'variants',
  artifact_id: 'artifacts',
  generated_content_id: 'content',
}

export const jobTargetResources: Record<string, string> = {
  candidate: 'candidates',
  software: 'software',
  source: 'sources',
  release: 'releases',
  variant: 'variants',
  artifact: 'artifacts',
  content: 'content',
  listing: 'listings',
}

export function relationResource(field: string, targetType?: unknown): string | undefined {
  if (field === 'target_id') return jobTargetResources[String(targetType ?? '')]
  return relationResources[field]
}
