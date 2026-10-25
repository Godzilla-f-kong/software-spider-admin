import axios from 'axios'
import { ElMessage } from 'element-plus'
import { apiErrorText, tr } from '../i18n'

export type Row = Record<string, unknown> & { id: number }
export interface Page<T> { items: T[]; total: number; page: number; page_size: number }
export interface LookupOption { id: number; label: string }

export const client = axios.create({ baseURL: '/api/v1', timeout: 15000 })
client.interceptors.response.use(response => response, error => {
  const message = error.response?.data?.error?.message ?? error.message ?? tr('请求失败', 'Request failed')
  ElMessage.error(apiErrorText(message))
  return Promise.reject(error)
})

export const api = {
  async lookup(resource: string, params: Record<string, unknown> = {}): Promise<LookupOption[]> {
    return (await client.get<{ items: LookupOption[] }>(`/lookups/${resource}`, { params })).data.items
  },
  async list(resource: string, params: Record<string, unknown> = {}): Promise<Page<Row>> {
    return (await client.get<Page<Row>>(`/${resource}`, { params })).data
  },
  async get(resource: string, id: number): Promise<Row> {
    return (await client.get<Row>(`/${resource}/${id}`)).data
  },
  async create(resource: string, data: Record<string, unknown> | number[]): Promise<Row> {
    return (await client.post<Row>(`/${resource}`, data)).data
  },
  async update(resource: string, id: number, data: Record<string, unknown>): Promise<Row> {
    return (await client.patch<Row>(`/${resource}/${id}`, data)).data
  },
  async action<T = Row>(path: string, data?: Record<string, unknown>, timeout = 15000): Promise<T> {
    return (await client.post<T>(path, data, { timeout })).data
  },
}
