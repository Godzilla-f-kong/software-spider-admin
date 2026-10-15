const formatter = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
})

export function formatBeijingTime(value: unknown): string {
  if (typeof value !== 'string' || !value) return '—'
  // Current API timestamps carry +08:00. Older naive API values were UTC.
  const explicit = /(?:Z|[+-]\d{2}:\d{2})$/.test(value)
  const parsed = new Date(explicit ? value : `${value}Z`)
  if (Number.isNaN(parsed.getTime())) return value
  const parts = Object.fromEntries(formatter.formatToParts(parsed).map(part => [part.type, part.value]))
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second} UTC+8`
}
